#!/usr/bin/env bash
# Self-evolve verification wrapper. Loads the API key from masbench/.env
# (gitignored) inside THIS process only -- the key is never echoed, never put on
# a command line, and never needs to appear in chat. Extra args pass through,
# e.g.:  bash scripts/verify_evolve.sh --evolved-mode graph_generate
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1          # -> masbench/

if [[ -f .env ]]; then
  set -a; source .env; set +a
fi
: "${OPENAI_API_KEY:?put OPENAI_API_KEY=sk-... into masbench/.env (gitignored), or export it in your shell}"

exec uv run --extra openai python scripts/verify_evolve.py "$@"
