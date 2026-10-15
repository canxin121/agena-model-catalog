"""Discover every allowlisted models.dev observation for a canonical ID.

The old implementation used ``setdefault`` and discarded all but the first
whole provider record. Callers now keep all observations and select values per
field group using the source registry plus the explicit provider order in
curation/sources.json as a deterministic tie-breaker.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent
SOURCE_POLICY = ROOT / "curation" / "sources.json"
UPSTREAM_REGISTRY = ROOT / "curation" / "upstreams.json"
VALID_ID = re.compile(r"[a-z0-9][a-z0-9._:-]*\Z")


@dataclass(frozen=True)
class SourceModel:
    provider: str
    source_id: str
    origin: str
    model: dict
    upstream: str
    policy_rank: int
    field_priorities: dict

    def priority(self, field_group):
        return int(self.field_priorities.get(field_group, 0))


def canonical_model_id(source_id):
    """Mirror Agena's common first-party and Hugging Face ID transforms."""
    value = source_id.strip().lower().rsplit("/", 1)[-1]
    value = re.sub(r"@(eu|us|global|apac|jp|au|[0-9]{8})$", "", value)
    for suffix in ("@default", "-maas", ":free", "-free"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
    value = value.replace("_", ".")
    rules = (
        (r"^(claude-(?:haiku|opus|sonnet)-)(\d)(\d)(.*)$", r"\1\2-\3\4"),
        (r"^(deepseek-v)(\d+)[-.](\d+)(.*)$", r"\1\2.\3\4"),
        (r"^(gemini)-(\d+)[-.](\d+)(.*)$", r"\1-\2.\3\4"),
        (r"^(gpt)-(\d+)[-.](\d+)(.*)$", r"\1-\2.\3\4"),
        (r"^(grok)-(\d+)(\d)(.*)$", r"\1-\2.\3\4"),
        (r"^(grok)-(\d+)[-.](\d+)(.*)$", r"\1-\2.\3\4"),
        (r"^(kimi-k\d+)[-.](\d+)(.*)$", r"\1.\2\3"),
        (r"^(llama)-(\d+)[-.](\d+)(.*)$", r"\1-\2.\3\4"),
        (r"^(minimax-m\d+)[-.](\d+)(.*)$", r"\1.\2\3"),
        (r"^(mistral-small)-(\d+)[-.](\d+)(.*)$", r"\1-\2.\3\4"),
        (r"^(qwen\d+)[-.](\d+)(.*)$", r"\1.\2\3"),
    )
    for pattern, replacement in rules:
        value = re.sub(pattern, replacement, value)
    while "--" in value:
        value = value.replace("--", "-")
    return value if VALID_ID.fullmatch(value) else None


def _allowed(model_name, spec):
    prefixes = spec.get("prefixes")
    return not prefixes or model_name.lower().startswith(tuple(p.lower() for p in prefixes))


def _registry_source(upstreams, upstream_id):
    for source in upstreams["sources"]:
        if source["id"] == upstream_id:
            return source
    raise ValueError(f"upstream {upstream_id!r} is absent from curation/upstreams.json")


def discover_trusted_models(models_dev):
    """Return canonical ID -> all allowlisted observations, without dropping rows."""
    if not isinstance(models_dev, dict) or len(models_dev) < 100:
        raise ValueError("models.dev snapshot is missing most providers")
    with SOURCE_POLICY.open(encoding="utf-8") as file:
        policy = json.load(file)
    with UPSTREAM_REGISTRY.open(encoding="utf-8") as file:
        upstreams = json.load(file)
    result = {}
    provider_specs = policy["providers"]
    base_priorities = _registry_source(upstreams, "models.dev").get("field_priorities", {})

    def add(canonical_id, record):
        result.setdefault(canonical_id, []).append(record)

    for rank, spec in enumerate(provider_specs):
        provider_id = spec["id"]
        provider_models = (models_dev.get(provider_id) or {}).get("models")
        if not isinstance(provider_models, dict) or not provider_models:
            raise ValueError(f"trusted provider {provider_id!r} is missing from the snapshot")
        for raw_id, model in sorted(provider_models.items()):
            source_id = model.get("id") or raw_id
            if "/" in source_id or not _allowed(source_id, spec):
                continue
            canonical_id = canonical_model_id(source_id)
            if canonical_id:
                add(
                    canonical_id,
                    SourceModel(
                        provider_id,
                        raw_id,
                        spec["origin"],
                        model,
                        "models.dev",
                        rank,
                        base_priorities,
                    ),
                )

    hf_models = (models_dev.get("huggingface") or {}).get("models")
    if not isinstance(hf_models, dict) or not hf_models:
        raise ValueError("Hugging Face models are missing from the models.dev snapshot")
    hf_rank_offset = len(provider_specs)
    for offset, spec in enumerate(policy["huggingface_organizations"]):
        organization = spec["id"]
        for raw_id, model in sorted(hf_models.items()):
            source_id = model.get("id") or raw_id
            namespace, separator, model_name = source_id.partition("/")
            if not separator or namespace != organization or not _allowed(model_name, spec):
                continue
            canonical_id = canonical_model_id(source_id)
            if canonical_id:
                add(
                    canonical_id,
                    SourceModel(
                        "huggingface",
                        raw_id,
                        spec["origin"],
                        model,
                        "models.dev",
                        hf_rank_offset + offset,
                        base_priorities,
                    ),
                )

    for observations in result.values():
        observations.sort(key=lambda item: (item.policy_rank, item.provider, item.source_id))
    return result


def discover_exact_models(models_dev):
    """Return all literal-ID observations for conservative legacy filling."""
    with UPSTREAM_REGISTRY.open(encoding="utf-8") as file:
        upstreams = json.load(file)
    configured_priorities = upstreams["global_model_field_priority"]["legacy_exact_id_fallback"]
    if isinstance(configured_priorities, dict):
        priorities = {group: int(configured_priorities.get(group, 0)) for group in upstreams["field_groups"]}
    else:
        fallback_priority = int(configured_priorities)
        priorities = {group: fallback_priority for group in upstreams["field_groups"]}
    result = {}
    for provider_id, provider in sorted(models_dev.items()):
        provider_models = provider.get("models") or {}
        provider_name = provider.get("name") or provider_id
        for raw_id, model in sorted(provider_models.items()):
            if not isinstance(model, dict):
                continue
            source_id = model.get("id") or raw_id
            source = SourceModel(
                provider_id,
                raw_id,
                provider_name,
                model,
                "models.dev",
                0,
                priorities,
            )
            for exact_id in {source_id, raw_id}:
                result.setdefault(exact_id, []).append(source)
    for observations in result.values():
        observations.sort(key=lambda item: (item.provider, item.source_id))
    return result


def preferred_source(observations, field_group):
    """Pick the highest-priority observation; policy order resolves equal ranks."""
    if not observations:
        return None
    # All trusted observations currently come from models.dev. Keep the
    # priority explicit even though provider policy order breaks its ties.
    return min(
        observations,
        key=lambda item: (-item.priority(field_group), item.policy_rank, item.provider, item.source_id),
    )


def source_ref(source, field_group):
    return {
        "upstream": source.upstream,
        "provider": source.provider,
        "source_id": source.source_id,
        "priority": source.priority(field_group),
        "policy_rank": source.policy_rank,
    }
