#!/usr/bin/env python3
"""Post-merge coverage report: how much of the catalog still misses each
authoritative field. Uses the flattened schema (input/features at top level;
there is no nested `capabilities` key — fix_capabilities folded it)."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cat = json.load(open(os.path.join(ROOT, "models.json")))["models"]


def reasoning_supported(c):
    feats = c.get("features")
    if isinstance(feats, list):
        return "reasoning" in feats
    if isinstance(feats, dict):
        return "reasoning" in (feats.get("supported") or [])
    return False


n = len(cat)


def miss(f):
    return sum(1 for c in cat.values() if c.get(f) is None)


print(f"total models: {n}")
for f in ("description", "context_window_tokens", "max_input_tokens", "max_output_tokens",
          "pricing", "knowledge_cutoff"):
    print(f"missing {f}: {miss(f)}")
print(f"thinking_modes present: {sum(1 for c in cat.values() if c.get('thinking_modes'))}")
print(f"speed_modes present: {sum(1 for c in cat.values() if c.get('speed_modes'))}")
print(f"input capabilities present: {n - miss('input')}")
print(f"features capabilities present: {n - miss('features')}")
rs = sum(1 for c in cat.values() if reasoning_supported(c))
rs_no_tm = sum(1 for c in cat.values() if reasoning_supported(c) and not c.get('thinking_modes'))
print(f"reasoning-supported: {rs}, of which still NO thinking modes: {rs_no_tm}")
