# Curation layer

`patches/` holds the hand-verified metadata edits that sit on top of the
models.dev-derived base. Each file is a `{ "models": { "<model-id>": {...} } }`
object that `scripts/apply_patches.py` merges into `models.json`.

## Discovering new model ids

`scripts/seed_modelsdev.py` automatically adds new IDs found in the first-party
providers and official Hugging Face organizations listed in `sources.json`.
The policy is ordered: the first trusted source for a canonical ID wins. Prefix
rules keep mixed providers such as Alibaba China and Volcengine from admitting
other vendors' hosted models. Gateway providers are not discovery sources.
To support a new vendor, add its provider or official organization once to
`sources.json`; individual new models then require no entry. `patches/` never
create catalog members and remain for verified exceptions.

`sources.json` also lists route providers whose context and output limits constrain the
shared catalog value for a model already found through a trusted source. A
route provider cannot add an identity on its own. This replaces individual
limit patches for Cline Pass models.

## Why patches instead of editing models.json directly

- The base comes from models.dev (see `scripts/merge_modelsdev.py`). Any field
  a refresh re-derives must not clobber a hand-verified value, so curated
  overrides live separately and are applied *after* the merge.
- A patch is a reviewable unit: each one corresponds to one verified change set
  (a family sweep, a capability fix, a pricing table) and can be re-verified
  independently (`scripts/verify_thinking.py`).

## Conventions

- **Patch fields are authoritative** for the keys they contain. `null` deletes
  a key from the merged model (used to clear fields that should be absent,
  e.g. `thinking_modes` on runtime-enriched models — a literal null would fail
  Rust deserialization since these fields are not `Option`).
- **Never fabricate.** Only include values verified from an official source
  (vendor docs, models.dev, HuggingFace model cards). A missing field is always
  preferable to a wrong one.
- Allowed top-level fields in a patch:
  `thinking_modes`, `speed_modes`, `max_input_tokens`, `context_window_tokens`,
  `max_output_tokens`, `knowledge_cutoff`, `description`, `pricing`,
  `release_date`, `last_updated`, `open_weights`, `display_name`.
- **Never add a model** that is not already in `models.json` (apply_patches.py
  rejects it).
- Thinking/speed modes must pass `scripts/apply_patches.py` shape checks and
  should be cross-checked against models.dev `reasoning_options` with
  `scripts/verify_thinking.py`.

## Historical note

The 2026-08 initial sweep generated `patches/` from upstream aggregators
(models.dev + OpenAI codex + HuggingFace + NVIDIA + per-vendor docs) with a
curation pass, then hand-reviewed. The one-off analysis scripts that produced
them were not kept; their durable inputs are the domestic-family verification
documents in `docs/research/`.

## Adding a patch

1. Read [`PATCH_SPEC.md`](PATCH_SPEC.md) — the detailed authoring spec (output
   contract, thinking/speed mode decision rules, source priority, no-fabrication
   rules). Follow it.
2. Write `<name>.json` in `patches/` (follow the conventions above).
3. Run `bash scripts/refresh.sh --no-fetch` to apply + validate + report.
4. Cross-check thinking modes: `python3 scripts/verify_thinking.py curation/patches/<name>.json`.
5. Commit with a message describing the change set, e.g.
   `chore(catalog): add thinking modes for <family>`.
