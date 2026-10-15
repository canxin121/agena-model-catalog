# Curation layer

`patches/` holds the hand-verified metadata edits that sit on top of the
automatically resolved model-level base. Each file is a `{ "models": { "<model-id>": {...} } }`
object that `scripts/apply_patches.py` merges into `models.json`.

`upstreams.json` is the independent upstream registry. It records URLs, source
scope, field groups, priorities, and mirrors. `sources.json` is a separate
selection policy for provider records inside models.dev and the official HF
organization/prefix discovery list.

## Discovering new model ids

`scripts/seed_modelsdev.py` automatically adds new IDs found in the first-party
providers and official Hugging Face organizations listed in `sources.json`.
The policy order is a tie-breaker when multiple allowlisted records have equal
field priority. All observations mapping to one canonical ID are retained and
fields are resolved by group instead of selecting one winning record wholesale.
Prefix rules keep mixed providers such as Alibaba China and Volcengine from
admitting other vendors' hosted models. Gateway providers are not canonical
model discovery sources. To support a new vendor, add its provider or official
organization once to `sources.json`; individual new models then require no
entry. `patches/` never create catalog members and remain for verified
exceptions.

`sources.json` also lists route providers whose context and output limits constrain the
shared catalog value for a model already found through a trusted source. A
route provider cannot add an identity on its own. This replaces individual
limit patches for Cline Pass models.

## Source scopes and priority

- **Verified patch (100):** manually checked provider facts; runs last.
- **models.dev publisher record (70):** canonical API model descriptions,
  limits, capabilities, semantics, pricing, and published modes, subject to the
  allowlist in `sources.json`.
- **Legacy exact-ID fallback (20 for descriptive facts):** can fill missing
  knowledge cutoff, release date, or open-weight status for an existing catalog
  entry with no allowlisted publisher record. Its route-specific limits,
  pricing, capabilities, and verbosity are never promoted to publisher-wide data.
- **OpenRouter route (90):** applies only to an exact OpenRouter route.
- **LiteLLM route reference (40):** route-level cross-check, not a model-global
  fallback.
- **Hugging Face artifact (100 for artifact facts):** repository/license/task
  metadata; it does not automatically define a hosted API model.
- **OpenCode mirror (0):** same bytes as models.dev in the audit, so it is not
  fetched or counted independently.
- **Codex and Gemini CLI presets (0 for provider facts):** client behavior only.

Route and artifact sources are emitted under `data/routes/` and
`data/artifacts/`. Route records keep the complete source object in `raw`.
Hugging Face artifact rows link to `data/observations/huggingface.json`, which
keeps each complete repository object once, including fields the current
normalizer does not interpret. Model-level field choices are explained in
`data/model-provenance.json`; disagreements are listed in
`data/source-conflicts.json`.

## Why patches instead of editing models.json directly

- The base comes from source-prioritized observations (see
  `scripts/merge_modelsdev.py`). Any field a refresh re-derives must not
  clobber a hand-verified value, so curated overrides live separately and are
  applied *after* the merge.
- A patch is a reviewable unit: each one corresponds to one verified change set
  (a family sweep, a capability fix, a pricing table) and can be re-verified
  independently (`scripts/verify_thinking.py`).

## Conventions

- **Patch fields are authoritative** for the keys they contain. `null` deletes
  a key from the merged model — a literal null would fail Rust deserialization
  since these fields are not `Option`. `null` must not be used to blank
  `thinking_modes` any more: the runtime no longer infers modes, so deleting a
  derived ladder removes the model's thinking selector.
- **Never fabricate.** Only include values verified from an official source
  (vendor docs, models.dev, HuggingFace model cards). A missing field is always
  preferable to a wrong one.
- Allowed top-level fields in a patch:
  `thinking_modes`, `speed_modes`, `max_input_tokens`, `context_window_tokens`,
  `max_output_tokens`, `knowledge_cutoff`, `description`, `pricing`,
  `release_date`, `last_updated`, `open_weights`, `display_name`.
- Provider-specific verbosity profiles live in `curation/verbosity-profiles.json`
  and must be grounded in provider API documentation. `provider_default` is the
  provider API default, not Agena's request preference. `reasoning_options`
  describes reasoning effort and must not be mapped to answer verbosity.
  Profiles are absent when support has no evidence.
- **Never add a model** that is not already in `models.json` (apply_patches.py
  rejects it).
- Thinking/speed modes must pass `scripts/apply_patches.py` shape checks and
  should be cross-checked against models.dev `reasoning_options` with
  `scripts/verify_thinking.py`.
- Patches run *after* `scripts/derive_thinking_modes.py`, which materialises
  `thinking_modes` from the trusted record's `reasoning_options`. Write a patch
  when the trusted record is missing, when it only advertises a `toggle` or
  `budget_tokens` option that needs a vendor-specific request encoding, or when
  a gateway variant ID has no trusted record of its own.
- `scripts/derive_speed_modes.py` runs right after it and materialises
  `speed_modes` from the trusted record's `experimental.modes`, always adding the
  `standard` entry (display name `Default`, no override) plus the `default`
  pointer. Patch speed modes when the vendor documents a tier the record does
  not publish, and name the concrete adapter (`openai_responses`, ...) in
  `adapter_overrides`.

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
3. Run `bash scripts/refresh.sh --no-fetch` to derive + apply + validate + verify + report.
4. Cross-check thinking modes: `python3 scripts/verify_thinking.py curation/patches/<name>.json`.
5. Commit with a message describing the change set, e.g.
   `chore(catalog): add thinking modes for <family>`.
