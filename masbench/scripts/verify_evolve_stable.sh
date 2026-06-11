#!/usr/bin/env bash
# Stable-dominance verification wrapper. Loads the API key from masbench/.env
# (gitignored, possibly a symlink to the main checkout) inside THIS process only.
# Extra args pass through, e.g.:
#   bash scripts/verify_evolve_stable.sh --evolved-mode graph_generate --rounds 3
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1          # -> masbench/

if [[ -f .env ]]; then
  set -a; source .env; set +a
fi
: "${OPENAI_API_KEY:?put OPENAI_API_KEY=sk-... into masbench/.env (gitignored), or export it}"

exec uv run --extra openai python scripts/verify_evolve_stable.py "$@"
