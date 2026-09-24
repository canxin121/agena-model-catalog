#!/usr/bin/env python3
"""Sync trusted model records, then fill gaps in legacy catalog entries.

First-party models.dev records are the base for canonical models. Curated
patches run after this script and take precedence over that base. Records from
other providers can only fill missing fields in pre-existing catalog entries;
they cannot change trusted models or introduce new identities.
"""

import json
from pathlib import Path

from model_sources import discover_trusted_models
from seed_modelsdev import seed_definition


ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "models.json"
SNAPSHOT = ROOT / ".cache" / "models.dev.json"
LEGACY_FILL_FIELDS = (
    "description", "knowledge_cutoff", "release_date", "open_weights",
    "context_window_tokens", "max_input_tokens", "max_output_tokens", "pricing",
)


def merge_capabilities(existing, incoming, source_wins):
    """Keep unspecified signals, and resolve explicit trusted signals."""
    if existing is None:
        return incoming
    if isinstance(existing, list):
        existing = {"supported": existing}
    supported = set(existing.get("supported") or [])
    unsupported = set(existing.get("unsupported") or [])
    source_supported = set(incoming.get("supported") or [])
    source_unsupported = set(incoming.get("unsupported") or [])
    if source_wins:
        supported -= source_unsupported
        unsupported -= source_supported
        supported |= source_supported
        unsupported |= source_unsupported
    else:
        supported |= source_supported - unsupported
        unsupported |= source_unsupported - supported
    result = dict(existing)
    if supported:
        result["supported"] = sorted(supported)
    else:
        result.pop("supported", None)
    if unsupported:
        result["unsupported"] = sorted(unsupported)
    else:
        result.pop("unsupported", None)
    return result


def merge_pricing(existing, incoming):
    """Update explicit source prices and retain only usable legacy thresholds."""
    if not isinstance(existing, dict):
        return incoming
    result = {**existing, **incoming}
    if "tiers" not in incoming and "tiers" in result:
        # Old gateway-derived catalogs contain tier lists with no threshold,
        # and sometimes multiple conflicting prices for the same threshold.
        # Neither can describe a canonical model's price schedule.
        thresholds = {}
        for tier in result["tiers"]:
            key = (tier.get("tier_type"), tier.get("size_tokens"))
            if None in key:
                continue
            if key in thresholds and thresholds[key] != tier:
                thresholds = {}
                break
            thresholds[key] = tier
        if thresholds:
            result["tiers"] = list(thresholds.values())
        else:
            result.pop("tiers")
    return result


def sync_trusted(definition, source):
    old_context = definition.get("context_window_tokens")
    base = seed_definition(source.model, source.origin)
    changed = 0
    for field, value in base.items():
        if field in ("input", "features"):
            value = merge_capabilities(definition.get(field), value, source_wins=True)
        elif field == "pricing":
            value = merge_pricing(definition.get(field), value)
        if definition.get(field) != value:
            definition[field] = value
            changed += 1

    context = definition.get("context_window_tokens")
    input_limit = definition.get("max_input_tokens")
    if "max_input_tokens" not in base and isinstance(context, int):
        if input_limit == old_context and context != old_context:
            definition["max_input_tokens"] = context
            changed += 1
        elif isinstance(input_limit, int) and input_limit > context:
            definition["max_input_tokens"] = context
            changed += 1
    return changed


def fill_legacy(definition, model):
    base = seed_definition(model, definition.get("origin"))
    changed = 0
    for field in LEGACY_FILL_FIELDS:
        if definition.get(field) is None and field in base:
            definition[field] = base[field]
            changed += 1
    for field in ("input", "features"):
        if field in base:
            merged = merge_capabilities(definition.get(field), base[field], source_wins=False)
            if definition.get(field) != merged:
                definition[field] = merged
                changed += 1
    return changed


def main():
    with CATALOG.open() as file:
        catalog = json.load(file)
    with SNAPSHOT.open() as file:
        models_dev = json.load(file)
    trusted = discover_trusted_models(models_dev)

    # Exact-ID fallback preserves the legacy coverage for catalog entries that
    # have no first-party record. It never takes precedence over trusted data.
    exact = {}
    for provider in models_dev.values():
        for raw_id, model in (provider.get("models") or {}).items():
            exact.setdefault(model.get("id") or raw_id, model)
            exact.setdefault(raw_id, model)

    trusted_matches = legacy_matches = trusted_updates = legacy_fills = 0
    for model_id, definition in catalog["models"].items():
        source = trusted.get(model_id)
        if source is not None:
            trusted_matches += 1
            trusted_updates += sync_trusted(definition, source)
        else:
            model = exact.get(model_id) or exact.get(model_id.lower())
            if model is not None:
                legacy_matches += 1
                legacy_fills += fill_legacy(definition, model)

    with CATALOG.open("w") as file:
        json.dump(catalog, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(f"trusted records: {trusted_matches}, fields updated: {trusted_updates}")
    print(f"legacy exact-ID records: {legacy_matches}, fields filled: {legacy_fills}")
    print(f"wrote {CATALOG}")


if __name__ == "__main__":
    main()
