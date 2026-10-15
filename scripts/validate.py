#!/usr/bin/env python3
"""Full-document validation mirroring serde deny_unknown_fields + enum checks
across every model in the catalog. This is the publish gate (publish.sh runs it
before committing)."""
import json
import os
import sys

from model_sources import canonical_model_id

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cat = json.load(open(os.path.join(ROOT, "models.json")))
models = cat["models"]

ALLOWED = {
    "lifecycle", "context_window_tokens", "max_input_tokens", "max_output_tokens",
    "description", "knowledge_cutoff", "release_date", "last_updated", "open_weights",
    "supports_parallel_tool_calls", "provider_sources", "verbosity_by_provider",
    "default_temperature", "default_top_p", "default_top_k",
    "assistant_reasoning_interleaved", "assistant_reasoning_field",
    "output_modalities", "pricing", "display_name", "origin",
    "thinking_modes", "speed_modes", "input", "features",
}
LIFECYCLE = {"active", "preview", "beta", "alpha", "experimental", "deprecated"}
STRATS = {"disabled", "effort", "budget", "adaptive", "request_only"}
EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max"}
INPUT_MODS = {"text", "image", "document", "audio", "video", "file"}
FEATURES = {"tool_calling", "streaming", "reasoning", "structured_output", "temperature"}
PRICING_KEYS = {"input_usd_per_million_tokens", "output_usd_per_million_tokens",
                "cache_read_usd_per_million_tokens", "cache_write_usd_per_million_tokens",
                "tiers"}
TIER_KEYS = {"tier_type", "size_tokens", "input_usd_per_million_tokens",
             "output_usd_per_million_tokens", "cache_read_usd_per_million_tokens",
             "cache_write_usd_per_million_tokens"}

errors = []
n = 0
canonical_ids = {}


def check(cond, msg):
    if not cond:
        errors.append(msg)


for mid, c in models.items():
    n += 1
    normalized_id = canonical_model_id(mid)
    if normalized_id is None:
        errors.append(f"{mid}: invalid model ID")
    elif normalized_id != mid:
        errors.append(f"{mid}: route/version alias must be stored as canonical ID {normalized_id!r}")
    elif normalized_id in canonical_ids:
        errors.append(
            f"{mid}: duplicate canonical ID also used by {canonical_ids[normalized_id]}"
        )
    else:
        canonical_ids[normalized_id] = mid
    for k in c:
        if k not in ALLOWED:
            errors.append(f"{mid}: unknown key {k!r}")
            continue
    if c.get("lifecycle") is not None and c["lifecycle"] not in LIFECYCLE:
        errors.append(f"{mid}: bad lifecycle {c['lifecycle']}")
    provider_sources = c.get("provider_sources")
    if provider_sources is not None:
        if (
            not isinstance(provider_sources, list)
            or not provider_sources
            or any(not isinstance(value, str) or not value.strip() or value != value.strip()
                   for value in provider_sources)
            or provider_sources != sorted(set(provider_sources))
        ):
            errors.append(f"{mid}: provider_sources must be sorted, unique provider IDs")
    verbosity_by_provider = c.get("verbosity_by_provider")
    if verbosity_by_provider is not None:
        if not isinstance(verbosity_by_provider, dict) or not verbosity_by_provider:
            errors.append(f"{mid}: verbosity_by_provider must be a non-empty object")
        else:
            sources = set(provider_sources or [])
            for provider_id, profile in verbosity_by_provider.items():
                if provider_id not in sources:
                    errors.append(f"{mid}: verbosity profile provider {provider_id!r} is not in provider_sources")
                if not isinstance(profile, dict):
                    errors.append(f"{mid}: verbosity profile for {provider_id} must be an object")
                    continue
                unknown = set(profile) - {"supported", "levels", "provider_default"}
                if unknown:
                    errors.append(f"{mid}: verbosity profile for {provider_id} has unknown keys {sorted(unknown)}")
                if profile.get("supported") is not True:
                    errors.append(f"{mid}: published verbosity profile for {provider_id} must explicitly be supported")
                levels = profile.get("levels")
                if levels is not None and (
                    not isinstance(levels, list)
                    or any(not isinstance(value, str) or not value.strip() or value != value.strip()
                           for value in levels)
                    or len(levels) != len(set(levels))
                ):
                    errors.append(f"{mid}: verbosity levels for {provider_id} must be unique non-empty strings")
                provider_default = profile.get("provider_default")
                if provider_default is not None and (
                    not isinstance(provider_default, str)
                    or not provider_default.strip()
                    or provider_default != provider_default.strip()
                ):
                    errors.append(f"{mid}: provider default verbosity for {provider_id} must be a trimmed string")
                if levels and provider_default is not None and provider_default not in levels:
                    errors.append(f"{mid}: provider default verbosity for {provider_id} is not an advertised level")
    # numeric limits: u32; 0 is a pre-existing convention for "unknown/unlimited"
    for f in ("context_window_tokens", "max_input_tokens", "max_output_tokens"):
        v = c.get(f)
        if v is not None and (not isinstance(v, int) or v < 0):
            errors.append(f"{mid}: bad {f}={v!r}")
    # capabilities: input/features forms
    for f in ("input", "features"):
        v = c.get(f)
        if v is not None:
            if isinstance(v, list):
                allowed = INPUT_MODS if f == "input" else FEATURES
                for x in v:
                    if x not in allowed:
                        errors.append(f"{mid}: {f} list bad {x!r}")
            elif isinstance(v, dict):
                for sub in ("supported", "unsupported"):
                    lst = v.get(sub)
                    if lst is not None:
                        allowed = INPUT_MODS if f == "input" else FEATURES
                        for x in lst:
                            if x not in allowed:
                                errors.append(f"{mid}: {f}.{sub} bad {x!r}")
            else:
                errors.append(f"{mid}: {f} bad type {type(v)}")
    # thinking modes
    tm = c.get("thinking_modes") or {}
    for mk, mv in tm.items():
        if mk == "default":
            if mv not in tm:
                errors.append(f"{mid}: default thinking {mv!r} not a mode")
            continue
        if not isinstance(mv, dict):
            errors.append(f"{mid}: thinking mode {mk} not dict")
            continue
        if mv.get("strategy") not in STRATS:
            errors.append(f"{mid}: thinking {mk} bad strategy {mv.get('strategy')}")
        if mv.get("effort") is not None and mv["effort"] not in EFFORTS:
            errors.append(f"{mid}: thinking {mk} bad effort {mv['effort']}")
        if mv.get("budget_tokens") is not None and not isinstance(mv["budget_tokens"], int):
            errors.append(f"{mid}: thinking {mk} bad budget_tokens")
    # speed modes
    sm = c.get("speed_modes") or {}
    for mk, mv in sm.items():
        if mk == "default":
            continue
        if not isinstance(mv, dict) or not mv.get("display_name"):
            errors.append(f"{mid}: speed mode {mk} malformed")
    # pricing
    pr = c.get("pricing")
    if pr is not None:
        if not isinstance(pr, dict):
            errors.append(f"{mid}: pricing not dict")
        else:
            for k in pr:
                if k not in PRICING_KEYS:
                    errors.append(f"{mid}: pricing unknown key {k!r}")
            for t in pr.get("tiers") or []:
                if not isinstance(t, dict):
                    errors.append(f"{mid}: pricing tier not dict")
                    continue
                for k in t:
                    if k not in TIER_KEYS:
                        errors.append(f"{mid}: pricing tier unknown key {k!r}")

print(f"validated {n} models")
if errors:
    print(f"\nERRORS ({len(errors)}):")
    for e in errors[:80]:
        print("  ", e)
    sys.exit(1)
print("ALL PASS: no unknown keys, valid enums, valid pricing/limits")
