#!/bin/bash
# One command to reproduce the evaluation. Arguments are passed to scripts/evaluate.py.
#   ./scripts/eval.sh                                             free: reference + baselines
#   ./scripts/eval.sh --model openai/gpt-6.1-sol --env-file .env   adds three agent runs per task
set -euo pipefail
cd "$(dirname "$0")/.."
poetry install --quiet
exec poetry run python scripts/evaluate.py "$@"
