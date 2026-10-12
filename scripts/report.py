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
speed = {mid: (c.get('speed_modes') or {}) for mid, c in cat.items() if c.get('speed_modes')}
print(f"speed_modes present: {len(speed)}")
no_standard = sorted(mid for mid, modes in speed.items() if 'standard' not in modes)
print(f"  of which missing the explicit `standard` (Default) entry: {len(no_standard)}")
for mid in no_standard[:10]:
    print(f"    no standard entry: {mid}")
not_pointing_at_standard = sorted(
    mid for mid, modes in speed.items()
    if modes.get('default') not in (None, 'standard')
)
for mid in not_pointing_at_standard[:10]:
    print(f"    default pointer is curated: {mid} -> {speed[mid].get('default')}")
print(f"input capabilities present: {n - miss('input')}")
print(f"features capabilities present: {n - miss('features')}")
rs = sum(1 for c in cat.values() if reasoning_supported(c))
rs_no_tm = sum(1 for c in cat.values() if reasoning_supported(c) and not c.get('thinking_modes'))
print(f"reasoning-supported: {rs}, of which still NO thinking modes: {rs_no_tm}")
if rs_no_tm:
    # These either have no trusted first-party record (aggregator aliases and
    # gateway variants) or a record that only advertises a toggle/budget option.
    # The runtime no longer infers modes for them, so they stay without a
    # thinking selector until a curated patch adds one.
    missing = sorted(mid for mid, c in cat.items()
                     if reasoning_supported(c) and not c.get('thinking_modes'))
    for mid in missing[:20]:
        print(f"    no thinking modes: {mid}")
    if len(missing) > 20:
        print(f"    ... {len(missing) - 20} more")
