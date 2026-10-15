#!/usr/bin/env bash
# Validate, then commit and push the catalog (models.json + any changed
# curation/docs/scripts). Usage: bash scripts/publish.sh "<message>"
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== validate ==="
python3 scripts/validate.py

if [[ ! -s .cache/models.dev.json ]]; then
  echo "missing .cache/models.dev.json; run the refresh pipeline before publishing" >&2
  exit 1
fi
echo "=== verify verbosity source retention ==="
python3 scripts/verify_verbosity.py
echo "=== verify multi-source record completeness ==="
python3 scripts/verify_source_artifacts.py

echo "=== stage + commit ==="
git add -A
if git diff --cached --quiet; then
  echo "nothing to commit"
  exit 0
fi
git commit -m "${1:-update models.json}"
echo "=== push ==="
git push origin main
echo "published $(git rev-parse --short HEAD)"
