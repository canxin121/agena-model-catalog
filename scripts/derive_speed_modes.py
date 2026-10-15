#!/usr/bin/env python3
"""Materialise speed modes from the trusted models.dev mode records.

The catalog is the only source of speed modes: the runtime sends exactly what a
mode declares and never infers a tier from a model id. This stage fills
`speed_modes` for entries that have none yet and guarantees an explicit
`standard` ("Default") entry so the selector can always express "send no tier".

Rules (conservative - never fabricate):

* Only the trusted first-party record (curation/sources.json) is read.
* Only these `experimental.modes[*].provider.body` shapes are materialised:
  - `{"service_tier": ...}` -> request override body patch;
  - `{"speed": "fast"}` from Anthropic -> body patch plus the documented
    `anthropic-beta: fast-mode-2026-02-01` header (same convention as the
    hand-curated entries);
  - `{"reasoning": {"mode": ...}}` -> an `openai_responses` adapter override,
    because `reasoning.mode` is Responses-only.
* Any other shape (for example Bedrock's `additionalModelRequestFields`) is
  skipped and listed for curation.
* Entries that already declare `speed_modes` are never rewritten; they only
  receive the `standard` entry and default pointer when missing.

Run after derive_thinking_modes.py and before apply_patches.py, and once more after the patches with --ensure-existing-only:

    python3 scripts/derive_speed_modes.py [--dry-run]
"""
import json
import os
import sys

from model_sources import discover_trusted_models, preferred_source

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "models.json")
SNAPSHOT = os.path.join(ROOT, ".cache", "models.dev.json")

STANDARD_KEY = "standard"
STANDARD_DISPLAY_NAME = "Default"
OPENAI_RESPONSES_ADAPTER = "openai_responses"
ANTHROPIC_FAST_HEADERS = {"anthropic-beta": "fast-mode-2026-02-01"}
DISPLAY_NAMES = {
    "fast": "Fast",
    "flex": "Flex",
    "priority": "Priority",
    "ultrafast": "Ultrafast",
    "pro": "Pro",
}


def display_name(mode_name):
    return DISPLAY_NAMES.get(mode_name, mode_name.replace("_", " ").title())


def published_modes(model):
    modes = (model.get("experimental") or {}).get("modes")
    return modes if isinstance(modes, dict) else {}


def mode_definition(provider_id, mode_name, spec):
    """Return the catalog mode for one published mode, or a skip reason."""
    body = ((spec or {}).get("provider") or {}).get("body")
    if not isinstance(body, dict) or not body:
        return None, "no provider body"
    keys = set(body)
    if keys == {"service_tier"}:
        return {
            "display_name": display_name(mode_name),
            "request_override": {"body_patch": body},
        }, None
    if keys == {"speed"} and provider_id.startswith("anthropic"):
        return {
            "display_name": display_name(mode_name),
            "request_override": {
                "headers": dict(ANTHROPIC_FAST_HEADERS),
                "body_patch": body,
            },
        }, None
    if keys == {"reasoning"}:
        return {
            "display_name": display_name(mode_name),
            "adapter_overrides": {OPENAI_RESPONSES_ADAPTER: {"body_patch": body}},
        }, None
    return None, f"unsupported body keys {sorted(keys)}"


def main():
    dry_run = "--dry-run" in sys.argv[1:]
    ensure_existing_only = "--ensure-existing-only" in sys.argv[1:]
    with open(CATALOG) as file:
        document = json.load(file)
    with open(SNAPSHOT) as file:
        models_dev = json.load(file)
    trusted = discover_trusted_models(models_dev)

    derived = []
    standard_added = []
    pointer_set = []
    skipped = {}

    def skip(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    for model_id, definition in document["models"].items():
        if not ensure_existing_only and not definition.get("speed_modes"):
            observations = trusted.get(model_id)
            if not observations:
                skip("no trusted record")
            else:
                source = preferred_source(observations, "modes")
                modes = {}
                for mode_name, spec in sorted(published_modes(source.model).items()):
                    if mode_name == STANDARD_KEY:
                        skip("vendor mode named standard")
                        continue
                    mode, reason = mode_definition(
                        source.provider, mode_name, spec
                    )
                    if mode is None:
                        skip(reason)
                        continue
                    modes[mode_name] = mode
                if modes:
                    definition["speed_modes"] = modes
                    derived.append(model_id)

        speed_modes = definition.get("speed_modes")
        if not speed_modes:
            continue
        if STANDARD_KEY not in speed_modes:
            speed_modes[STANDARD_KEY] = {"display_name": STANDARD_DISPLAY_NAME}
            standard_added.append(model_id)
        if "default" not in speed_modes:
            speed_modes["default"] = STANDARD_KEY
            pointer_set.append(model_id)

    print(f"derived speed_modes: {len(derived)}")
    for model_id in sorted(derived):
        names = ",".join(
            key
            for key in document["models"][model_id]["speed_modes"]
            if key != "default"
        )
        print(f"  {model_id}: {names}")
    print(f"standard entry added: {len(standard_added)}")
    print(f"default pointer set to standard: {len(pointer_set)}")
    if skipped:
        print("skipped:")
        for reason, count in sorted(skipped.items()):
            print(f"  {reason}: {count}")

    if dry_run:
        print("dry run: models.json unchanged")
        return
    with open(CATALOG, "w") as file:
        json.dump(document, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(f"wrote {CATALOG}")


if __name__ == "__main__":
    main()
