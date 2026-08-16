#!/usr/bin/env python3
"""Merge authoritative base fields from models.dev into the catalog for any
model whose key matches exactly. Fill only missing fields; never overwrite
existing values. Capabilities are merged (union of supported/unsupported).

Models.dev is the authoritative base for limits, pricing, descriptions,
knowledge cutoffs, and input/features capabilities. Run after fetch_modelsdev.sh.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path):
    with open(os.path.join(ROOT, path)) as f:
        return json.load(f)


cat = load("models.json")
md = load(".cache/models.dev.json")

# index models.dev by exact model id (and the raw key, for aliases)
dev = {}
for prov in md.values():
    for mid, m in (prov.get("models") or {}).items():
        real = m.get("id") or mid
        dev.setdefault(real, m)
        dev.setdefault(mid, m)


def usd(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return ("%.2f" % v).rstrip("0").rstrip(".") if v == int(v) else ("%g" % v)
    s = str(v).strip()
    return s if s and s not in ("0", "0.0") else None


def num2(v):
    return usd(v)


def pricing_from_cost(cost):
    if not cost:
        return None
    p = {}
    p["input_usd_per_million_tokens"] = num2(cost.get("input"))
    p["output_usd_per_million_tokens"] = num2(cost.get("output"))
    p["cache_read_usd_per_million_tokens"] = num2(cost.get("cache_read"))
    p["cache_write_usd_per_million_tokens"] = num2(cost.get("cache_write"))
    tiers = []
    for t in cost.get("tiers") or []:
        d = {}
        if t.get("type"):
            d["tier_type"] = t["type"]
        if t.get("size"):
            d["size_tokens"] = t["size"]
        d["input_usd_per_million_tokens"] = num2(t.get("input"))
        d["output_usd_per_million_tokens"] = num2(t.get("output"))
        if any(d.values()):
            tiers.append(d)
    if tiers:
        p["tiers"] = tiers
    if any(v for v in p.values() if not isinstance(v, list)):
        return p
    return None


def cap_from_model(m):
    """Build the flat capability fields (input/features) from models.dev
    signals. The catalog schema uses flattened top-level input/features — never
    a nested `capabilities` key — so this writes the final shape directly."""
    inp = m.get("modalities") or {}
    inputs = []
    for x in inp.get("input") or []:
        # models.dev spells document input "pdf"; the catalog schema uses
        # "document" (allowed set: text/image/document/audio/video/file).
        canonical = {"pdf": "document"}.get(x.lower(), x.lower())
        if canonical in ("text", "image", "audio", "video", "document", "file"):
            inputs.append(canonical)
    patch = {}
    if inputs:
        patch["input"] = {"supported": inputs}
    features_sup = []
    features_unsup = []
    if m.get("reasoning") is True:
        features_sup.append("reasoning")
    if m.get("tool_call") is True:
        features_sup.append("tool_calling")
    if m.get("structured_output") is True:
        features_sup.append("structured_output")
    if m.get("temperature") is True:
        features_sup.append("temperature")
    if m.get("reasoning") is False:
        features_unsup.append("reasoning")
    if m.get("tool_call") is False:
        features_unsup.append("tool_calling")
    if m.get("structured_output") is False:
        features_unsup.append("structured_output")
    if m.get("temperature") is False:
        features_unsup.append("temperature")
    if features_sup or features_unsup:
        feats = {}
        if features_sup:
            feats["supported"] = features_sup
        if features_unsup:
            feats["unsupported"] = features_unsup
        patch["features"] = feats
    return patch


def merge_flat(existing, key, patchval):
    """Union one capability field into the flat form.
    existing: None | list (legacy array form) | {supported, unsupported}"""
    def union(ex, sub, patchlist):
        ex_set = set((ex or {}).get(sub) or [])
        ex_set.update(patchlist or [])
        return sorted(ex_set)

    if existing is None:
        return patchval
    if isinstance(existing, list):
        # legacy array form: members are the "supported" baseline, but the
        # patch is authoritative for what it explicitly mentions — patch
        # unsupported members leave supported and are recorded as unsupported.
        existing_set = set(existing)
        patch_sup = set(patchval.get("supported") or [])
        patch_unsup = set(patchval.get("unsupported") or [])
        result = {"supported": sorted((existing_set - patch_unsup) | patch_sup)}
        if patch_unsup:
            result["unsupported"] = sorted(patch_unsup)
        return result
    nd = dict(existing)
    if isinstance(patchval, dict):
        if "supported" in patchval:
            nd["supported"] = union(existing, "supported", patchval["supported"])
        if "unsupported" in patchval:
            nd["unsupported"] = union(existing, "unsupported", patchval["unsupported"])
    return nd


stats = {
    k: 0
    for k in ("description", "knowledge_cutoff", "context", "max_output",
              "pricing", "input", "features", "release_date", "open_weights", "max_input")
}
matched = 0
for cid, cdef in cat["models"].items():
    m = dev.get(cid) or dev.get(cid.lower())
    if m is None:
        continue
    matched += 1
    if cdef.get("description") is None and m.get("description"):
        cdef["description"] = m["description"]; stats["description"] += 1
    if cdef.get("knowledge_cutoff") is None and m.get("knowledge"):
        cdef["knowledge_cutoff"] = m["knowledge"]; stats["knowledge_cutoff"] += 1
    if cdef.get("release_date") is None and m.get("release_date"):
        cdef["release_date"] = m["release_date"]; stats["release_date"] += 1
    if cdef.get("open_weights") is None and m.get("open_weights") is not None:
        cdef["open_weights"] = m["open_weights"]; stats["open_weights"] += 1
    lim = m.get("limit") or {}
    if cdef.get("context_window_tokens") is None and (lim.get("context") or lim.get("input")):
        cdef["context_window_tokens"] = lim.get("context") or lim.get("input"); stats["context"] += 1
    if cdef.get("max_output_tokens") is None and lim.get("output"):
        cdef["max_output_tokens"] = lim["output"]; stats["max_output"] += 1
    if cdef.get("max_input_tokens") is None and lim.get("input"):
        cdef["max_input_tokens"] = lim["input"]; stats["max_input"] += 1
    if cdef.get("pricing") is None:
        p = pricing_from_cost(m.get("cost"))
        if p:
            cdef["pricing"] = p; stats["pricing"] += 1
    cap = cap_from_model(m)
    if cap:
        for key in ("input", "features"):
            if key in cap:
                merged = merge_flat(cdef.get(key), key, cap[key])
                if merged != cdef.get(key):
                    cdef[key] = merged
                    stats[key] += 1

print(f"matched exact ids: {matched}/{len(cat['models'])}")
print("fields filled from models.dev:")
for k, v in stats.items():
    print(f"  {k}: {v}")

out = os.path.join(ROOT, "models.json")
with open(out, "w") as f:
    json.dump(cat, f, ensure_ascii=False, indent=2)
print("wrote", out)
