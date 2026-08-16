# Agena Model Catalog

Self-maintained model catalog for the [Agena](https://github.com/canxin121/agena) LLM runtime.

`models.json` is the canonical, hand-curated source of model metadata. The Agena runtime
fetches this file at startup instead of crawling external model registries at runtime.

## File

- **`models.json`** — a single JSON document:

  ```json
  {
    "models": {
      "gpt-4o": {
        "lifecycle": "active",
        "context_window_tokens": 128000,
        "max_output_tokens": 16384,
        "description": "...",
        "knowledge_cutoff": "2023-10-01",
        "open_weights": false,
        "supports_parallel_tool_calls": true,
        "output_modalities": ["text"],
        "pricing": {
          "input_usd_per_million_tokens": "2.50",
          "output_usd_per_million_tokens": "10.00",
          "cache_read_usd_per_million_tokens": "1.25",
          "cache_write_usd_per_million_tokens": "3.75"
        },
        "display_name": "GPT-4o",
        "origin": "OpenAI",
        "thinking_modes": {},
        "speed_modes": {},
        "input": { "supported": ["text", "image"] },
        "features": { "supported": ["tool_calling", "streaming", "temperature"] }
      }
    }
  }
  ```

  - Keys are **canonical model ids** as produced by `agena_provider::normalized_catalog_model_id`.
  - `origin` is the vendor display name (e.g. "OpenAI", "Anthropic", "Google", "DeepSeek").
  - `lifecycle` is one of `active | preview | beta | alpha | experimental | deprecated`.
  - All fields are optional and skipped when absent.

## Thinking modes (`thinking_modes`)

Optional map of mode key → mode definition. An optional `"default"` key names the mode
used when none is requested.

```json
"thinking_modes": {
  "default": "medium",
  "off":     { "display_name": "Off", "strategy": "disabled" },
  "low":     { "display_name": "Think Low", "strategy": "effort", "effort": "low" },
  "medium":  { "display_name": "Think Medium", "strategy": "effort", "effort": "medium" },
  "high":    { "display_name": "Think High", "strategy": "effort", "effort": "high" }
}
```

- `strategy` is one of `disabled | effort | budget | adaptive | request_only`.
  - `effort` — depth level: `minimal | low | medium | high | xhigh | max`.
  - `budget` — fixed reasoning token budget via `budget_tokens` (u32).
  - `request_only` — toggled by a request field, e.g. Qwen3 `enable_thinking`,
    DeepSeek/Kimi `thinking`, via `request_override.body_patch`.
- `request_override` / `adapter_overrides` add provider-specific request fields
  (headers and/or a nested `body_patch`), e.g.:
  `{"request_override": {"body_patch": {"enable_thinking": true}}}`.

## Speed modes (`speed_modes`)

Optional map of mode key → mode definition. Only present when the vendor actually
documents a speed tier (do not invent one).

```json
"speed_modes": {
  "fast": {
    "display_name": "Fast",
    "description": "1.5x speed, increased usage",
    "request_override": { "body_patch": { "service_tier": "priority" } },
    "adapter_overrides": { "openai": { "body_patch": { "service_tier": "priority" } } }
  }
}
```

Anthropic fast-mode example:
```json
"speed_modes": {
  "fast": {
    "display_name": "Fast",
    "request_override": {
      "headers": { "anthropic-beta": "fast-mode-2026-02-01" },
      "body_patch": { "speed": "fast" }
    }
  }
}
```

## Updating

The catalog is updated by hand (or by a maintainer's script), then pushed here. Follow
the existing field conventions. When you remove a model that is truly gone, also check
that no consumer depends on it. Prefer keeping a `deprecated` lifecycle over deleting.

Recommended flow for a bulk refresh:

1. Generate a fresh candidate from the upstream aggregators
   (e.g. `models.dev/api.json`, vendor model pages, HuggingFace official lists).
2. Curate: normalize ids, merge aliases, keep the best source per model, assign origins.
3. Diff against `models.json`, review, and commit.

Verification rules:

- **Never fabricate.** If a value cannot be verified from an official source
  (vendor docs, models.dev, HuggingFace model cards), omit the field — a missing
  field is always preferable to a wrong one.
- `models.dev` is the authoritative base for context/output limits, pricing,
  descriptions, knowledge cutoffs, and the `input`/`features` capability flags.
- Thinking modes and speed modes require per-vendor verification against official
  API docs; the runtime auto-enriches only the OpenAI (gpt-5/o1/o3/o4), Gemini,
  and Claude families — every other vendor's modes must be curated here.
- A model flagged `reasoning` but with no documented toggle (e.g. some
  Llama/Pixtral/Gemma entries) should NOT get thinking modes.

## Repository layout

```
models.json          canonical catalog (the runtime fetches this)
README.md            this file
curation/
  patches/           hand-verified metadata patches applied over the base
  README.md          patch conventions and how to add one
docs/research/       per-vendor verification documents (domestic families)
scripts/
  refresh.sh         end-to-end refresh: fetch → merge → apply → backfill → validate → report
  publish.sh         validate + commit + push (the release gate)
  fetch_modelsdev.sh snapshot models.dev into .cache/
  merge_modelsdev.py fill missing base fields from the models.dev snapshot
  apply_patches.py   apply curation/patches onto models.json
  backfill_input.py  conservative max_input_tokens backfill
  validate.py        full-document schema validation (publish gate)
  verify_thinking.py cross-check thinking patches against models.dev reasoning_options
  report.py          coverage report
```

The data pipeline is **fetch → merge → curate → verify**:

1. **fetch** — `fetch_modelsdev.sh` snapshots `models.dev/api.json` into
   `.cache/` (not committed; reproducible).
2. **merge** — `merge_modelsdev.py` fills missing base fields (limits, pricing,
   descriptions, knowledge cutoffs, input/features) from the snapshot, exact-id
   matches only, never overwriting an existing value.
3. **curate** — `apply_patches.py` merges `curation/patches/*.json` over the
   merged base. Curated values win (they were verified against official
   sources); `null` in a patch deletes a key.
4. **verify** — `verify_thinking.py` cross-checks thinking-mode patches against
   models.dev `reasoning_options` (mismatch = fabrication signal);
   `validate.py` enforces the full schema before anything is committed.

### Refreshing the catalog

```bash
bash scripts/refresh.sh            # fetch + merge + apply + backfill + validate + report
bash scripts/refresh.sh --no-fetch # reuse an existing .cache snapshot
bash scripts/publish.sh "chore(catalog): ..."   # validate, commit, push
```

See `curation/README.md` for the patch conventions.
