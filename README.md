# Agena Model Catalog

[![Refresh model catalog](https://github.com/canxin121/agena-model-catalog/actions/workflows/refresh-models.yml/badge.svg)](https://github.com/canxin121/agena-model-catalog/actions/workflows/refresh-models.yml)

Self-maintained model catalog for the [Agena](https://github.com/canxin121/agena) LLM runtime.

`models.json` is the canonical generated source of model metadata. A GitHub
Actions refresh runs every six hours. It fetches `models.dev`, discovers new models
from trusted first-party providers and official Hugging Face organizations, updates
trusted metadata, derives thinking modes from the trusted reasoning options, applies
curated exceptions and route limits, validates the result, and publishes changes. The
Agena runtime fetches this file at startup instead of crawling registries at runtime,
and it reads thinking modes from this file instead of inferring them per vendor family.

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

This file is the only source of thinking modes: the Agena runtime does not infer
OpenAI / Anthropic / Gemini family ladders from model IDs any more. Every mode a model
can offer is declared here, and a model whose entry has no `thinking_modes` shows no
thinking selector.

`scripts/derive_thinking_modes.py` fills the gap for entries that declare `reasoning`
but have no curated modes yet, using the **trusted first-party record only**:

- each published `effort` value becomes an effort mode, `none` becomes the disabled
  `off` mode; the order of the source is preserved;
- `toggle` and `budget_tokens` options are not derived, because they need a
  vendor-specific request encoding — those stay in `curation/patches/`;
- an entry that already declares `thinking_modes` is never modified, and no `default`
  key is invented (models.dev publishes none).

So a model such as `gpt-6.1-sol` gets exactly the effort values OpenAI publishes
(`low`, `medium`, `high`, `xhigh`, `max`) and nothing else — no invented `off`/
`minimal`, no missing `max`.

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

Like thinking modes, speed modes come from this file only: the runtime sends
exactly what a mode declares and never invents a tier. `scripts/derive_speed_modes.py`
materialises them from the trusted record's `experimental.modes` when an entry has
none yet:

- `{"service_tier": ...}` becomes a request body patch (accepted by both the
  Responses and the Chat Completions API);
- `{"speed": "fast"}` from Anthropic also carries the documented
  `anthropic-beta: fast-mode-2026-02-01` header;
- `{"reasoning": {"mode": ...}}` becomes an `openai_responses` adapter override,
  because `reasoning.mode` is Responses-only;
- any other shape (for example Bedrock's `additionalModelRequestFields`) is
  skipped and reported for curation.

`adapter_overrides` keys must be the adapter ids a provider route really uses
(`openai_responses`, `openai_chat_completions`); a plain `openai` key is still
accepted by the runtime as an alias for those two, but new data should name the
concrete adapter.

Exactly one entry of every `speed_modes` map is `standard`
(`{ "display_name": "Default" }`, no override) and the `default` pointer names it, so
the selector can always express "send no speed tier". Selecting it changes nothing on
the wire; the provider keeps its native default.

## Updating

`.github/workflows/refresh-models.yml` runs the refresh four times a day and can also be
started manually from **Actions → Refresh model catalog → Run workflow** on
`main`. Its schedule is **05:17, 11:17, 17:17, and 23:17 UTC+8**, every six hours
(cron `17 3,9,15,21 * * *` in UTC); GitHub may delay the actual start.
Changes to the workflow, scripts, or curation on `main` also trigger
a refresh. The workflow uses the built-in `GITHUB_TOKEN` with `contents: write`,
so no API keys or additional secrets are required.

The workflow commits and pushes `models.json` to `main` only when the validated
output changes. An unchanged catalog is a successful refresh and produces no
commit. Every run includes a summary with the publication result and pipeline
log. Downloads have bounded retries and timeouts; a failed refresh never reaches
the publish step. GitHub refreshes the remote catalog; use `git pull --ff-only`
to bring those changes into a local checkout.

Adding a new model from an already trusted source requires no model ID
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
- Thinking modes come from the trusted record's `reasoning_options` (derived) or from
  a curated patch; the runtime adds nothing on its own. Speed modes always require
  per-vendor verification against official API docs.
- A model that a gateway serves under a variant ID without its own trusted record
  (for example `deepseek-v4-flash:thinking`) needs a curated patch when it should
  offer a thinking selector.
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
  refresh.sh         end-to-end refresh: fetch → discover → merge → derive modes → curate → route caps → backfill → validate → verify → report
  model_sources.py   canonicalize and select trusted upstream records
  seed_modelsdev.py  add newly discovered canonical model ids
  publish.sh         validate + commit + push (the release gate)
  fetch_modelsdev.sh snapshot models.dev into .cache/
  merge_modelsdev.py sync trusted fields and fill legacy gaps from the snapshot
  derive_thinking_modes.py materialise thinking modes from trusted reasoning_options
  derive_speed_modes.py materialise speed modes from trusted experimental.modes
  apply_patches.py   apply curation/patches onto models.json
  apply_route_limits.py cap shared context and output by configured route limits
  backfill_input.py  conservative max_input_tokens backfill
  validate.py        full-document schema validation (publish gate)
  verify_thinking.py cross-check thinking modes against the trusted first-party records
  report.py          coverage report
```

The data pipeline is **fetch → discover → merge → derive thinking → derive speed → curate → route caps → validate → verify**:

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
4. **derive thinking** — `derive_thinking_modes.py` materialises `thinking_modes`
   from the trusted record's `reasoning_options` for entries that declare
   `reasoning` and have no curated modes yet. Existing modes are never modified, so
   reruns are no-ops and curation always wins.
5. **derive speed** — `derive_speed_modes.py` materialises `speed_modes` from the
   trusted record's `experimental.modes`. It runs again after the patches with
   `--ensure-existing-only`, so entries whose modes come from a curated patch also
   receive the explicit `standard` entry and its `default` pointer.
6. **curate** — `apply_patches.py` merges `curation/patches/*.json` over the
   merged base. Curated values win (they were verified against official
   sources); `null` in a patch deletes a key.
7. **route caps** — `apply_route_limits.py` takes the lower of the trusted
   source's context and output limits and each configured route's corresponding
   limits for the same canonical model. Route providers cannot introduce new
   model IDs. This keeps shared limits safe for routes such as Cline Pass.
8. **verify** — `validate.py` enforces the catalog schema and `verify_thinking.py`
   cross-checks thinking modes against the trusted first-party records. A patch that
   declares an effort value the record does not publish, or that turns a read-only
   toggle into an effort ladder, fails the refresh. Patches for models without a
   trusted record and ladders wider than a gateway-shaped record are reported as
   advisories, and the catalog-vs-trusted comparison stays a report.

### Refreshing the catalog

```bash
bash scripts/refresh.sh            # fetch + discover + merge + derive think+speed + curate + route caps + validate + verify
bash scripts/refresh.sh --no-fetch # reuse an existing .cache snapshot
bash scripts/publish.sh "chore(catalog): ..."   # validate, commit, push
```

See `curation/README.md` for the patch conventions.
