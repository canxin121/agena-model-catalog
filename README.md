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

## Updating

The catalog is updated by hand (or by a maintainer's script), then pushed here. Follow
the existing field conventions. When you remove a model that is truly gone, also check
that no consumer depends on it. Prefer keeping a `deprecated` lifecycle over deleting.

Recommended flow for a bulk refresh:

1. Generate a fresh candidate from the upstream aggregators
   (e.g. `models.dev/api.json`, vendor model pages, HuggingFace official lists).
2. Curate: normalize ids, merge aliases, keep the best source per model, assign origins.
3. Diff against `models.json`, review, and commit.

See `scripts/update.sh` for a skeleton.

## Consumers

- **Agena runtime** — fetches `https://raw.githubusercontent.com/canxin121/agena-model-catalog/main/models.json`
  when the public catalog is enabled (`AGENA_DISABLE_PUBLIC_MODEL_CATALOG_SOURCES` disables it).
- Everything is display-only metadata: limits, pricing, capabilities, thinking modes.

## License

MIT (same as the Agena repository).
