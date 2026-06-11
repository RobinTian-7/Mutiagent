#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO="${EXPERIMENT_REPO:-$SCRIPT_REPO}"
ROOT="${EXPERIMENT_ROOT:-$(cd "$REPO/.." && pwd)}"
SHARED_PYTHON_BIN="/Users/robintian/AI/Agent-Expretional-Graph/.venv/bin/python"

if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x "$REPO/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO/.venv/bin/python"
  elif [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT/.venv/bin/python"
  elif [[ -x "$SHARED_PYTHON_BIN" ]]; then
    PYTHON_BIN="$SHARED_PYTHON_BIN"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
  else
    echo "No Python executable found. Set PYTHON_BIN=/path/to/python." >&2
    exit 2
  fi
fi

: "${DASHSCOPE_API_KEY:?Set DASHSCOPE_API_KEY before running this experiment.}"
: "${DEEPSEEK_API_KEY:?Set DEEPSEEK_API_KEY before running this experiment.}"

label="${1:-soldier-bailian-qwen35-flash__emperor-minister-deepseek-v4-pro_selfevolve-only}"
out_root="$REPO/runs/bailian_soldier_qwen35_flash_deepseekapi_v4pro_selfevolve_only_localinit_2048_0to511_v2planner/$label"
default_role_llm_config="$REPO/configs/role_llm_profiles/deepseek_v4pro_bailian_qwen35_flash.json"
if [[ -n "${ROLE_LLM_CONFIG:-}" ]]; then
  role_llm_config="$ROLE_LLM_CONFIG"
else
  mkdir -p "$out_root"
  role_llm_config="$out_root/role_llm_profiles.json"
  cp "$default_role_llm_config" "$role_llm_config"
fi

command env \
  PYTHONUTF8=1 \
  PYTHONIOENCODING=utf-8 \
  LANG=en_US.UTF-8 \
  LC_ALL=en_US.UTF-8 \
  ROOT="$ROOT" \
  REPO="$REPO" \
  PYTHON_BIN="$PYTHON_BIN" \
  DASHSCOPE_API_KEY="$DASHSCOPE_API_KEY" \
  DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  OUT_ROOT="$out_root" \
  ROLE_LLM_CONFIG="$role_llm_config" \
  LLM_PROVIDER=fake \
  MODEL_NAME=fake \
  CONFIRM_REAL_LLM=YES \
  RUN_BASELINES=0 \
  RUN_EVOLUTION=1 \
  EVOLUTION_ITERS=5 \
  N_AGENTS=8 \
  ARRAY_SIZES=2048 \
  VALUE_MIN=0 \
  VALUE_MAX=511 \
  TRAIN_SEEDS=1,2,3,4 \
  EVAL_SEEDS=101,102,103,104 \
  MAX_PARALLEL_RUNS=4 \
  MAX_PARALLEL_AGENTS=4 \
  MAX_PARALLEL_MINISTERS=4 \
  MAX_PARALLEL_INSIGHT_SHARDS=4 \
  GRAPH_SEARCH_MODE=topk \
  NUM_GRAPH_CANDIDATES=1 \
  GRAPH_TOP_K=1 \
  GRAPH_VALIDATION_SEEDS= \
  GRAPH_CANDIDATE_SCORE_MODE=accuracy_max \
  GRAPH_MAX_STEPS=10 \
  GRAPH_MAX_MESSAGES=32 \
  GRAPH_MAX_RECEIVER_FAN_IN=5 \
  BEST_SO_FAR_MODE=on \
  SKILL_TOP_K_PER_CONDITION=3 \
  INIT_MODE=deterministic \
  "$REPO/scripts/run_mas_autoskill_free_dag_pipeline.sh"
