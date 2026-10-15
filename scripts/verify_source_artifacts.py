#!/usr/bin/env python3
"""Check that fetched source observations survive normalization unchanged."""

import hashlib
import json
from pathlib import Path

from model_sources import (
    canonical_model_id,
    discover_exact_models,
    discover_trusted_models,
)


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def read_json(path, default=None):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def expected_hf_ids(snapshot, selection):
    allowed = {
        spec["id"]: tuple(prefix.lower() for prefix in spec.get("prefixes", [""]))
        for spec in selection["huggingface_organizations"]
    }
    result = {}
    for organization, rows in snapshot.get("organizations", {}).items():
        prefixes = allowed.get(organization)
        if prefixes is None:
            continue
        for row in rows:
            repo_id = row["id"]
            name = repo_id.split("/", 1)[-1].lower()
            if any(name.startswith(prefix) for prefix in prefixes):
                result[repo_id] = row
    return result


def verify_hash(source_id, snapshot_path, status, document):
    source_status = status.get("sources", {}).get(source_id, {})
    expected_hash = source_status.get("sha256")
    if not snapshot_path.exists():
        require(
            source_status.get("status", document.get("source", {}).get("status"))
            in {None, "unavailable", "not_fetched"},
                f"{source_id}: source snapshot is missing but status says it is available")
        return
    actual_hash = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    if expected_hash is not None and not source_status.get("cached_from_published_snapshot"):
        require(actual_hash == expected_hash, f"{source_id}: cached snapshot hash does not match source status")
    expected_document_hash = (
        expected_hash
        if source_status.get("cached_from_published_snapshot") and expected_hash
        else actual_hash
    )
    require(document.get("source", {}).get("sha256") == expected_document_hash,
            f"{source_id}: published sidecar does not identify its source snapshot hash")


def main():
    selection = read_json(ROOT / "curation" / "sources.json")
    status = read_json(ROOT / ".cache" / "source-status.json", {"sources": {}})
    catalog = read_json(ROOT / "models.json")["models"]
    resolution = read_json(ROOT / ".cache" / "modelsdev-resolution.json")

    # Every selected models.dev observation is kept, with all unknown fields in raw.
    models_dev = read_json(ROOT / ".cache" / "models.dev.json")
    trusted = discover_trusted_models(models_dev)
    expected_models_dev = {
        (model_id, observation.provider, observation.source_id): observation.model
        for model_id, observations in trusted.items()
        for observation in observations
    }
    models_dev_doc = read_json(DATA / "observations" / "models.dev.json")
    actual_models_dev = {
        (
            row["canonical_model_id"],
            row["source"]["provider"],
            row["source"]["source_id"],
        ): row["raw"]
        for row in models_dev_doc["records"]
    }
    require(len(models_dev_doc["records"]) == len(expected_models_dev)
            and actual_models_dev == expected_models_dev,
            "models.dev: selected source records or raw fields were lost/changed")
    exact_observations = discover_exact_models(models_dev)
    trusted_ids = set(trusted)
    expected_legacy = {
        (model_id, observation.provider, observation.source_id): observation.model
        for model_id in sorted(set(catalog) - trusted_ids)
        for observation in (
            exact_observations.get(model_id)
            or exact_observations.get(model_id.lower())
            or []
        )
    }
    legacy_doc = read_json(DATA / "observations" / "models.dev-exact-id-fallback.json")
    actual_legacy = {
        (row["catalog_model_id"], row["source"]["provider"], row["source"]["source_id"]): row["raw"]
        for row in legacy_doc["records"]
    }
    require(len(legacy_doc["records"]) == len(expected_legacy) and actual_legacy == expected_legacy,
            "models.dev exact-ID fallback: candidate records or raw fields were lost/changed")

    route_cap_ids = selection["route_limit_caps"]
    expected_caps = {}
    for provider_id in route_cap_ids:
        for raw_id, row in ((models_dev.get(provider_id) or {}).get("models") or {}).items():
            route_id = row.get("id") or raw_id
            model_id = canonical_model_id(route_id)
            if model_id in catalog:
                expected_caps[(model_id, provider_id, raw_id)] = row
    caps_doc = read_json(DATA / "routes" / "modelsdev-caps.json")
    actual_caps = {
        (row["canonical_model_id"], row["provider"], row["source_id"]): row["raw"]
        for row in caps_doc["records"]
    }
    require(len(caps_doc["records"]) == len(expected_caps) and actual_caps == expected_caps,
            "models.dev route caps: configured route observations or raw fields were lost/changed")

    # OpenRouter preserves every exact gateway route, including unknown fields.
    openrouter_snapshot_path = ROOT / ".cache" / "sources" / "openrouter.json"
    openrouter_snapshot = read_json(openrouter_snapshot_path, {"data": []})
    openrouter_doc = read_json(DATA / "routes" / "openrouter.json")
    expected_openrouter = {row["id"]: row for row in openrouter_snapshot["data"]}
    actual_openrouter = {row["route_id"]: row["raw"] for row in openrouter_doc["records"]}
    require(len(openrouter_doc["records"]) == len(expected_openrouter)
            and actual_openrouter == expected_openrouter,
            "OpenRouter: route records or raw fields were lost/changed")
    for row in openrouter_doc["records"]:
        params = row["raw"].get("supported_parameters")
        expected_support = True if isinstance(params, list) and "verbosity" in params else None
        require(row["fields"].get("supports_verbosity") == expected_support,
                f"OpenRouter {row['route_id']}: verbosity signal was parsed incorrectly")

    # LiteLLM keys and raw objects are kept even when a row is not understood.
    litellm_snapshot_path = ROOT / ".cache" / "sources" / "litellm.json"
    litellm_snapshot = read_json(litellm_snapshot_path, {})
    litellm_doc = read_json(DATA / "routes" / "litellm.json")
    expected_litellm = litellm_snapshot
    actual_litellm = {row["route_id"]: row["raw"] for row in litellm_doc["records"]}
    require(len(litellm_doc["records"]) == len(expected_litellm)
            and actual_litellm == expected_litellm,
            "LiteLLM: route records or raw fields were lost/changed")

    # HF organization/prefix filtering is intentional; accepted repository rows
    # must remain byte-equivalent at the parsed-object level.
    hf_snapshot_path = ROOT / ".cache" / "sources" / "huggingface.json"
    hf_snapshot = read_json(hf_snapshot_path, {"organizations": {}, "record_count": 0})
    hf_observations = read_json(DATA / "observations" / "huggingface.json")
    expected_hf_observations = {
        (organization, row["id"]): row
        for organization, rows in hf_snapshot.get("organizations", {}).items()
        for row in rows
    }
    actual_hf_observations = {
        (row["organization"], row["repository_id"]): row["raw"]
        for row in hf_observations["records"]
    }
    require(
        len(hf_observations["records"]) == len(expected_hf_observations)
        and actual_hf_observations == expected_hf_observations,
        "Hugging Face: official organization records or raw fields were lost/changed",
    )
    hf_expected = expected_hf_ids(hf_snapshot, selection)
    hf_doc = read_json(DATA / "artifacts" / "huggingface.json")
    hf_actual = {row["repository_id"]: row for row in hf_doc["records"]}
    require(len(hf_doc["records"]) == len(hf_expected) and set(hf_actual) == set(hf_expected),
            "Hugging Face: allowlisted artifact records were lost or added")
    for repository_id, raw in hf_expected.items():
        actual = hf_actual[repository_id]
        expected_facts = {
            "pipeline_tag": raw.get("pipeline_tag"),
            "library_name": raw.get("library_name"),
            "tags": raw.get("tags"),
            "license": (raw.get("cardData") or {}).get("license")
            if isinstance(raw.get("cardData"), dict) else None,
            "last_modified": raw.get("lastModified"),
            "downloads": raw.get("downloads"),
            "likes": raw.get("likes"),
        }
        require(actual["organization"] == repository_id.split("/", 1)[0]
                and actual["facts"] == expected_facts,
                f"Hugging Face {repository_id}: artifact facts were parsed incorrectly")

    # Every published model field must carry an explanation, even when its
    # provenance is historical catalog curation rather than a live source.
    provenance = read_json(DATA / "model-provenance.json")["models"]
    require(set(provenance) == set(catalog),
            "model provenance must cover exactly the published model IDs")
    for model_id, definition in catalog.items():
        require(set(provenance[model_id]) == set(definition),
                f"{model_id}: model provenance does not cover every published field")
    route_caps = read_json(ROOT / ".cache" / "route-limit-caps.json", {"models": {}})
    for model_id, fields in route_caps.get("models", {}).items():
        for field in fields:
            if field == "routes":
                continue
            if field in catalog.get(model_id, {}):
                require(
                    provenance[model_id][field].get("kind")
                    in {"configured_route_limit_cap", "verified_curated_patch"},
                    f"{model_id}.{field}: route-cap provenance is missing",
                )

    conflicts = read_json(DATA / "source-conflicts.json")["conflicts"]
    require(conflicts == sorted(
        resolution.get("conflicts", []),
        key=lambda item: (item.get("model_id", ""), item.get("field", "")),
    ), "published source conflicts differ from the merge resolution record")

    verify_hash("models.dev", ROOT / ".cache" / "models.dev.json", status, models_dev_doc)
    verify_hash("openrouter", openrouter_snapshot_path, status, openrouter_doc)
    verify_hash("litellm", litellm_snapshot_path, status, litellm_doc)
    verify_hash("huggingface", hf_snapshot_path, status, hf_doc)

    print(
        "source integrity verified: "
        f"{len(actual_models_dev)} models.dev observations, "
        f"{len(actual_openrouter)} OpenRouter routes, "
        f"{len(actual_litellm)} LiteLLM records, "
        f"{len(hf_actual)} HF artifacts, "
        f"{len(conflicts)} explicit conflicts, "
        f"{sum(len(fields) for fields in provenance.values())} provenance fields"
    )


if __name__ == "__main__":
    main()
