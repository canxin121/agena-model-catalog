#!/usr/bin/env python3
"""Cross-check thinking modes against the models.dev snapshot's
reasoning_options.

Two passes:

1. Patches (curation/patches/*.json): a patch that sets thinking_modes on a
   model whose ropts contradict it (or whose ropts are absent/empty) is a
   fabrication signal. Mismatches fail the run.
2. Catalog (models.json): entries whose effort modes are wider than the trusted
   first-party record publishes, or that offer an off mode the vendor does not
   publish. Reported only - curated entries are deliberately allowed to be
   wider than a gateway-shaped source record.

Run after fetch_modelsdev.sh; pass specific patch files to check only those:
    python3 scripts/verify_thinking.py curation/patches/domestic_*.json
"""
import json
import os
import sys
import glob

from model_sources import discover_trusted_models

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
md = json.load(open(os.path.join(ROOT, ".cache/models.dev.json")))
trusted = discover_trusted_models(md)
dev = {}
for prov in md.values():
    for mid, m in (prov.get("models") or {}).items():
        real = m.get("id") or mid
        dev.setdefault(real, m)
        dev.setdefault(mid, m)


def patch_has_toggle(tm):
    for k, v in (tm or {}).items():
        if k == "default":
            continue
        if isinstance(v, dict) and v.get("strategy") == "request_only":
            return True
    return False


def patch_has_effort(tm):
    for k, v in (tm or {}).items():
        if k == "default":
            continue
        if isinstance(v, dict) and v.get("strategy") == "effort":
            return True
    return False


def patch_always_on(tm):
    # a single mode with no off toggle = always-on reasoning variant
    if not tm:
        return False
    return not patch_has_toggle(tm) and not any(
        isinstance(v, dict) and v.get("strategy") == "disabled" for v in tm.values())


def ropts_kind(ro):
    if not ro:
        return None
    for r in ro:
        t = r.get("type")
        if t == "effort":
            return "effort"
        if t == "toggle":
            return "toggle"
        if t == "token":
            return "budget"
    return "other"


def check(pf):
    base = os.path.basename(pf)
    patch = json.load(open(pf))
    pmodels = patch.get("models") or {}
    mismatch, empty, absent, ok, skipped = [], [], [], [], []
    for mid, pv in sorted(pmodels.items()):
        tm = pv.get("thinking_modes")
        if not tm:
            skipped.append((mid, "no thinking_modes in patch"))
            continue
        m = dev.get(mid)
        if m is None:
            # :thinking / alias variants won't match; try stripping suffixes
            absent.append((mid, "not in models.dev (alias/variant?)"))
            continue
        ro = m.get("reasoning_options")
        kind = ropts_kind(ro)
        has_t = patch_has_toggle(tm)
        has_e = patch_has_effort(tm)
        if kind == "toggle" and has_e and not has_t:
            mismatch.append((mid, "patch=effort but ropts=toggle", ro))
        elif kind == "effort" and has_t and not has_e:
            mismatch.append((mid, "patch=toggle but ropts=effort", ro))
        elif kind in ("effort", "toggle") and (has_t or has_e):
            ok.append((mid, kind))
        elif kind is None:
            if patch_always_on(tm):
                # always-on variants are deliberate (e.g. -thinking models);
                # only flag if base model is a non-reasoning type
                empty.append((mid, "ropts empty but always-on mode (check base model)"))
            else:
                empty.append((mid, "ropts empty — template risk", ro))
        else:
            empty.append((mid, f"ropts kind={kind}", ro))
    return base, mismatch, empty, absent, ok


def catalog_pass():
    """Report catalog entries that are wider than the trusted record (advisory)."""
    catalog = json.load(open(os.path.join(ROOT, "models.json")))["models"]
    checked = wider = off_unsupported = 0
    wider_rows = []
    off_rows = []
    for mid, c in sorted(catalog.items()):
        tm = c.get("thinking_modes") or {}
        if not tm:
            continue
        source = trusted.get(mid)
        if source is None:
            continue
        values = set()
        for option in source.model.get("reasoning_options") or []:
            if isinstance(option, dict) and option.get("type") == "effort":
                values |= {str(v).strip().lower() for v in option.get("values") or []}
        if not values:
            continue
        checked += 1
        efforts = {
            m.get("effort")
            for mk, m in tm.items()
            if mk != "default" and isinstance(m, dict) and m.get("strategy") == "effort"
        }
        extra = {effort for effort in efforts if effort} - values
        has_off = any(
            isinstance(m, dict) and m.get("strategy") == "disabled"
            for mk, m in tm.items()
            if mk != "default"
        )
        if extra:
            wider += 1
            wider_rows.append((mid, sorted(extra), sorted(values)))
        if has_off and "none" not in values:
            off_unsupported += 1
            off_rows.append(mid)
    print("\n===== catalog cross-check (report only) =====")
    print(f"  entries with a trusted record to compare: {checked}")
    print(f"  offer effort values the trusted record does not publish: {wider}")
    for mid, extra, values in wider_rows[:15]:
        print(f"    {mid}: catalog has {extra}, trusted publishes {values}")
    if len(wider_rows) > 15:
        print(f"    ... {len(wider_rows) - 15} more")
    print(f"  offer an off mode while the trusted record lists no 'none': {off_unsupported}")
    for mid in off_rows[:15]:
        print(f"    {mid}")
    if len(off_rows) > 15:
        print(f"    ... {len(off_rows) - 15} more")


def main():
    targets = sys.argv[1:] or sorted(
        glob.glob(os.path.join(ROOT, "curation/patches/*.json")))
    explicit_targets = bool(sys.argv[1:])
    total_mismatch = total_empty = 0
    for t in targets:
        base, mismatch, empty, absent, ok = check(t)
        print(f"\n===== {base} =====")
        print(f"  patched-with-thinking: {len(mismatch)+len(empty)+len(ok)} (ok={len(ok)})")
        if mismatch:
            print(f"  *** MISMATCH ({len(mismatch)}) ***")
            for mid, why, ro in mismatch:
                print(f"    {mid}: {why}  ropts={json.dumps(ro)}")
            total_mismatch += len(mismatch)
        if empty:
            print(f"  ropts-empty/unsupported ({len(empty)})")
            for row in empty:
                if len(row) == 3:
                    mid, why, ro = row
                else:
                    mid, why = row
                print(f"    {mid}: {why}")
            total_empty += len(empty)
        if absent:
            print(f"  absent-from-models.dev ({len(absent)}): {', '.join(m for m, _ in absent[:25])}")
    if not explicit_targets:
        catalog_pass()
    print(f"\n===== TOTALS: {total_mismatch} mismatches, {total_empty} ropts-empty =====")
    if total_mismatch:
        sys.exit(1)


if __name__ == "__main__":
    main()
