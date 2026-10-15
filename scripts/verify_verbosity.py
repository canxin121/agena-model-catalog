#!/usr/bin/env python3
"""Verify scoped verbosity retention and the automatic OpenAI GPT profile."""
import json
import os
import sys

from model_sources import discover_trusted_models
from seed_modelsdev import resolve_model_observations, verbosity_metadata


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "models.json")
SNAPSHOT = os.path.join(ROOT, ".cache", "models.dev.json")


def main():
    with open(CATALOG, encoding="utf-8") as file:
        catalog = json.load(file)
    with open(SNAPSHOT, encoding="utf-8") as file:
        models_dev = json.load(file)

    models = catalog.get("models")
    if not isinstance(models, dict):
        print("models.json: 'models' must be an object", file=sys.stderr)
        return 1

    trusted = discover_trusted_models(models_dev)
    errors = []
    models_with_profiles = 0
    total_profiles = 0
    for model_id, definition in models.items():
        observations = trusted.get(model_id)
        if observations:
            expected_sources = sorted({source.provider for source in observations})
            if definition.get("provider_sources") != expected_sources:
                errors.append(
                    f"{model_id}: provider_sources={definition.get('provider_sources')!r}, "
                    f"expected {expected_sources!r}"
                )
            resolved, _provenance, _conflicts = resolve_model_observations(observations)
            expected = resolved.get("verbosity_by_provider")
        else:
            expected = None
            if "provider_sources" in definition:
                errors.append(f"{model_id}: stale provider_sources without a trusted current observation")

        actual = definition.get("verbosity_by_provider")
        if actual != expected:
            errors.append(
                f"{model_id}: verbosity_by_provider={actual!r}, expected {expected!r}"
            )
        if actual:
            models_with_profiles += 1
            total_profiles += len(actual)

        for legacy in ("supports_verbosity", "default_verbosity"):
            if legacy in definition:
                errors.append(f"{model_id}: legacy global {legacy} must not be published")

    # These policy probes protect the refresh behavior for future models:
    # GPT-6 text models get the OpenAI profile, while other providers and
    # non-text GPT products remain unannotated.
    future_text_gpt = verbosity_metadata(
        {"id": "gpt-99.1", "modalities": {"output": ["text"]}},
        "openai",
    )
    if future_text_gpt.get("verbosity_by_provider", {}).get("openai", {}).get("levels") != [
        "low", "medium", "high"
    ]:
        errors.append("future OpenAI GPT text model did not receive the configured verbosity profile")
    for source, provider_id in (
        ({"id": "gpt-99.1", "modalities": {"output": ["text"]}}, "openrouter"),
        ({"id": "gpt-99-audio", "modalities": {"output": ["audio", "text"]}}, "openai"),
        ({"id": "gpt-99-image", "modalities": {"output": ["image"]}}, "openai"),
    ):
        if verbosity_metadata(source, provider_id):
            errors.append(f"non-matching source/model unexpectedly received verbosity: {provider_id}/{source['id']}")

    print(
        "verbosity profiles: "
        f"{models_with_profiles}/{len(models)} models, {total_profiles} provider profiles"
    )
    if errors:
        print(f"\nERRORS ({len(errors)}):", file=sys.stderr)
        for error in errors[:100]:
            print(f"  {error}", file=sys.stderr)
        return 1

    print("ALL PASS: provider-scoped verbosity and source lists match current evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
