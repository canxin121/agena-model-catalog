#!/usr/bin/env python3
"""Materialise thinking modes from the trusted models.dev reasoning options.

The Agena runtime is data-driven: it no longer infers OpenAI / Anthropic /
Gemini family effort ladders from model IDs, so every thinking mode a model can
offer has to be declared here in models.json. This stage fills the gap for
entries that declare reasoning but have no curated thinking_modes yet.

Rules (conservative - never fabricate):

* Only the trusted first-party record (curation/sources.json) is read. Gateway
  records publish inconsistent subsets of the same model's options.
* Only `effort` options are materialised: each published value becomes a mode
  and `none` becomes the disabled/off mode. `toggle` and `budget_tokens` need a
  vendor-specific request encoding, so those stay curated patches.
* Existing thinking_modes are never modified: curation wins and reruns are no-ops.
* No `default` key is invented; models.dev does not publish one and most curated
  entries leave it unset.

Run after merge_modelsdev.py and before apply_patches.py:

    python3 scripts/derive_thinking_modes.py [--dry-run]
"""
import json
import os
import sys

from model_sources import discover_trusted_models

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "models.json")
SNAPSHOT = os.path.join(ROOT, ".cache", "models.dev.json")

EFFORT_VALUES = ("minimal", "low", "medium", "high", "xhigh", "max")
OFF_KEY = "off"


def reasoning_supported(definition):
    features = definition.get("features")
    if isinstance(features, list):
        return "reasoning" in features
    if isinstance(features, dict):
        return "reasoning" in (features.get("supported") or [])
    return False


def effort_values(model):
    """Published effort values from a models.dev record, in source order."""
    values = []
    for option in model.get("reasoning_options") or []:
        if not isinstance(option, dict) or option.get("type") != "effort":
            continue
        for value in option.get("values") or []:
            value = str(value).strip().lower()
            if value and value not in values:
                values.append(value)
    return values


def modes_from_values(values):
    """Build the thinking_modes map, or None when a value is unknown."""
    modes = {}
    for value in values:
        if value == "none":
            modes[OFF_KEY] = {"display_name": "Off", "strategy": "disabled"}
        elif value in EFFORT_VALUES:
            modes[value] = {
                "display_name": f"Think {value.capitalize()}",
                "strategy": "effort",
                "effort": value,
            }
        else:
            return None
    return modes or None


def main():
    dry_run = "--dry-run" in sys.argv[1:]
    with open(CATALOG) as file:
        document = json.load(file)
    with open(SNAPSHOT) as file:
        models_dev = json.load(file)
    trusted = discover_trusted_models(models_dev)

    derived = []
    curated = 0
    no_trusted = 0
    no_effort = 0
    unknown = []

    for model_id, definition in document["models"].items():
        if definition.get("thinking_modes"):
            curated += 1
            continue
        if not reasoning_supported(definition):
            continue
        source = trusted.get(model_id)
        if source is None:
            no_trusted += 1
            continue
        values = effort_values(source.model)
        if not values:
            no_effort += 1
            continue
        modes = modes_from_values(values)
        if modes is None:
            unknown.append(model_id)
            continue
        definition["thinking_modes"] = modes
        derived.append(model_id)

    print(f"curated thinking_modes kept: {curated}")
    print(
        "reasoning without thinking_modes and without a trusted record: "
        f"{no_trusted}"
    )
    print(f"trusted record publishes no effort options: {no_effort}")
    if unknown:
        print(f"unmapped effort values, skipped ({len(unknown)}): {', '.join(sorted(unknown))}")
    print(f"derived thinking_modes: {len(derived)}")
    for model_id in sorted(derived):
        modes = ",".join(document["models"][model_id]["thinking_modes"])
        print(f"  {model_id}: {modes}")

    if dry_run:
        print("dry run: models.json unchanged")
        return
    with open(CATALOG, "w") as file:
        json.dump(document, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(f"wrote {CATALOG}")


if __name__ == "__main__":
    main()
