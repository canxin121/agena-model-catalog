#!/usr/bin/env python3
"""Apply curated patch files (curation/patches/*.json) onto models.json, then
validate. Patches are authoritative for the fields they contain (they were
human/agent-verified against official sources). Validate: JSON shape matches
catalog schema, no unknown keys, no models added that don't exist, thinking/
speed mode shapes are legal, then re-run coverage stats."""
import json
import os
import sys
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(ROOT, "models.json")
PATCH_DIR = os.path.join(ROOT, "curation", "patches")

ALLOWED_TOP = {
    "thinking_modes", "speed_modes", "max_input_tokens", "context_window_tokens",
    "max_output_tokens", "knowledge_cutoff", "description", "pricing", "release_date",
    "last_updated", "open_weights", "display_name",
}
THINK_STRATS = {"disabled", "effort", "budget", "adaptive", "request_only"}
EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max"}


def main():
    cat = json.load(open(CAT))
    models = cat["models"]

    patched = 0
    models_touched = set()
    errors = []

    patch_files = sorted(glob.glob(os.path.join(PATCH_DIR, "*.json")))
    if not patch_files:
        print("no patch files yet")
        return

    for pf in patch_files:
        try:
            patch = json.load(open(pf))
        except Exception as e:
            errors.append(f"{os.path.basename(pf)}: unparseable ({e})")
            continue
        pmodels = patch.get("models")
        if not isinstance(pmodels, dict):
            errors.append(f"{os.path.basename(pf)}: no models dict")
            continue
        for mid, pv in pmodels.items():
            if not isinstance(pv, dict):
                errors.append(f"{os.path.basename(pf)}: model {mid} not object")
                continue
            if mid not in models:
                errors.append(f"{os.path.basename(pf)}: model {mid} NOT IN CATALOG")
                continue
            cur = models[mid]
            for k, v in pv.items():
                if k not in ALLOWED_TOP:
                    errors.append(f"{os.path.basename(pf)}: model {mid} unknown field {k}")
                    continue
                if v is None:
                    # null = delete the key (used to clear a field that should
                    # be absent, e.g. thinking_modes for runtime-enriched
                    # models). A literal null would fail Rust deserialization
                    # since these fields are not Option.
                    cur.pop(k, None)
                    continue
                cur[k] = v
            models_touched.add(mid)
            patched += 1

    # ---- validation of thinking/speed modes shape ----
    for mid in models_touched:
        cur = models[mid]
        tm = cur.get("thinking_modes")
        if tm is not None:
            if not isinstance(tm, dict):
                errors.append(f"{mid}: thinking_modes not dict")
            else:
                for mk, mv in tm.items():
                    if mk == "default":
                        continue
                    if not isinstance(mv, dict):
                        errors.append(f"{mid}: thinking mode {mk} not dict")
                        continue
                    strat = mv.get("strategy")
                    if strat not in THINK_STRATS:
                        errors.append(f"{mid}: thinking mode {mk} bad strategy {strat}")
                    if strat == "effort" and mv.get("effort") not in EFFORTS:
                        errors.append(f"{mid}: thinking mode {mk} bad effort {mv.get('effort')}")
        sm = cur.get("speed_modes")
        if sm is not None:
            if not isinstance(sm, dict):
                errors.append(f"{mid}: speed_modes not dict")
            else:
                for mk, mv in sm.items():
                    if not isinstance(mv, dict) or "display_name" not in mv:
                        errors.append(f"{mid}: speed mode {mk} malformed")

    print(f"patched {patched} model-field-sets across {len(models_touched)} models")
    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for e in errors[:60]:
            print("  ", e)
        sys.exit(1)
    else:
        print("validation passed")

    json.dump(cat, open(CAT, "w"), ensure_ascii=False, indent=2)
    print("wrote", CAT)


if __name__ == "__main__":
    main()
