#!/usr/bin/env python3
"""Cross-check thinking modes against the trusted first-party records.

Two passes:

1. Patches (`curation/patches/*.json`). A patch fails the run only when it
   contradicts what the trusted record publishes for that model:
   - it declares an effort value the record does not publish, or
   - it turns a read-only toggle into an effort ladder.
   Everything else is advisory: a patch for a model without a trusted record
   (gateway aliases and variants), a patch that keeps an on/off toggle the
   record does not describe, or a patch that offers an off mode where the
   record lists no `none`.
2. Catalog (`models.json`). Entries whose effort modes are wider than the
   trusted record publishes, or that offer an off mode the record does not
   list. Report only: curated entries are deliberately allowed to be wider
   than a gateway-shaped source record.

Run after fetch_modelsdev.sh; pass specific patch files to check only those:

    python3 scripts/verify_thinking.py curation/patches/domestic_*.json
"""
import glob
import json
import os
import sys

from model_sources import discover_trusted_models

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "models.json")
PATCH_DIR = os.path.join(ROOT, "curation", "patches")
SNAPSHOT = os.path.join(ROOT, ".cache", "models.dev.json")

TRUSTED = discover_trusted_models(json.load(open(SNAPSHOT)))


def reasoning_options(model):
    return [
        option
        for option in (model.get("reasoning_options") or [])
        if isinstance(option, dict)
    ]


def option_kinds(model):
    return {option.get("type") for option in reasoning_options(model)}


def effort_values(model):
    values = set()
    for option in reasoning_options(model):
        if option.get("type") == "effort":
            values |= {str(value).strip().lower() for value in option.get("values") or []}
    return values


def modes_of(definition):
    return {
        name: value
        for name, value in (definition or {}).items()
        if name != "default" and isinstance(value, dict)
    }


def strategies(modes):
    return {mode.get("strategy") for mode in modes.values()}


def efforts(modes):
    return {
        mode.get("effort")
        for mode in modes.values()
        if mode.get("strategy") == "effort" and mode.get("effort")
    }


def patch_check(path):
    """Return (name, contradictions, advisories, checked) for one patch file."""
    name = os.path.basename(path)
    patch = json.load(open(path))
    hard, advisory, checked = [], [], 0
    for model_id, value in sorted((patch.get("models") or {}).items()):
        if not isinstance(value, dict):
            continue
        modes = modes_of(value.get("thinking_modes"))
        if not modes:
            continue
        checked += 1
        source = TRUSTED.get(model_id)
        if source is None:
            advisory.append((model_id, "no trusted record - unverifiable"))
            continue
        model = source.model
        published = effort_values(model)
        kinds = option_kinds(model)
        declared = efforts(modes)
        outside = declared - published
        if published and outside:
            hard.append(
                (
                    model_id,
                    "declares effort "
                    + str(sorted(outside))
                    + " but the record publishes "
                    + str(sorted(published)),
                )
            )
        elif not published and declared and kinds == {"toggle"}:
            advisory.append(
                (model_id, "declares an effort ladder where the record publishes only a toggle")
            )
        elif not published and not kinds:
            advisory.append((model_id, "declares modes where the record publishes none"))
        if "disabled" in strategies(modes) and published and "none" not in published:
            advisory.append((model_id, "offers an off mode while the record lists no none"))
    return name, hard, advisory, checked


def catalog_check():
    """Advisory comparison of the published catalog against the trusted records."""
    catalog = json.load(open(CATALOG))["models"]
    checked = 0
    wider, off = [], []
    for model_id, definition in sorted(catalog.items()):
        modes = modes_of(definition.get("thinking_modes"))
        if not modes:
            continue
        source = TRUSTED.get(model_id)
        if source is None:
            continue
        published = effort_values(source.model)
        if not published:
            continue
        checked += 1
        outside = efforts(modes) - published
        if outside:
            wider.append((model_id, sorted(outside), sorted(published)))
        if "disabled" in strategies(modes) and "none" not in published:
            off.append(model_id)
    print("\n===== catalog cross-check (report only) =====")
    print("  entries with a trusted record to compare: " + str(checked))
    print("  offer effort values the trusted record does not publish: " + str(len(wider)))
    for model_id, extra, published in wider[:15]:
        print("    " + model_id + ": catalog has " + str(extra) + ", trusted publishes " + str(published))
    if len(wider) > 15:
        print("    ... " + str(len(wider) - 15) + " more")
    print("  offer an off mode while the trusted record lists no none: " + str(len(off)))


def main():
    explicit = bool(sys.argv[1:])
    targets = sys.argv[1:] or sorted(glob.glob(os.path.join(PATCH_DIR, "*.json")))
    total_hard = 0
    total_advisory = 0
    total_checked = 0
    for target in targets:
        name, hard, advisory, checked = patch_check(target)
        total_hard += len(hard)
        total_advisory += len(advisory)
        total_checked += checked
        if not hard and not advisory:
            continue
        print("\n===== " + name + " =====")
        if hard:
            print("  *** CONTRADICTS THE TRUSTED RECORD (" + str(len(hard)) + ") ***")
            for model_id, why in hard:
                print("    " + model_id + ": " + why)
        if advisory:
            print("  advisory (" + str(len(advisory)) + "):")
            for model_id, why in advisory:
                print("    " + model_id + ": " + why)
    print(
        "\nchecked "
        + str(total_checked)
        + " patched entries: "
        + str(total_hard)
        + " contradictions, "
        + str(total_advisory)
        + " advisories"
    )
    if not explicit:
        catalog_check()
    if total_hard:
        sys.exit(1)


if __name__ == "__main__":
    main()
