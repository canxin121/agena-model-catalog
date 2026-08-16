#!/usr/bin/env bash
# Validate, then commit and push the catalog (models.json + any changed
# curation/docs/scripts). Usage: bash scripts/publish.sh "<message>"
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== validate ==="
python3 scripts/validate.py

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
