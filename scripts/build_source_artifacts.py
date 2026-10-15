#!/usr/bin/env python3
"""Publish lossless route/artifact observations and model-field provenance.

Route and weight-repository facts are deliberately kept out of canonical
models.json. Route records retain their complete upstream object in ``raw``;
Hugging Face artifacts link to a separate full observation inventory so its
large raw objects are stored only once.
"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

from model_sources import (
    canonical_model_id,
    discover_exact_models,
    discover_trusted_models,
    source_ref,
)


ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "curation" / "upstreams.json"
SELECTION = ROOT / "curation" / "sources.json"
CATALOG = ROOT / "models.json"
STATUS = ROOT / ".cache" / "source-status.json"
RESOLUTION = ROOT / ".cache" / "modelsdev-resolution.json"
ROUTE_CAPS = ROOT / ".cache" / "route-limit-caps.json"
PATCH_DIR = ROOT / "curation" / "patches"
SOURCE_CACHE = ROOT / ".cache" / "sources"
OUTPUT = ROOT / "data"


def read_json(path, default=None):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == encoded:
        return
    path.write_text(encoded, encoding="utf-8")


def source_snapshot(source_id):
    safe_id = source_id.replace("/", "_").replace(".", "_")
    return SOURCE_CACHE / f"{safe_id}.json"


def source_meta(source_id, statuses):
    status = statuses.get(source_id, {})
    if source_id == "models.dev":
        local_snapshot = ROOT / ".cache" / "models.dev.json"
    else:
        local_snapshot = source_snapshot(source_id)
    local_hash = None
    if local_snapshot.is_file():
        local_hash = hashlib.sha256(local_snapshot.read_bytes()).hexdigest()
    result = {
        "id": source_id,
        "status": status.get("status", "cached" if local_hash else "not_fetched"),
        "sha256": status.get("sha256") or local_hash,
        "record_count": status.get("record_count"),
    }
    if source_id in {"huggingface", "openrouter", "litellm"}:
        result["retrieved_at"] = status.get("retrieved_at")
    return result


def exact_catalog_candidate(raw_id, catalog_ids):
    if not isinstance(raw_id, str):
        return None
    suffix = raw_id.rsplit("/", 1)[-1]
    if suffix in catalog_ids:
        return suffix
    normalized = canonical_model_id(raw_id)
    return normalized if normalized in catalog_ids else None


def openrouter_routes(value, catalog_ids, source):
    records = []
    raw_rows = value.get("data", [])
    if not isinstance(raw_rows, list) or any(not isinstance(row, dict) for row in raw_rows):
        raise ValueError("OpenRouter response contains a non-object route record")
    field_priorities = source.get("field_priorities", {})
    for row in sorted(raw_rows, key=lambda item: str(item.get("id", ""))):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("OpenRouter record has no string id")
        pricing = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
        top_provider = row.get("top_provider") if isinstance(row.get("top_provider"), dict) else {}
        supported_parameters = row.get("supported_parameters")
        records.append({
            "route_id": row["id"],
            "scope": "openrouter_api_route",
            "catalog_model_id_candidate": exact_catalog_candidate(row["id"], catalog_ids),
            "priority": field_priorities,
            "fields": {
                "context_length_tokens": row.get("context_length"),
                "max_input_tokens": top_provider.get("max_prompt_tokens"),
                "max_output_tokens": top_provider.get("max_completion_tokens"),
                "input_usd_per_million_tokens": _per_million(pricing.get("prompt")),
                "output_usd_per_million_tokens": _per_million(pricing.get("completion")),
                "supports_verbosity": (
                    True if isinstance(supported_parameters, list) and "verbosity" in supported_parameters else None
                ),
                "supported_parameters": supported_parameters,
            },
            "raw": row,
        })
    return {
        "schema_version": 1,
        "source": source_meta(source["id"], STATUS_CACHE),
        "scope": "openrouter_api_route",
        "records": records,
    }


def _per_million(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if number < 0:
        return None
    formatted = format(number * Decimal(1_000_000), "f")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted or "0"


def litellm_routes(value, catalog_ids, source):
    records = []
    field_priorities = source.get("field_priorities", {})
    for route_id, raw in sorted(value.items()):
        if not isinstance(raw, dict):
            records.append({
                "route_id": route_id,
                "provider": None,
                "scope": "provider_route_reference",
                "catalog_model_id_candidate": exact_catalog_candidate(route_id, catalog_ids),
                "priority": field_priorities,
                "fields": {},
                "raw": raw,
            })
            continue
        records.append({
            "route_id": route_id,
            "provider": raw.get("litellm_provider"),
            "scope": "provider_route_reference",
            "catalog_model_id_candidate": exact_catalog_candidate(route_id, catalog_ids),
            "priority": field_priorities,
            "fields": {
                "max_input_tokens": raw.get("max_input_tokens"),
                "max_output_tokens": raw.get("max_output_tokens"),
                "input_usd_per_million_tokens": _per_million(raw.get("input_cost_per_token")),
                "output_usd_per_million_tokens": _per_million(raw.get("output_cost_per_token")),
                "cache_read_usd_per_million_tokens": _per_million(raw.get("cache_read_input_token_cost")),
                "cache_write_usd_per_million_tokens": _per_million(raw.get("cache_creation_input_token_cost")),
                "source_url": raw.get("source"),
            },
            "raw": raw,
        })
    return {
        "schema_version": 1,
        "source": source_meta(source["id"], STATUS_CACHE),
        "scope": "provider_route_reference",
        "records": records,
    }


def huggingface_artifacts(value, catalog_ids, source):
    records = []
    for organization, raw_rows in sorted(value.get("organizations", {}).items()):
        if not isinstance(raw_rows, list) or any(not isinstance(raw, dict) for raw in raw_rows):
            raise ValueError(f"Hugging Face {organization}: malformed repository list")
        for raw in sorted(raw_rows, key=lambda item: str(item.get("id", ""))):
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
                raise ValueError(f"Hugging Face {organization}: record has no string id")
            if raw["id"].split("/", 1)[0] != organization:
                raise ValueError(f"Hugging Face artifact is outside allowlisted organization: {raw['id']}")
            if not any(
                raw["id"].split("/", 1)[-1].lower().startswith(prefix.lower())
                for spec in SELECTION_CACHE["huggingface_organizations"]
                if spec["id"] == organization
                for prefix in spec.get("prefixes", [""])
            ):
                continue
            records.append({
                "repository_id": raw["id"],
                "organization": organization,
                "scope": "weight_artifact_candidate",
                "catalog_model_id_candidate": exact_catalog_candidate(raw["id"], catalog_ids),
                "priority": source.get("field_priorities", {}),
                "facts": {
                    "pipeline_tag": raw.get("pipeline_tag"),
                    "library_name": raw.get("library_name"),
                    "tags": raw.get("tags"),
                    "license": (raw.get("cardData") or {}).get("license")
                    if isinstance(raw.get("cardData"), dict) else None,
                    "last_modified": raw.get("lastModified"),
                    "downloads": raw.get("downloads"),
                    "likes": raw.get("likes"),
                },
            })
    return {
        "schema_version": 1,
        "source": source_meta(source["id"], STATUS_CACHE),
        "scope": "weight_artifact_candidate",
        "records": records,
    }


def patch_field_sources():
    result = {}
    for path in sorted(PATCH_DIR.glob("*.json")):
        patch = read_json(path, {})
        notes = patch.get("notes")
        for model_id, fields in (patch.get("models") or {}).items():
            for field in fields:
                result.setdefault(model_id, {})[field] = {
                    "kind": "verified_curated_patch",
                    "path": str(path.relative_to(ROOT)),
                    "priority": 100,
                    "has_source_notes": bool(notes),
                }
    return result


def build_model_provenance(catalog, resolution, route_caps):
    patches = patch_field_sources()
    resolved_models = resolution.get("models", {})
    route_models = route_caps.get("models", {})
    result = {"schema_version": 1, "models": {}}
    for model_id, definition in sorted(catalog.get("models", {}).items()):
        base_fields = resolved_models.get(model_id, {}).get("fields", {})
        fields = {}
        for field, value in sorted(definition.items()):
            patch = patches.get(model_id, {}).get(field)
            if patch:
                fields[field] = patch
                continue
            route_cap = route_models.get(model_id, {}).get(field)
            if route_cap:
                fields[field] = {
                    "kind": "configured_route_limit_cap",
                    "upstream": "models.dev",
                    **deepcopy(route_cap),
                    "routes": deepcopy(route_models[model_id].get("routes", [])),
                }
                continue
            source_field = base_fields.get(field)
            if source_field and source_field.get("value", value) == value:
                fields[field] = {
                    "kind": "upstream_field_observation",
                    "scope": resolved_models.get(model_id, {}).get("scope"),
                    **deepcopy(source_field),
                }
                continue
            if (
                field == "thinking_modes"
                and resolved_models.get(model_id, {}).get("scope") == "publisher_api_model"
            ):
                fields[field] = {
                    "kind": "derived_from_models.dev_reasoning_options",
                    "upstream": "models.dev",
                    "priority": 70,
                }
                continue
            if (
                field == "speed_modes"
                and resolved_models.get(model_id, {}).get("scope") == "publisher_api_model"
            ):
                fields[field] = {
                    "kind": "derived_from_models.dev_experimental_modes",
                    "upstream": "models.dev",
                    "priority": 70,
                }
                continue
            fields[field] = {"kind": "existing_catalog_or_pipeline_value"}
        result["models"][model_id] = fields
    return result


def main():
    global STATUS_CACHE, SELECTION_CACHE
    registry = read_json(REGISTRY)
    SELECTION_CACHE = read_json(SELECTION)
    status_document = read_json(STATUS, {"sources": {}})
    STATUS_CACHE = status_document.get("sources", {})
    catalog = read_json(CATALOG)
    catalog_ids = set(catalog["models"])
    resolution = read_json(RESOLUTION, {"models": {}, "conflicts": []})
    route_caps = read_json(ROUTE_CAPS, {"models": {}})
    models_dev_snapshot = read_json(ROOT / ".cache" / "models.dev.json", {})
    models_dev_observations = discover_trusted_models(models_dev_snapshot)
    exact_observations = discover_exact_models(models_dev_snapshot)
    route_cap_provider_ids = SELECTION_CACHE["route_limit_caps"]
    route_cap_records = []
    for provider_id in route_cap_provider_ids:
        provider_models = (models_dev_snapshot.get(provider_id) or {}).get("models") or {}
        for raw_id, raw in sorted(provider_models.items()):
            route_id = raw.get("id") or raw_id
            model_id = canonical_model_id(route_id)
            if model_id not in catalog_ids:
                continue
            route_cap_records.append({
                "canonical_model_id": model_id,
                "route_id": route_id,
                "provider": provider_id,
                "source_id": raw_id,
                "scope": "models.dev_route_limit_cap",
                "priority": 70,
                "fields": {
                    "context_window_tokens": (raw.get("limit") or {}).get("context"),
                    "max_output_tokens": (raw.get("limit") or {}).get("output"),
                },
                "raw": raw,
            })

    by_id = {source["id"]: source for source in registry["sources"]}
    openrouter_source = by_id["openrouter"]
    litellm_source = by_id["litellm"]
    huggingface_source = by_id["huggingface"]

    openrouter_snapshot = read_json(source_snapshot("openrouter"), {"data": []})
    litellm_snapshot = read_json(source_snapshot("litellm"), {})
    huggingface_snapshot = read_json(source_snapshot("huggingface"), {"organizations": {}, "record_count": 0})

    openrouter_document = openrouter_routes(openrouter_snapshot, catalog_ids, openrouter_source)
    litellm_document = litellm_routes(litellm_snapshot, catalog_ids, litellm_source)
    huggingface_document = huggingface_artifacts(huggingface_snapshot, catalog_ids, huggingface_source)

    write_json(OUTPUT / "routes" / "openrouter.json", openrouter_document)
    write_json(OUTPUT / "routes" / "litellm.json", litellm_document)
    write_json(OUTPUT / "artifacts" / "huggingface.json", huggingface_document)
    write_json(OUTPUT / "observations" / "huggingface.json", {
        "schema_version": 1,
        "source": source_meta("huggingface", STATUS_CACHE),
        "scope": "official_organization_repository_observation",
        "records": [
            {
                "repository_id": raw["id"],
                "organization": organization,
                "raw": raw,
            }
            for organization, raw_rows in sorted(huggingface_snapshot.get("organizations", {}).items())
            for raw in sorted(raw_rows, key=lambda item: item.get("id", ""))
        ],
    })
    write_json(OUTPUT / "observations" / "models.dev.json", {
        "schema_version": 1,
        "source": source_meta("models.dev", STATUS_CACHE),
        "scope": "allowlisted_publisher_api_model_observation",
        "records": [
            {
                "canonical_model_id": model_id,
                "scope": "publisher_api_model",
                "source": source_ref(observation, "identity"),
                "field_priorities": observation.field_priorities,
                "raw": observation.model,
            }
            for model_id, observations in sorted(models_dev_observations.items())
            for observation in observations
        ],
    })
    trusted_ids = set(models_dev_observations)
    legacy_observation_records = []
    for model_id in sorted(catalog_ids - trusted_ids):
        observations = exact_observations.get(model_id) or exact_observations.get(model_id.lower()) or []
        for observation in observations:
            legacy_observation_records.append({
                "catalog_model_id": model_id,
                "scope": "legacy_exact_id_fallback_candidate",
                "source": source_ref(observation, "identity"),
                "field_priorities": observation.field_priorities,
                "raw": observation.model,
            })
    write_json(OUTPUT / "observations" / "models.dev-exact-id-fallback.json", {
        "schema_version": 1,
        "source": source_meta("models.dev", STATUS_CACHE),
        "scope": "exact_id_low_priority_descriptive_fallback_candidates",
        "records": legacy_observation_records,
    })
    write_json(OUTPUT / "routes" / "modelsdev-caps.json", {
        "schema_version": 1,
        "source": source_meta("models.dev", STATUS_CACHE),
        "scope": "configured_route_limit_cap",
        "records": route_cap_records,
    })
    write_json(OUTPUT / "model-provenance.json", build_model_provenance(catalog, resolution, route_caps))
    write_json(OUTPUT / "source-conflicts.json", {
        "schema_version": 1,
        "resolution_policy": "highest per-field-group source priority; source policy order breaks ties",
        "conflicts": sorted(
            resolution.get("conflicts", []),
            key=lambda item: (item.get("model_id", ""), item.get("field", "")),
        ),
    })

    inventory = []
    for source in registry["sources"]:
        meta = source_meta(source["id"], STATUS_CACHE)
        inventory.append({
            **source,
            "snapshot_status": meta["status"],
            "snapshot_sha256": meta["sha256"],
            "snapshot_record_count": meta["record_count"],
            **({"last_successful_retrieval": meta["retrieved_at"]}
               if meta.get("retrieved_at") else {}),
        })
    write_json(OUTPUT / "source-inventory.json", {
        "schema_version": 1,
        "sources": inventory,
        "route_record_counts": {
            "models.dev_allowlisted_observations": sum(
                len(observations) for observations in models_dev_observations.values()
            ),
            "models.dev_exact_id_fallback_candidates": len(legacy_observation_records),
            "models.dev_route_limit_caps": len(route_cap_records),
            "openrouter": len(openrouter_document["records"]),
            "litellm": len(litellm_document["records"]),
        },
        "artifact_record_counts": {"huggingface": len(huggingface_document["records"])},
        "model_provenance_count": len(catalog_ids),
    })
    print(
        "wrote source sidecars: "
        f"{sum(len(rows) for rows in models_dev_observations.values())} allowlisted models.dev observations, "
        f"{len(openrouter_document['records'])} OpenRouter routes, "
        f"{len(litellm_document['records'])} LiteLLM route references, "
        f"{len(huggingface_document['records'])} Hugging Face artifacts, "
        f"{len(resolution.get('conflicts', []))} models.dev field conflicts"
    )


if __name__ == "__main__":
    STATUS_CACHE = {}
    SELECTION_CACHE = {}
    main()
