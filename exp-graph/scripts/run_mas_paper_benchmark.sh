#!/usr/bin/env bash
set -euo pipefail

# One-command MAS paper benchmark pipeline:
# train topology evidence -> collect -> batch insights -> evolve skills
# -> held-out test fixed/v0/v1 -> collect -> benchmark report.

ROOT="${ROOT:-/Users/robintian/AI/Agent-Expretional-Graph}"
REPO="${REPO:-$ROOT/exp-graph}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
SKILL_DIR="${SKILL_DIR:-$REPO/configs/mas_skills}"

LLM_PROVIDER="${LLM_PROVIDER:-openai}"
MODEL_NAME="${MODEL_NAME:-gpt-4o-mini}"
MERGE_MODE="${MERGE_MODE:-llm_full_merge}"
INIT_MODE="${INIT_MODE:-llm_local_solve}"

OBJECTIVES="${OBJECTIVES:-accuracy_first,budget_first,balanced}"
TOPOLOGIES="${TOPOLOGIES:-tree,one_peer_exponential_dag_star,mesh_star}"
N_AGENTS="${N_AGENTS:-4,8}"
ARRAY_SIZES="${ARRAY_SIZES:-32,64}"
TRAIN_SEEDS="${TRAIN_SEEDS:-1,2,3,4,5}"
TEST_SEEDS="${TEST_SEEDS:-9,10,11,12,13}"

MAX_PARALLEL_RUNS="${MAX_PARALLEL_RUNS:-1}"
MAX_PARALLEL_AGENTS="${MAX_PARALLEL_AGENTS:-2}"
MAX_PARALLEL_MINISTERS="${MAX_PARALLEL_MINISTERS:-2}"
MAX_PARALLEL_INSIGHT_SHARDS="${MAX_PARALLEL_INSIGHT_SHARDS:-2}"
VERBOSE_EVENTS="${VERBOSE_EVENTS:-0}"

TRAIN_DIR="${TRAIN_DIR:-$ROOT/cf_mas_train_paper_v0}"
TEST_FIXED_DIR="${TEST_FIXED_DIR:-$ROOT/cf_mas_test_fixed}"
TEST_V0_DIR="${TEST_V0_DIR:-$ROOT/cf_mas_test_v0}"
TEST_V1_DIR="${TEST_V1_DIR:-$ROOT/cf_mas_test_v1}"
BENCHMARK_DIR="${BENCHMARK_DIR:-$ROOT/cf_mas_paper_benchmark_report}"
EVOLVED_SKILL_DIR="${EVOLVED_SKILL_DIR:-/private/tmp/mas_skills_paper_v1}"
EVOLVED_SKILL_MD_DIR="${EVOLVED_SKILL_MD_DIR:-/private/tmp/mas_skills_paper_v1_md}"

if [[ "${CONFIRM_REAL_LLM:-}" != "YES" && "$LLM_PROVIDER" == "openai" ]]; then
  cat <<'EOF'
This pipeline launches the full paper-scale real-LLM benchmark.
Default size is roughly 540 OpenAI jobs:
  train topology sweep: 180
  test fixed topology: 180
  test frozen skillbank + llm_free: 120
  test evolved skillbank: 60

Run it explicitly with:
  CONFIRM_REAL_LLM=YES scripts/run_mas_paper_benchmark.sh

For a cheap wiring test, use:
  LLM_PROVIDER=fake MODEL_NAME=fake scripts/run_mas_paper_benchmark.sh
EOF
  exit 2
fi

cd "$REPO"

VERBOSE_ARGS=()
if [[ "$VERBOSE_EVENTS" == "1" || "$VERBOSE_EVENTS" == "true" || "$VERBOSE_EVENTS" == "YES" ]]; then
  VERBOSE_ARGS=(--verbose-events)
fi

run_cli() {
  PYTHONPATH=src "$PYTHON_BIN" -m exp_graph.mas.cli "$@"
}

collect_dir() {
  local matrix_dir="$1"
  run_cli collect-matrix \
    --matrix-dir "$matrix_dir" \
    --output-dir "$matrix_dir/collected"
}

prepare_evolved_skill_dir() {
  local stamp
  stamp="$(date +%Y%m%d_%H%M%S)"
  if [[ -d "$EVOLVED_SKILL_DIR" ]]; then
    mv "$EVOLVED_SKILL_DIR" "${EVOLVED_SKILL_DIR}_backup_$stamp"
  fi
  if [[ -d "$EVOLVED_SKILL_MD_DIR" ]]; then
    mv "$EVOLVED_SKILL_MD_DIR" "${EVOLVED_SKILL_MD_DIR}_backup_$stamp"
  fi
  cp -R "$SKILL_DIR" "$EVOLVED_SKILL_DIR"
}

echo "[1/10] train topology evidence -> $TRAIN_DIR"
run_cli run-matrix \
  --skill-dir "$SKILL_DIR" \
  --objectives "$OBJECTIVES" \
  --planner-modes operator_compose \
  --planner-policies topology_sweep \
  --topologies "$TOPOLOGIES" \
  --n-agents "$N_AGENTS" \
  --array-sizes "$ARRAY_SIZES" \
  --seeds "$TRAIN_SEEDS" \
  --llm-provider "$LLM_PROVIDER" \
  --model-name "$MODEL_NAME" \
  --merge-mode "$MERGE_MODE" \
  --init-mode "$INIT_MODE" \
  --trace \
  --retain-traces \
  "${VERBOSE_ARGS[@]}" \
  --max-parallel-runs "$MAX_PARALLEL_RUNS" \
  --max-parallel-agents "$MAX_PARALLEL_AGENTS" \
  --max-parallel-ministers "$MAX_PARALLEL_MINISTERS" \
  --output-dir "$TRAIN_DIR"

echo "[2/10] collect train"
collect_dir "$TRAIN_DIR"

echo "[3/10] analyze train batch insights"
run_cli analyze-insights \
  --skill-dir "$SKILL_DIR" \
  --evidence-file "$TRAIN_DIR/collected/batch_evidence.jsonl" \
  --summary-file "$TRAIN_DIR/collected/cross_seed_metrics.json" \
  --trace-summary-file "$TRAIN_DIR/collected/cross_seed_trace_summary.json" \
  --llm-provider "$LLM_PROVIDER" \
  --model-name "$MODEL_NAME" \
  --max-parallel-insight-shards "$MAX_PARALLEL_INSIGHT_SHARDS" \
  --output-dir "$TRAIN_DIR/insights"

echo "[4/10] evolve temporary skillbank -> $EVOLVED_SKILL_DIR"
prepare_evolved_skill_dir
run_cli evolve-skills \
  --skill-dir "$EVOLVED_SKILL_DIR" \
  --evidence-file "$TRAIN_DIR/collected/batch_evidence.jsonl" \
  --patch-dir "$TRAIN_DIR/collected/batch_patches" \
  --backup \
  --markdown-dir "$EVOLVED_SKILL_MD_DIR"

echo "[5/10] test fixed topology baselines -> $TEST_FIXED_DIR"
run_cli eval-matrix \
  --skill-dir "$SKILL_DIR" \
  --phase test \
  --objectives "$OBJECTIVES" \
  --planner-modes operator_compose \
  --planner-policies fixed_topology \
  --topologies "$TOPOLOGIES" \
  --n-agents "$N_AGENTS" \
  --array-sizes "$ARRAY_SIZES" \
  --seeds "$TEST_SEEDS" \
  --llm-provider "$LLM_PROVIDER" \
  --model-name "$MODEL_NAME" \
  --merge-mode "$MERGE_MODE" \
  --init-mode "$INIT_MODE" \
  --trace \
  --retain-traces \
  "${VERBOSE_ARGS[@]}" \
  --max-parallel-runs "$MAX_PARALLEL_RUNS" \
  --max-parallel-agents "$MAX_PARALLEL_AGENTS" \
  --max-parallel-ministers "$MAX_PARALLEL_MINISTERS" \
  --output-dir "$TEST_FIXED_DIR"

echo "[6/10] test frozen skillbank v0 + llm_free -> $TEST_V0_DIR"
run_cli eval-matrix \
  --skill-dir "$SKILL_DIR" \
  --phase test \
  --objectives "$OBJECTIVES" \
  --planner-modes operator_compose \
  --planner-policies skill_grounded,llm_free \
  --topologies "$TOPOLOGIES" \
  --n-agents "$N_AGENTS" \
  --array-sizes "$ARRAY_SIZES" \
  --seeds "$TEST_SEEDS" \
  --llm-provider "$LLM_PROVIDER" \
  --model-name "$MODEL_NAME" \
  --merge-mode "$MERGE_MODE" \
  --init-mode "$INIT_MODE" \
  --trace \
  --retain-traces \
  "${VERBOSE_ARGS[@]}" \
  --max-parallel-runs "$MAX_PARALLEL_RUNS" \
  --max-parallel-agents "$MAX_PARALLEL_AGENTS" \
  --max-parallel-ministers "$MAX_PARALLEL_MINISTERS" \
  --output-dir "$TEST_V0_DIR"

echo "[7/10] test evolved skillbank v1 -> $TEST_V1_DIR"
run_cli eval-matrix \
  --skill-dir "$EVOLVED_SKILL_DIR" \
  --phase test \
  --objectives "$OBJECTIVES" \
  --planner-modes operator_compose \
  --planner-policies skill_grounded \
  --topologies "$TOPOLOGIES" \
  --n-agents "$N_AGENTS" \
  --array-sizes "$ARRAY_SIZES" \
  --seeds "$TEST_SEEDS" \
  --llm-provider "$LLM_PROVIDER" \
  --model-name "$MODEL_NAME" \
  --merge-mode "$MERGE_MODE" \
  --init-mode "$INIT_MODE" \
  --trace \
  --retain-traces \
  "${VERBOSE_ARGS[@]}" \
  --max-parallel-runs "$MAX_PARALLEL_RUNS" \
  --max-parallel-agents "$MAX_PARALLEL_AGENTS" \
  --max-parallel-ministers "$MAX_PARALLEL_MINISTERS" \
  --output-dir "$TEST_V1_DIR"

echo "[8/10] collect held-out tests"
collect_dir "$TEST_FIXED_DIR"
collect_dir "$TEST_V0_DIR"
collect_dir "$TEST_V1_DIR"

echo "[9/10] build benchmark report -> $BENCHMARK_DIR"
run_cli benchmark-report \
  --fixed-collected-dir "$TEST_FIXED_DIR/collected" \
  --v0-collected-dir "$TEST_V0_DIR/collected" \
  --v1-collected-dir "$TEST_V1_DIR/collected" \
  --output-dir "$BENCHMARK_DIR"

echo "[10/10] done"
echo "Benchmark report:"
echo "  $BENCHMARK_DIR/benchmark_report.md"
echo
sed -n '1,220p' "$BENCHMARK_DIR/benchmark_report.md"
