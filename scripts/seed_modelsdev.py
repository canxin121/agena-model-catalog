#!/usr/bin/env python3
"""Discover new canonical models from trusted models.dev sources.

The source policy admits first-party providers and official Hugging Face
organizations. It does not require a new hand-written entry for each model.
Existing catalog entries are preserved; merge and curated patches update them.
"""
import json
import os
import sys

from model_sources import discover_trusted_models

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "models.json")
MODELS_DEV = os.path.join(ROOT, ".cache", "models.dev.json")
MAX_AUTO_ADDITIONS = 100

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
        threshold = tier.get("tier") or tier
        if threshold.get("type"):
            item["tier_type"] = threshold["type"]
        if threshold.get("size"):
            item["size_tokens"] = threshold["size"]
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
    return sorted(values)


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
        result["supported"] = sorted(supported)
    if unsupported:
        result["unsupported"] = sorted(unsupported)
    return result or None


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
    models = catalog.get("models")
    if not isinstance(models, dict):
        print("models.json: 'models' must be an object", file=sys.stderr)
        return 1

    sources = discover_trusted_models(models_dev)
    missing = sorted(sources.keys() - models.keys())
    if len(missing) > MAX_AUTO_ADDITIONS:
        print(
            f"refusing {len(missing)} automatic additions (limit {MAX_AUTO_ADDITIONS}); "
            "review curation/sources.json and the upstream snapshot",
            file=sys.stderr,
        )
        return 1

    added = []
    for canonical_id in missing:
        source = sources[canonical_id]
        models[canonical_id] = seed_definition(source.model, source.origin)
        added.append((canonical_id, source.provider, source.source_id))

    if added:
        catalog["models"] = dict(sorted(models.items()))
        with open(CATALOG, "w") as f:
            json.dump(catalog, f, ensure_ascii=False, indent=2)
            f.write("\n")

    print(f"discovered {len(sources)} trusted canonical ids; added {len(added)} new models")
    for canonical_id, provider, source_id in added:
        print(f"  {canonical_id} <- {provider}/{source_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
