#!/usr/bin/env python3
"""Discover new canonical models from trusted models.dev sources.

The source policy admits first-party providers and official Hugging Face
organizations. It does not require a new hand-written entry for each model.
Existing catalog entries are preserved; merge and curated patches update them.
"""
import json
import os
import re
import sys

from model_sources import canonical_model_id, discover_trusted_models, preferred_source, source_ref

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "models.json")
MODELS_DEV = os.path.join(ROOT, ".cache", "models.dev.json")
VERBOSITY_PROFILES = os.path.join(ROOT, "curation", "verbosity-profiles.json")
MAX_AUTO_ADDITIONS = 100

with open(VERBOSITY_PROFILES, encoding="utf-8") as _file:
    VERBOSITY_PROFILE_POLICY = json.load(_file)


def _validate_verbosity_profile_policy(policy):
    profiles = policy.get("profiles")
    if not isinstance(profiles, list):
        raise ValueError("curation/verbosity-profiles.json must contain a profiles list")
    seen = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError("verbosity profile entries must be objects")
        provider = profile.get("provider")
        profile_id = profile.get("id")
        minimum_major = profile.get("minimum_model_major")
        levels = profile.get("levels")
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("verbosity profiles require a provider ID")
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise ValueError("verbosity profiles require an ID")
        if (provider, profile_id) in seen:
            raise ValueError(f"duplicate verbosity profile {provider}/{profile_id}")
        seen.add((provider, profile_id))
        if type(minimum_major) is not int or minimum_major < 1:
            raise ValueError(f"{profile_id}: minimum_model_major must be a positive integer")
        if (
            not isinstance(levels, list)
            or not levels
            or any(not isinstance(value, str) or not value.strip() or value != value.strip()
                   for value in levels)
            or len(levels) != len(set(levels))
        ):
            raise ValueError(f"{profile_id}: levels must be unique, trimmed, non-empty strings")
        provider_default = profile.get("provider_default")
        if provider_default is not None and provider_default not in levels:
            raise ValueError(f"{profile_id}: provider_default must be one of its levels")
        exclusions = profile.get("exclude_id_patterns", [])
        if not isinstance(exclusions, list) or any(not isinstance(value, str) for value in exclusions):
            raise ValueError(f"{profile_id}: exclude_id_patterns must be a list of regex strings")
        for pattern in exclusions:
            re.compile(pattern)


_validate_verbosity_profile_policy(VERBOSITY_PROFILE_POLICY)

LIFECYCLES = {"active", "preview", "beta", "alpha", "experimental", "deprecated"}
INPUT_MODALITIES = {"text", "image", "document", "audio", "video", "file"}
VERBOSITY_SOURCE_FIELDS = {
    "supports_verbosity": "supports_verbosity",
    "default_verbosity": "default_verbosity",
    "verbosity_levels": "verbosity_levels",
    "supported_verbosity_levels": "verbosity_levels",
}


def _verbosity_key_paths(value, path=()):
    """Find verbosity-related source keys so schema changes cannot vanish silently."""
    if isinstance(value, dict):
        for key, child in value.items():
            next_path = path + (str(key),)
            if "verbosity" in str(key).casefold():
                yield next_path
            yield from _verbosity_key_paths(child, next_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _verbosity_key_paths(child, path + (str(index),))


def _provider_verbosity_profile(source, provider_id):
    """Return an explicitly scoped endpoint profile for this provider/model."""
    raw_id = (source.get("id") or "").strip().lower()
    source_id = canonical_model_id(raw_id) or raw_id
    output_modalities = (source.get("modalities") or {}).get("output") or []
    if not isinstance(output_modalities, list) or "text" not in output_modalities:
        return None
    for profile in VERBOSITY_PROFILE_POLICY.get("profiles", []):
        if profile.get("provider") != provider_id:
            continue
        match = re.match(r"^gpt-(\d+)(?:[.-]|$)", source_id)
        if not match or int(match.group(1)) < int(profile.get("minimum_model_major", 0)):
            continue
        if any(re.search(pattern, source_id) for pattern in profile.get("exclude_id_patterns", [])):
            continue
        return {
            "supported": True,
            "levels": list(profile["levels"]),
            "provider_default": profile.get("provider_default"),
        }
    return None


def verbosity_metadata(source, provider_id):
    """Resolve route-scoped verbosity evidence without deriving reasoning.

    Unknown verbosity-shaped upstream fields fail closed. An explicit false
    suppresses inherited endpoint support. Unsupported and unknown providers
    are omitted from the published catalog.
    """
    paths = list(_verbosity_key_paths(source))
    unknown = [
        ".".join(path)
        for path in paths
        if len(path) != 1 or path[0] not in VERBOSITY_SOURCE_FIELDS
    ]
    if unknown:
        raise ValueError(
            "unsupported upstream verbosity field(s): " + ", ".join(sorted(unknown))
        )

    explicit_support = source.get("supports_verbosity")
    if explicit_support is not None and type(explicit_support) is not bool:
        raise ValueError(
            f"upstream supports_verbosity must be a boolean or null, got {explicit_support!r}"
        )
    if explicit_support is False:
        return {"verbosity_by_provider": {provider_id: {"supported": False}}}

    result = _provider_verbosity_profile(source, provider_id)
    if result is None:
        if explicit_support is not True:
            return {}
        result = {"supported": True}

    for source_key, catalog_key in VERBOSITY_SOURCE_FIELDS.items():
        if source_key not in source or source[source_key] is None:
            continue
        value = source[source_key]
        if source_key == "supports_verbosity":
            if value:
                result["supported"] = True
        else:
            if source_key == "default_verbosity":
                if not isinstance(value, str) or not value.strip() or value != value.strip():
                    raise ValueError(
                        f"upstream {source_key} must be a trimmed, non-empty string "
                        f"or null, got {value!r}"
                    )
                result["provider_default"] = value
                result["supported"] = True
            else:
                if (
                    not isinstance(value, list)
                    or any(not isinstance(item, str) or not item.strip() or item != item.strip()
                           for item in value)
                    or len(value) != len(set(value))
                ):
                    raise ValueError(
                        f"upstream {source_key} must be a unique list of trimmed, "
                        f"non-empty strings or null, got {value!r}"
                    )
                result["levels"] = value
                result["supported"] = True

    if not result.get("supported"):
        return {"verbosity_by_provider": {provider_id: {"supported": False}}}
    result.pop("default_verbosity", None)
    result.pop("supported_verbosity_levels", None)
    if result.get("provider_default") is None:
        result.pop("provider_default", None)
    return {"verbosity_by_provider": {provider_id: result}}


def load(path):
    with open(path) as f:
        return json.load(f)


def usd(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value == 0:
            return "0"
        return ("%.12g" % value)
    value = str(value).strip()
    return value or None


def pricing_from_cost(cost):
    if not cost:
        return None
    pricing = {}
    mapping = {
        "input": "input_usd_per_million_tokens",
        "output": "output_usd_per_million_tokens",
        "cache_read": "cache_read_usd_per_million_tokens",
        "cache_write": "cache_write_usd_per_million_tokens",
    }
    for source_key, catalog_key in mapping.items():
        value = usd(cost.get(source_key))
        if value is not None:
            pricing[catalog_key] = value
    tiers = []
    for tier in cost.get("tiers") or []:
        item = {}
        threshold = tier.get("tier") or tier
        if threshold.get("type"):
            item["tier_type"] = threshold["type"]
        if threshold.get("size"):
            item["size_tokens"] = threshold["size"]
        for source_key, catalog_key in mapping.items():
            value = usd(tier.get(source_key))
            if value is not None:
                item[catalog_key] = value
        if item:
            tiers.append(item)
    if tiers:
        pricing["tiers"] = tiers
    return pricing or None


def canonical_input_modalities(model):
    values = []
    for value in (model.get("modalities") or {}).get("input") or []:
        value = {"pdf": "document"}.get(value.lower(), value.lower())
        if value in INPUT_MODALITIES and value not in values:
            values.append(value)
    return sorted(values)


def feature_flags(model):
    source = {
        "reasoning": "reasoning",
        "tool_call": "tool_calling",
        "structured_output": "structured_output",
        "temperature": "temperature",
    }
    supported = []
    unsupported = []
    for source_key, catalog_key in source.items():
        value = model.get(source_key)
        if value is True:
            supported.append(catalog_key)
        elif value is False:
            unsupported.append(catalog_key)
    result = {}
    if supported:
        result["supported"] = sorted(supported)
    if unsupported:
        result["unsupported"] = sorted(unsupported)
    return result or None


def seed_definition(source, origin, provider_id):
    definition = {}
    try:
        definition.update(verbosity_metadata(source, provider_id))
    except ValueError as error:
        source_id = source.get("id") or "<unknown model id>"
        raise ValueError(f"{source_id}: {error}") from error
    status = source.get("status")
    if status in LIFECYCLES:
        definition["lifecycle"] = status

    limits = source.get("limit") or {}
    context = limits.get("context") or limits.get("input")
    if context is not None:
        definition["context_window_tokens"] = context
    if limits.get("input") is not None:
        definition["max_input_tokens"] = limits["input"]
    if limits.get("output") is not None:
        definition["max_output_tokens"] = limits["output"]

    scalar_fields = {
        "description": "description",
        "knowledge": "knowledge_cutoff",
        "release_date": "release_date",
        "last_updated": "last_updated",
        "open_weights": "open_weights",
        "name": "display_name",
    }
    for source_key, catalog_key in scalar_fields.items():
        value = source.get(source_key)
        if value is not None and value != "":
            definition[catalog_key] = value

    definition["origin"] = origin

    interleaved = source.get("interleaved")
    if isinstance(interleaved, dict) and interleaved.get("field"):
        definition["assistant_reasoning_interleaved"] = True
        definition["assistant_reasoning_field"] = interleaved["field"]

    outputs = []
    for value in (source.get("modalities") or {}).get("output") or []:
        value = value.lower()
        if value not in outputs:
            outputs.append(value)
    if outputs:
        definition["output_modalities"] = outputs

    pricing = pricing_from_cost(source.get("cost"))
    if pricing:
        definition["pricing"] = pricing

    inputs = canonical_input_modalities(source)
    if inputs:
        definition["input"] = {"supported": inputs}

    features = feature_flags(source)
    if features:
        definition["features"] = features

    return definition


FIELD_GROUPS = {
    "lifecycle": "descriptive",
    "description": "descriptive",
    "knowledge_cutoff": "descriptive",
    "release_date": "descriptive",
    "last_updated": "descriptive",
    "open_weights": "descriptive",
    "display_name": "descriptive",
    "origin": "descriptive",
    "context_window_tokens": "limits",
    "max_input_tokens": "limits",
    "max_output_tokens": "limits",
    "input": "capabilities",
    "features": "capabilities",
    "output_modalities": "capabilities",
    "verbosity_by_provider": "semantics",
    "supports_parallel_tool_calls": "semantics",
    "default_temperature": "semantics",
    "default_top_p": "semantics",
    "default_top_k": "semantics",
    "assistant_reasoning_interleaved": "semantics",
    "assistant_reasoning_field": "semantics",
    "pricing": "pricing",
}


def _source_definition(source):
    return seed_definition(source.model, source.origin, source.provider)


def _resolve_capability_group(observations, definitions, field):
    values = {}
    for source in observations:
        if source.priority("capabilities") <= 0:
            continue
        selection = definitions[id(source)].get(field)
        if not isinstance(selection, dict):
            continue
        supported = set(selection.get("supported") or [])
        unsupported = set(selection.get("unsupported") or [])
        for item in supported | unsupported:
            values.setdefault(item, []).append((source, item in supported))

    selected = {}
    field_provenance = {}
    conflicts = []
    for item, candidates in sorted(values.items()):
        winner = min(
            candidates,
            key=lambda pair: (
                -pair[0].priority("capabilities"),
                pair[0].policy_rank,
                pair[0].provider,
                pair[0].source_id,
            ),
        )
        status = "supported" if winner[1] else "unsupported"
        selected.setdefault(status, []).append(item)
        candidate_details = [
            {
                "value": "supported" if is_supported else "unsupported",
                "source": source_ref(source, "capabilities"),
            }
            for source, is_supported in candidates
        ]
        winner_detail = next(
            detail
            for detail, (source, _is_supported) in zip(candidate_details, candidates)
            if source == winner[0]
        )
        field_provenance[item] = {
            "value": status,
            "source": source_ref(winner[0], "capabilities"),
        }
        if len({is_supported for _, is_supported in candidates}) > 1:
            conflicts.append({
                "field": f"{field}.{item}",
                "winner": winner_detail,
                "candidates": candidate_details,
                "resolution": "highest field priority, then source policy order",
            })

    resolved = {}
    if selected.get("supported"):
        resolved["supported"] = sorted(selected["supported"])
    if selected.get("unsupported"):
        resolved["unsupported"] = sorted(selected["unsupported"])
    return resolved or None, field_provenance, conflicts


def _resolve_verbosity_group(observations, definitions):
    """Resolve verbosity independently for each API provider namespace."""
    candidates_by_provider = {}
    for source in observations:
        if source.priority("semantics") <= 0:
            continue
        profiles = definitions[id(source)].get("verbosity_by_provider") or {}
        for provider_id, profile in profiles.items():
            candidates_by_provider.setdefault(provider_id, []).append((source, profile))

    resolved = {}
    field_provenance = {}
    conflicts = []
    for provider_id, candidates in sorted(candidates_by_provider.items()):
        winner_source, winner = min(
            candidates,
            key=lambda pair: (
                -pair[0].priority("semantics"),
                pair[0].policy_rank,
                pair[0].provider,
                pair[0].source_id,
            ),
        )
        source_ref_value = source_ref(winner_source, "semantics")
        direct_keys = {
            "supports_verbosity", "default_verbosity",
            "verbosity_levels", "supported_verbosity_levels",
        }
        inherited = not any(key in winner_source.model for key in direct_keys)
        if winner.get("supported") is True:
            resolved[provider_id] = winner
        field_provenance[provider_id] = {
            "kind": "curated_provider_api_profile" if inherited else "upstream_provider_observation",
            "value": winner,
            "source": source_ref_value,
        }
        if len({json.dumps(profile, sort_keys=True) for _, profile in candidates}) > 1:
            conflicts.append({
                "field": f"verbosity_by_provider.{provider_id}",
                "winner": {"value": winner, "source": source_ref_value},
                "candidates": [
                    {"value": value, "source": source_ref(source, "semantics")}
                    for source, value in candidates
                ],
                "resolution": "highest field priority, then source policy order",
            })
    return resolved or None, field_provenance, conflicts


def resolve_model_observations(observations, allowed_field_groups=None):
    """Resolve one canonical definition independently for every field group.

    Missing values do not compete. Explicit false values do. Pricing remains an
    atomic value because tier schedules and cache prices belong together.
    """
    definitions = {id(source): _source_definition(source) for source in observations}
    resolved = {}
    provenance = {}
    conflicts = []

    for field, field_group in FIELD_GROUPS.items():
        if allowed_field_groups is not None and field_group not in allowed_field_groups:
            continue
        if not any(source.priority(field_group) > 0 for source in observations):
            continue
        if field in ("input", "features"):
            value, items, field_conflicts = _resolve_capability_group(
                observations, definitions, field
            )
            if value is not None:
                resolved[field] = value
                provenance[field] = {"items": items}
            conflicts.extend(field_conflicts)
            continue
        if field == "verbosity_by_provider":
            value, provider_provenance, field_conflicts = _resolve_verbosity_group(
                observations, definitions
            )
            if value is not None:
                resolved[field] = value
                provenance[field] = provider_provenance
            conflicts.extend(field_conflicts)
            continue

        candidates = [
            (source, definitions[id(source)][field])
            for source in observations
            if source.priority(field_group) > 0
            and field in definitions[id(source)]
        ]
        if not candidates:
            continue
        winner_source, winner_value = min(
            candidates,
            key=lambda pair: (
                -pair[0].priority(field_group),
                pair[0].policy_rank,
                pair[0].provider,
                pair[0].source_id,
            ),
        )
        resolved[field] = winner_value
        provenance[field] = {
            "value": winner_value,
            "source": source_ref(winner_source, field_group),
        }
        if any(value != winner_value for _, value in candidates):
            conflicts.append({
                "field": field,
                "winner": {"value": winner_value, "source": source_ref(winner_source, field_group)},
                "candidates": [
                    {"value": value, "source": source_ref(source, field_group)}
                    for source, value in candidates
                ],
                "resolution": "highest field priority, then source policy order",
            })

    return resolved, provenance, conflicts


def main():
    catalog = load(CATALOG)
    models_dev = load(MODELS_DEV)
    models = catalog.get("models")
    if not isinstance(models, dict):
        print("models.json: 'models' must be an object", file=sys.stderr)
        return 1

    sources = discover_trusted_models(models_dev)
    missing = sorted(sources.keys() - models.keys())
    if len(missing) > MAX_AUTO_ADDITIONS:
        print(
            f"refusing {len(missing)} automatic additions (limit {MAX_AUTO_ADDITIONS}); "
            "review curation/sources.json and the upstream snapshot",
            file=sys.stderr,
        )
        return 1

    added = []
    for canonical_id in missing:
        definition, _provenance, _conflicts = resolve_model_observations(sources[canonical_id])
        definition["provider_sources"] = sorted(
            {observation.provider for observation in sources[canonical_id]}
        )
        models[canonical_id] = definition
        source = preferred_source(sources[canonical_id], "identity")
        added.append((canonical_id, source.provider, source.source_id))

    if added:
        catalog["models"] = dict(sorted(models.items()))
        with open(CATALOG, "w") as f:
            json.dump(catalog, f, ensure_ascii=False, indent=2)
            f.write("\n")

    print(f"discovered {len(sources)} trusted canonical ids; added {len(added)} new models")
    for canonical_id, provider, source_id in added:
        print(f"  {canonical_id} <- {provider}/{source_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
