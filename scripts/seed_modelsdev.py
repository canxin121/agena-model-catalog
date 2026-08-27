#!/usr/bin/env python3
"""Seed explicitly reviewed new catalog members from models.dev.

The catalog is intentionally not an automatic mirror of every models.dev provider:
curation/seeds.json is the membership gate. Each seed names one canonical catalog id
and one provider/source id whose metadata may be used to create that model. Existing
catalog entries are never overwritten here; later merge + curated patches own updates.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "models.json")
MODELS_DEV = os.path.join(ROOT, ".cache", "models.dev.json")
SEEDS = os.path.join(ROOT, "curation", "seeds.json")

LIFECYCLES = {"active", "preview", "beta", "alpha", "experimental", "deprecated"}
INPUT_MODALITIES = {"text", "image", "document", "audio", "video", "file"}


def load(path):
    with open(path) as f:
        return json.load(f)


def usd(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value == 0:
            return "0"
        return ("%.12g" % value)
    value = str(value).strip()
    return value or None


def pricing_from_cost(cost):
    if not cost:
        return None
    pricing = {}
    mapping = {
        "input": "input_usd_per_million_tokens",
        "output": "output_usd_per_million_tokens",
        "cache_read": "cache_read_usd_per_million_tokens",
        "cache_write": "cache_write_usd_per_million_tokens",
    }
    for source_key, catalog_key in mapping.items():
        value = usd(cost.get(source_key))
        if value is not None:
            pricing[catalog_key] = value
    tiers = []
    for tier in cost.get("tiers") or []:
        item = {}
        if tier.get("type"):
            item["tier_type"] = tier["type"]
        if tier.get("size"):
            item["size_tokens"] = tier["size"]
        for source_key, catalog_key in mapping.items():
            value = usd(tier.get(source_key))
            if value is not None:
                item[catalog_key] = value
        if item:
            tiers.append(item)
    if tiers:
        pricing["tiers"] = tiers
    return pricing or None


def canonical_input_modalities(model):
    values = []
    for value in (model.get("modalities") or {}).get("input") or []:
        value = {"pdf": "document"}.get(value.lower(), value.lower())
        if value in INPUT_MODALITIES and value not in values:
            values.append(value)
    return values


def feature_flags(model):
    source = {
        "reasoning": "reasoning",
        "tool_call": "tool_calling",
        "structured_output": "structured_output",
        "temperature": "temperature",
    }
    supported = []
    unsupported = []
    for source_key, catalog_key in source.items():
        value = model.get(source_key)
        if value is True:
            supported.append(catalog_key)
        elif value is False:
            unsupported.append(catalog_key)
    result = {}
    if supported:
        result["supported"] = supported
    if unsupported:
        result["unsupported"] = unsupported
    return result or None


def find_source_model(models_dev, provider_key, source_id):
    provider = models_dev.get(provider_key)
    if not isinstance(provider, dict):
        return None
    models = provider.get("models") or {}
    if source_id in models:
        return models[source_id]
    for raw_id, model in models.items():
        if (model.get("id") or raw_id) == source_id:
            return model
    return None


def seed_definition(source, origin):
    definition = {}
    status = source.get("status")
    if status in LIFECYCLES:
        definition["lifecycle"] = status

    limits = source.get("limit") or {}
    context = limits.get("context") or limits.get("input")
    if context is not None:
        definition["context_window_tokens"] = context
    if limits.get("input") is not None:
        definition["max_input_tokens"] = limits["input"]
    if limits.get("output") is not None:
        definition["max_output_tokens"] = limits["output"]

    scalar_fields = {
        "description": "description",
        "knowledge": "knowledge_cutoff",
        "release_date": "release_date",
        "last_updated": "last_updated",
        "open_weights": "open_weights",
        "name": "display_name",
    }
    for source_key, catalog_key in scalar_fields.items():
        value = source.get(source_key)
        if value is not None and value != "":
            definition[catalog_key] = value

    definition["origin"] = origin

    interleaved = source.get("interleaved")
    if isinstance(interleaved, dict) and interleaved.get("field"):
        definition["assistant_reasoning_interleaved"] = True
        definition["assistant_reasoning_field"] = interleaved["field"]

    outputs = []
    for value in (source.get("modalities") or {}).get("output") or []:
        value = value.lower()
        if value not in outputs:
            outputs.append(value)
    if outputs:
        definition["output_modalities"] = outputs

    pricing = pricing_from_cost(source.get("cost"))
    if pricing:
        definition["pricing"] = pricing

    inputs = canonical_input_modalities(source)
    if inputs:
        definition["input"] = {"supported": inputs}

    features = feature_flags(source)
    if features:
        definition["features"] = features

    return definition


def main():
    catalog = load(CATALOG)
    models_dev = load(MODELS_DEV)
    seeds_doc = load(SEEDS)
    seeds = seeds_doc.get("models")
    if not isinstance(seeds, dict):
        print("curation/seeds.json: 'models' must be an object", file=sys.stderr)
        return 1

    models = catalog.get("models")
    if not isinstance(models, dict):
        print("models.json: 'models' must be an object", file=sys.stderr)
        return 1

    added = []
    errors = []
    for canonical_id, spec in seeds.items():
        if canonical_id in models:
            continue
        if not isinstance(spec, dict):
            errors.append(f"{canonical_id}: seed spec must be an object")
            continue
        provider = spec.get("provider")
        source_id = spec.get("source_id") or canonical_id
        origin = spec.get("origin")
        if not provider or not origin:
            errors.append(f"{canonical_id}: seed requires provider and origin")
            continue
        source = find_source_model(models_dev, provider, source_id)
        if source is None:
            errors.append(f"{canonical_id}: {provider}/{source_id} not found in models.dev")
            continue
        models[canonical_id] = seed_definition(source, origin)
        added.append((canonical_id, provider, source_id))

    if errors:
        print("seed errors:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    if added:
        catalog["models"] = dict(sorted(models.items()))
        with open(CATALOG, "w") as f:
            json.dump(catalog, f, ensure_ascii=False, indent=2)
            f.write("\n")

    print(f"seeded {len(added)} reviewed models from models.dev")
    for canonical_id, provider, source_id in added:
        print(f"  {canonical_id} <- {provider}/{source_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
