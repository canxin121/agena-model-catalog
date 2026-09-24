# Agena Model Catalog

Self-maintained model catalog for the [Agena](https://github.com/canxin121/agena) LLM runtime.

`models.json` is the canonical generated source of model metadata. A daily GitHub
Actions refresh fetches `models.dev`, discovers new models from trusted first-party
providers and official Hugging Face organizations, updates trusted metadata, applies
curated exceptions and route limits, validates the result, and publishes changes. The Agena runtime
fetches this file at startup instead of crawling registries at runtime.

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

`.github/workflows/refresh-models.yml` runs the refresh daily and can also be
started manually. The workflow commits `models.json` when the validated output
changes. Adding a new model from an already trusted source requires no model ID
entry or catalog edit. A new provider or official Hugging Face organization is
admitted once in `curation/sources.json`; provider-specific gateway aliases and
third-party finetunes are excluded by the source policy. A refresh never removes
existing models automatically, since older IDs may still be used by consumers.

Existing IDs are preserved. For models from a trusted source, each field that
source provides is refreshed; missing source fields keep their catalog value.
Verified exceptions belong in `curation/patches/`, which run after the source
merge. For older models without a trusted source, the merge only fills gaps.

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
  sources.json       trusted provider and official organization policy
  patches/           hand-verified metadata patches applied over the base
  README.md          patch conventions and how to add one
docs/research/       per-vendor verification documents (domestic families)
scripts/
  refresh.sh         end-to-end refresh: fetch → discover → merge → curate → route caps → backfill → validate → report
  model_sources.py   canonicalize and select trusted upstream records
  seed_modelsdev.py  add newly discovered canonical model ids
  publish.sh         validate + commit + push (the release gate)
  fetch_modelsdev.sh snapshot models.dev into .cache/
  merge_modelsdev.py sync trusted fields and fill legacy gaps from the snapshot
  apply_patches.py   apply curation/patches onto models.json
  apply_route_limits.py cap shared context and output by configured route limits
  backfill_input.py  conservative max_input_tokens backfill
  validate.py        full-document schema validation (publish gate)
  verify_thinking.py cross-check thinking patches against models.dev reasoning_options
  report.py          coverage report
```

The data pipeline is **fetch → discover → merge → curate → route caps → verify**:

1. **fetch** — `fetch_modelsdev.sh` snapshots `models.dev/api.json` into
   `.cache/` (not committed; reproducible).
2. **discover** — `model_sources.py` selects first-party provider records and
   models from official Hugging Face organizations according to `curation/sources.json`.
   `seed_modelsdev.py` adds every new canonical ID from those sources. Source order
   resolves duplicate IDs, and a large unexpected influx stops the refresh for review.
3. **merge** — `merge_modelsdev.py` updates fields explicitly supplied by a
   trusted source, including limits, prices, descriptions, and capabilities.
   Price components omitted by the source are preserved; legacy price tiers
   without a unique threshold are discarded. Older models without a trusted
   source only receive missing fields from exact-ID matches.
4. **curate** — `apply_patches.py` merges `curation/patches/*.json` over the
   merged base. Curated values win (they were verified against official
   sources); `null` in a patch deletes a key.
5. **route caps** — `apply_route_limits.py` takes the lower of the trusted
   source's context and output limits and each configured route's corresponding
   limits for the same canonical model. Route providers cannot introduce new
   model IDs. This keeps shared limits safe for routes such as Cline Pass.
6. **verify** — `validate.py` enforces the catalog schema before anything is
   committed. `verify_thinking.py` is a separate advisory audit of existing
   thinking-mode patches against models.dev `reasoning_options`; it is not the
   automated publish gate because upstream reasoning records are incomplete.

### Refreshing the catalog

```bash
bash scripts/refresh.sh            # fetch + discover + merge + curate + route caps + validate
bash scripts/refresh.sh --no-fetch # reuse an existing .cache snapshot
bash scripts/publish.sh "chore(catalog): ..."   # validate, commit, push
```

See `curation/README.md` for the patch conventions.
