#!/usr/bin/env python3
"""Conservatively cap shared context and output limits for runtime routes.

Route providers do not introduce model identities. Their limits only reduce
an already discovered, source-backed model's shared safety bounds.
"""

import json
from pathlib import Path

from model_sources import canonical_model_id, discover_trusted_models


ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "models.json"
MODELS_DEV = ROOT / ".cache" / "models.dev.json"
POLICY = ROOT / "curation" / "sources.json"


def positive_limit(model, field):
    value = (model.get("limit") or {}).get(field)
    return value if type(value) is int and value > 0 else None


def main():
    with CATALOG.open() as file:
        catalog = json.load(file)
    with MODELS_DEV.open() as file:
        models_dev = json.load(file)
    with POLICY.open() as file:
        route_providers = json.load(file)["route_limit_caps"]
    trusted = discover_trusted_models(models_dev)
    models = catalog["models"]
    changed = set()

    for provider_id in route_providers:
        provider_models = (models_dev.get(provider_id) or {}).get("models") or {}
        if not provider_models:
            raise ValueError(f"configured route provider {provider_id!r} is missing from the snapshot")
        for raw_id, route_model in provider_models.items():
            route_id = route_model.get("id") or raw_id
            canonical_id = canonical_model_id(route_id)
            if canonical_id not in models or canonical_id not in trusted:
                continue
            definition = models[canonical_id]
            official_context = positive_limit(trusted[canonical_id].model, "context")
            route_context = positive_limit(route_model, "context")
            if official_context is not None and route_context is not None:
                safe_context = min(official_context, route_context)
                current_context = definition.get("context_window_tokens")
                if current_context is None or current_context > safe_context:
                    definition["context_window_tokens"] = safe_context
                    changed.add(canonical_id)
                current_input = definition.get("max_input_tokens")
                effective_context = definition["context_window_tokens"]
                if current_input is not None and current_input > effective_context:
                    definition["max_input_tokens"] = effective_context
                    changed.add(canonical_id)

            official_output = positive_limit(trusted[canonical_id].model, "output")
            route_output = positive_limit(route_model, "output")
            if official_output is not None and route_output is not None:
                safe_output = min(official_output, route_output)
                current_output = definition.get("max_output_tokens")
                if current_output is None or current_output > safe_output:
                    definition["max_output_tokens"] = safe_output
                    changed.add(canonical_id)

    if changed:
        with CATALOG.open("w") as file:
            json.dump(catalog, file, ensure_ascii=False, indent=2)
            file.write("\n")
    print(f"route limit caps applied to {len(changed)} models")
    for model_id in sorted(changed):
        definition = models[model_id]
        print(f"  {model_id}: context={definition.get('context_window_tokens')}, output={definition.get('max_output_tokens')}")


if __name__ == "__main__":
    main()
