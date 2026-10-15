#!/usr/bin/env bash
# Fetch every independent upstream in curation/upstreams.json. models.dev is
# required for canonical model fields; route and artifact sources are recorded
# independently and remain usable from their local cache if a later request fails.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 scripts/fetch_upstreams.py "$@"
