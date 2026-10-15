#!/usr/bin/env python3
"""Resolve trusted models.dev observations per field group and fill old gaps.

All allowlisted records for an ID participate. Source priority chooses a value
independently for each field group; explicit conflicts and their losing records
are saved in the local resolution snapshot for publication as a sidecar.
"""

import json
from pathlib import Path

from model_sources import canonical_model_id, discover_exact_models, discover_trusted_models
from seed_modelsdev import resolve_model_observations


ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "models.json"
SNAPSHOT = ROOT / ".cache" / "models.dev.json"
RESOLUTION = ROOT / ".cache" / "modelsdev-resolution.json"
LEGACY_FILL_FIELDS = (
    "knowledge_cutoff", "release_date", "open_weights",
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
    """Let the selected source win explicit prices without erasing omissions."""
    if not isinstance(existing, dict):
        return incoming
    result = {**existing, **incoming}
    if "tiers" not in incoming and "tiers" in result:
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


def sync_trusted(definition, base):
    old_context = definition.get("context_window_tokens")
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


def fill_legacy(definition, base):
    changed = 0
    for field in LEGACY_FILL_FIELDS:
        if definition.get(field) is None and field in base:
            definition[field] = base[field]
            changed += 1
    return changed


def collapse_catalog_aliases(models):
    """Keep one canonical identity when legacy catalog keys are route aliases."""
    removed = []
    for model_id in sorted(list(models)):
        canonical_id = canonical_model_id(model_id)
        if canonical_id is None or canonical_id == model_id:
            continue
        if canonical_id in models:
            alias = models.pop(model_id)
            canonical = models[canonical_id]
            sources = sorted(
                set(canonical.get("provider_sources", []))
                | set(alias.get("provider_sources", []))
            )
            if sources:
                canonical["provider_sources"] = sources
        else:
            models[canonical_id] = models.pop(model_id)
        removed.append((model_id, canonical_id))
    return removed


def main():
    with CATALOG.open() as file:
        catalog = json.load(file)
    with SNAPSHOT.open() as file:
        models_dev = json.load(file)
    collapsed = collapse_catalog_aliases(catalog["models"])
    trusted = discover_trusted_models(models_dev)
    exact = discover_exact_models(models_dev)

    trusted_matches = legacy_matches = trusted_updates = legacy_fills = 0
    resolution_models = {}
    conflicts = []
    for model_id, definition in catalog["models"].items():
        observations = trusted.get(model_id)
        if observations:
            trusted_matches += 1
            base, provenance, model_conflicts = resolve_model_observations(observations)
            trusted_updates += sync_trusted(definition, base)
            provider_sources = sorted({source.provider for source in observations})
            if definition.get("provider_sources") != provider_sources:
                definition["provider_sources"] = provider_sources
                trusted_updates += 1
            provenance["provider_sources"] = {
                "value": provider_sources,
                "observations": [
                    {"provider": provider_id, "source_id": source_id}
                    for provider_id, source_id in sorted({
                        (source.provider, source.source_id)
                        for source in observations
                    })
                ],
            }
            resolution_models[model_id] = {
                "scope": "publisher_api_model",
                "fields": provenance,
            }
            conflicts.extend(
                {"model_id": model_id, **conflict} for conflict in model_conflicts
            )
        else:
            legacy_observations = exact.get(model_id) or exact.get(model_id.lower())
            if legacy_observations:
                legacy_matches += 1
                base, provenance, model_conflicts = resolve_model_observations(
                    legacy_observations,
                    allowed_field_groups={"descriptive"},
                )
                legacy_fills += fill_legacy(definition, base)
                resolution_models[model_id] = {
                    "scope": "legacy_exact_id_fallback",
                    "fields": provenance,
                }
                conflicts.extend(
                    {"model_id": model_id, **conflict} for conflict in model_conflicts
                )

    # The legacy global fields conflated API defaults, model support, and
    # Agena's request preference. New catalog data is provider-scoped; refresh
    # it exactly from the current trusted observations so stale facts disappear.
    for definition in catalog["models"].values():
        definition.pop("supports_verbosity", None)
        definition.pop("default_verbosity", None)
        definition.pop("verbosity_by_provider", None)

    for model_id, model in catalog["models"].items():
        observations = trusted.get(model_id)
        if not observations:
            definition = model
            definition.pop("provider_sources", None)
            continue
        definition, _provenance, _conflicts = resolve_model_observations(observations)
        scoped_verbosity = definition.get("verbosity_by_provider")
        if scoped_verbosity:
            model["verbosity_by_provider"] = scoped_verbosity

    with CATALOG.open("w") as file:
        json.dump(catalog, file, ensure_ascii=False, indent=2)
        file.write("\n")
    RESOLUTION.write_text(
        json.dumps(
            {"models": resolution_models, "conflicts": conflicts},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"trusted records: {trusted_matches}, fields updated: {trusted_updates}")
    print(f"legacy exact-ID records: {legacy_matches}, fields filled: {legacy_fills}")
    if collapsed:
        print(f"collapsed {len(collapsed)} route aliases to canonical IDs")
        for alias, canonical in collapsed:
            print(f"  {alias} -> {canonical}")
    print(f"wrote {CATALOG}")


if __name__ == "__main__":
    main()
