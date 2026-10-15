#!/usr/bin/env python3
"""Conservatively cap shared context and output limits for runtime routes.

Route providers do not introduce model identities. Their limits only reduce
an already discovered, source-backed model's shared safety bounds.
"""

import json
from pathlib import Path

from model_sources import canonical_model_id, discover_trusted_models, preferred_source


ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "models.json"
MODELS_DEV = ROOT / ".cache" / "models.dev.json"
POLICY = ROOT / "curation" / "sources.json"
ROUTE_EVIDENCE = ROOT / ".cache" / "route-limit-caps.json"


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
    evidence = {}

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
            preferred = preferred_source(trusted[canonical_id], "limits")
            official_context = positive_limit(preferred.model, "context")
            route_context = positive_limit(route_model, "context")
            route_output = positive_limit(route_model, "output")
            model_evidence = evidence.setdefault(canonical_id, {"routes": []})
            model_evidence["routes"].append({
                "upstream": "models.dev",
                "provider": provider_id,
                "source_id": raw_id,
                "route_id": route_id,
                "context_window_tokens": route_context,
                "max_output_tokens": route_output,
            })
            if official_context is not None and route_context is not None:
                safe_context = min(official_context, route_context)
                current_context = definition.get("context_window_tokens")
                if current_context is None or current_context > safe_context:
                    definition["context_window_tokens"] = safe_context
                    changed.add(canonical_id)
                    if route_context < official_context:
                        model_evidence["context_window_tokens"] = {
                            "value": safe_context,
                            "priority": 70,
                            "resolution": "lower configured route limit",
                            "official_value": official_context,
                            "route_value": route_context,
                        }
                current_input = definition.get("max_input_tokens")
                effective_context = definition["context_window_tokens"]
                if current_input is not None and current_input > effective_context:
                    definition["max_input_tokens"] = effective_context
                    changed.add(canonical_id)
                    if route_context < official_context:
                        model_evidence["max_input_tokens"] = {
                            "value": effective_context,
                            "priority": 70,
                            "resolution": "capped by configured route context limit",
                            "official_context_value": official_context,
                            "route_context_value": route_context,
                        }

            official_output = positive_limit(preferred.model, "output")
            if official_output is not None and route_output is not None:
                safe_output = min(official_output, route_output)
                current_output = definition.get("max_output_tokens")
                if current_output is None or current_output > safe_output:
                    definition["max_output_tokens"] = safe_output
                    changed.add(canonical_id)
                    if route_output < official_output:
                        model_evidence["max_output_tokens"] = {
                            "value": safe_output,
                            "priority": 70,
                            "resolution": "lower configured route limit",
                            "official_value": official_output,
                            "route_value": route_output,
                        }

    ROUTE_EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    ROUTE_EVIDENCE.write_text(
        json.dumps({"models": evidence}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

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
