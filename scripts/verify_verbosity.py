#!/usr/bin/env python3
"""Ensure supported models.dev verbosity metadata reaches the final catalog.

Trusted publisher observations are resolved by the semantics field priority
unless a curated patch overrides the field. Legacy exact-ID observations have
zero priority for semantics and are retained for audit without affecting model
verbosity metadata.
"""
import glob
import json
import os
import sys

from model_sources import discover_exact_models, discover_trusted_models
from seed_modelsdev import VERBOSITY_SOURCE_FIELDS, resolve_model_observations


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "models.json")
SNAPSHOT = os.path.join(ROOT, ".cache", "models.dev.json")
PATCH_DIR = os.path.join(ROOT, "curation", "patches")
FIELDS = tuple(VERBOSITY_SOURCE_FIELDS.values())


def load_patches():
    """Return the last patch value for each model/verbosity field."""
    overrides = {}
    for path in sorted(glob.glob(os.path.join(PATCH_DIR, "*.json"))):
        with open(path) as file:
            patch = json.load(file)
        for model_id, definition in (patch.get("models") or {}).items():
            for field in FIELDS:
                if field in definition:
                    overrides.setdefault(model_id, {})[field] = definition[field]
    return overrides


def check_final_value(model_id, definition, field, expected, errors, source):
    if expected is None:
        if field in definition:
            errors.append(f"{model_id}: {field} should be absent after {source}")
    elif definition.get(field) != expected:
        errors.append(
            f"{model_id}: {field}={definition.get(field)!r}, "
            f"expected {expected!r} from {source}"
        )


def main():
    with open(CATALOG) as file:
        catalog = json.load(file)
    with open(SNAPSHOT) as file:
        models_dev = json.load(file)

    models = catalog.get("models")
    if not isinstance(models, dict):
        print("models.json: 'models' must be an object", file=sys.stderr)
        return 1

    trusted = discover_trusted_models(models_dev)
    exact = discover_exact_models(models_dev)

    patch_overrides = load_patches()
    errors = []
    trusted_sources = legacy_sources = trusted_fields = legacy_fields = 0

    for model_id, definition in models.items():
        observations = trusted.get(model_id)
        source_kind = "trusted models.dev field winner"
        is_trusted = bool(observations)
        if is_trusted:
            resolved, _provenance, _conflicts = resolve_model_observations(observations)
            trusted_sources += 1
        else:
            observations = exact.get(model_id) or exact.get(model_id.lower())
            resolved = {}
            if observations:
                resolved, _provenance, _conflicts = resolve_model_observations(observations)
                source_kind = "legacy exact-ID models.dev field winner"
                legacy_sources += 1

        upstream = {field: resolved[field] for field in FIELDS if field in resolved}
        if is_trusted:
            trusted_fields += len(upstream)
        else:
            legacy_fields += len(upstream)

        overrides = patch_overrides.get(model_id, {})
        for field in FIELDS:
            if field in overrides:
                check_final_value(
                    model_id, definition, field, overrides[field], errors,
                    "curated patch",
                )
                continue

            if field not in upstream:
                continue
            expected = upstream[field]
            if is_trusted:
                check_final_value(
                    model_id, definition, field, expected, errors, source_kind
                )
            elif definition.get(field) is None:
                errors.append(
                    f"{model_id}: {field} from {source_kind} was not copied into the catalog"
                )

    catalog_models_with_verbosity = sum(
        any(field in definition for field in FIELDS) for definition in models.values()
    )
    print(
        "verbosity source records: "
        f"trusted={trusted_sources} ({trusted_fields} field values), "
        f"legacy exact-ID={legacy_sources} ({legacy_fields} field values)"
    )
    print(
        "catalog models with verbosity metadata: "
        f"{catalog_models_with_verbosity}/{len(models)}"
    )
    if errors:
        print(f"\nERRORS ({len(errors)}):", file=sys.stderr)
        for error in errors[:80]:
            print(f"  {error}", file=sys.stderr)
        return 1

    print("ALL PASS: source verbosity metadata is retained according to catalog precedence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
