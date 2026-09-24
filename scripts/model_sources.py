"""Discover canonical models from first-party models.dev records.

The source policy is curated once per provider or official Hugging Face
organization. Individual model IDs are discovered on every refresh. Earlier
policy entries win when several trusted sources publish the same model.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent
SOURCE_POLICY = ROOT / "curation" / "sources.json"
VALID_ID = re.compile(r"[a-z0-9][a-z0-9._:-]*\Z")


@dataclass(frozen=True)
class SourceModel:
    provider: str
    source_id: str
    origin: str
    model: dict


def canonical_model_id(source_id):
    """Mirror Agena's common first-party and Hugging Face ID transforms."""
    value = source_id.strip().lower().rsplit("/", 1)[-1]
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


def discover_trusted_models(models_dev):
    """Return one deterministic, source-backed record per canonical model ID."""
    if not isinstance(models_dev, dict) or len(models_dev) < 100:
        raise ValueError("models.dev snapshot is missing most providers")
    with SOURCE_POLICY.open() as file:
        policy = json.load(file)
    result = {}

    for spec in policy["providers"]:
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
                result.setdefault(
                    canonical_id,
                    SourceModel(provider_id, raw_id, spec["origin"], model),
                )

    hf_models = (models_dev.get("huggingface") or {}).get("models")
    if not isinstance(hf_models, dict) or not hf_models:
        raise ValueError("Hugging Face models are missing from the snapshot")
    for spec in policy["huggingface_organizations"]:
        organization = spec["id"]
        for raw_id, model in sorted(hf_models.items()):
            source_id = model.get("id") or raw_id
            namespace, separator, model_name = source_id.partition("/")
            if not separator or namespace != organization or not _allowed(model_name, spec):
                continue
            canonical_id = canonical_model_id(source_id)
            if canonical_id:
                result.setdefault(
                    canonical_id,
                    SourceModel("huggingface", raw_id, spec["origin"], model),
                )

    return result
