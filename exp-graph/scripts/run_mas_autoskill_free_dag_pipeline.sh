#!/usr/bin/env bash
set -euo pipefail

# One-command experiment pipeline for:
#   baselines vs. self-evolving MAS from an empty skill bank.
#
# Default mode runs the custom empty-skill free-DAG self-evolution loop:
#   1. fixed topology baselines
#   2. empty free-DAG baseline without learning
#   3. frozen hand-written skillbank free-DAG baseline
#   4. iterative train -> collect -> insight -> evolve -> held-out eval
#
# The existing LangGraph paper workflow is still available through:
#   PIPELINE_MODE=langgraph_paper scripts/run_mas_autoskill_free_dag_pipeline.sh
#
# Best-so-far elite retention is controlled by:
#   BEST_SO_FAR_MODE=on|off
# Legacy BEST_SO_FAR_ELITE=0|1 is still accepted when BEST_SO_FAR_MODE is unset.

ROOT="${ROOT:-/Users/robintian/AI/Agent-Expretional-Graph}"
REPO="${REPO:-$ROOT/exp-graph}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
HAND_SKILL_DIR="${HAND_SKILL_DIR:-$REPO/configs/mas_skills}"
OUT_ROOT="${OUT_ROOT:-$REPO/runs/cf_mas_autoskill_free_dag}"

PIPELINE_MODE="${PIPELINE_MODE:-autoskill_free_dag}"

LLM_PROVIDER="${LLM_PROVIDER:-openai}"
MODEL_NAME="${MODEL_NAME:-gpt-4o-mini}"
MERGE_MODE="${MERGE_MODE:-llm_full_merge}"
INIT_MODE="${INIT_MODE:-llm_local_solve}"
TEMPERATURE="${TEMPERATURE:-0.0}"
JSON_RETRY_ATTEMPTS="${JSON_RETRY_ATTEMPTS:-2}"

OBJECTIVES="${OBJECTIVES:-balanced}"
BASELINE_TOPOLOGIES="${BASELINE_TOPOLOGIES:-tree,one_peer_exponential_dag_star,mesh_star}"
N_AGENTS="${N_AGENTS:-4,8}"
ARRAY_SIZES="${ARRAY_SIZES:-32,64}"
TRAIN_SEEDS="${TRAIN_SEEDS:-1,2,3}"
EVAL_SEEDS="${EVAL_SEEDS:-101,102,103}"
EVOLUTION_ITERS="${EVOLUTION_ITERS:-2}"

MAX_PARALLEL_RUNS="${MAX_PARALLEL_RUNS:-1}"
MAX_PARALLEL_AGENTS="${MAX_PARALLEL_AGENTS:-2}"
MAX_PARALLEL_MINISTERS="${MAX_PARALLEL_MINISTERS:-2}"
MAX_PARALLEL_INSIGHT_SHARDS="${MAX_PARALLEL_INSIGHT_SHARDS:-2}"

TRACE="${TRACE:-1}"
RETAIN_TRACES="${RETAIN_TRACES:-1}"
VERBOSE_EVENTS="${VERBOSE_EVENTS:-1}"
RUN_BASELINES="${RUN_BASELINES:-1}"
RUN_EVOLUTION="${RUN_EVOLUTION:-1}"
if [[ -z "${BEST_SO_FAR_MODE:-}" ]]; then
  BEST_SO_FAR_MODE="${BEST_SO_FAR_ELITE:-on}"
fi
case "$BEST_SO_FAR_MODE" in
  1|true|TRUE|yes|YES|y|Y|on|ON|enabled|ENABLED)
    BEST_SO_FAR_MODE="on"
    BEST_SO_FAR_ELITE=1
    ;;
  0|false|FALSE|no|NO|n|N|off|OFF|disabled|DISABLED)
    BEST_SO_FAR_MODE="off"
    BEST_SO_FAR_ELITE=0
    ;;
  *)
    echo "Invalid BEST_SO_FAR_MODE=$BEST_SO_FAR_MODE. Use on or off." >&2
    exit 2
    ;;
esac
BEST_SKILLS_DIR="${BEST_SKILLS_DIR:-$OUT_ROOT/skills_best_so_far}"
BEST_SO_FAR_STATE="${BEST_SO_FAR_STATE:-$OUT_ROOT/best_so_far.json}"
SKILL_TOP_K_PER_CONDITION="${SKILL_TOP_K_PER_CONDITION:-3}"
SKILL_ARCHIVE_DIR="${SKILL_ARCHIVE_DIR:-$OUT_ROOT/skills_archive}"

GRAPH_SEARCH_MODE="${GRAPH_SEARCH_MODE:-topk}"
NUM_GRAPH_CANDIDATES="${NUM_GRAPH_CANDIDATES:-4}"
GRAPH_TOP_K="${GRAPH_TOP_K:-2}"
GRAPH_CANDIDATE_SCORE_MODE="${GRAPH_CANDIDATE_SCORE_MODE:-objective}"
GRAPH_MAX_STEPS="${GRAPH_MAX_STEPS:-4}"
GRAPH_MAX_MESSAGES="${GRAPH_MAX_MESSAGES:-32}"
GRAPH_MAX_RECEIVER_FAN_IN="${GRAPH_MAX_RECEIVER_FAN_IN:-4}"
GRAPH_REPAIR_ATTEMPTS="${GRAPH_REPAIR_ATTEMPTS:-1}"
GRAPH_VALIDATION_SEEDS="${GRAPH_VALIDATION_SEEDS:-}"

LANGGRAPH_OUTPUT_DIR="${LANGGRAPH_OUTPUT_DIR:-$OUT_ROOT/langgraph_paper_workflow}"
LANGGRAPH_CONFIG="${LANGGRAPH_CONFIG:-$REPO/configs/mas_workflows/paper_benchmark.json}"
LANGGRAPH_STOP_AFTER="${LANGGRAPH_STOP_AFTER:-}"
LANGGRAPH_DRY_RUN="${LANGGRAPH_DRY_RUN:-0}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python executable not found or not executable: $PYTHON_BIN" >&2
  echo "Set PYTHON_BIN=/path/to/python, usually $ROOT/.venv/bin/python" >&2
  exit 2
fi

if [[ "$LLM_PROVIDER" == "openai" && "${CONFIRM_REAL_LLM:-}" != "YES" ]]; then
  cat >&2 <<EOF
This launches real OpenAI-backed MAS experiments.

Set CONFIRM_REAL_LLM=YES when you intend to run it, for example:
  CONFIRM_REAL_LLM=YES scripts/run_mas_autoskill_free_dag_pipeline.sh

For a cheap wiring test:
  LLM_PROVIDER=fake MODEL_NAME=fake scripts/run_mas_autoskill_free_dag_pipeline.sh
EOF
  exit 2
fi

if [[ "$LLM_PROVIDER" == "openai" && -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is not set." >&2
  exit 2
fi

cd "$REPO"
mkdir -p "$OUT_ROOT"

run_cli() {
  PYTHONPATH=src "$PYTHON_BIN" -m exp_graph.mas.cli "$@"
}

truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|y|Y) return 0 ;;
    *) return 1 ;;
  esac
}

best_so_far_enabled() {
  [[ "$BEST_SO_FAR_MODE" == "on" ]]
}

trace_args=()
if truthy "$TRACE"; then
  trace_args+=(--trace)
fi
if truthy "$RETAIN_TRACES"; then
  trace_args+=(--retain-traces)
fi
if truthy "$VERBOSE_EVENTS"; then
  trace_args+=(--verbose-events)
fi

graph_args=(
  --graph-search-mode "$GRAPH_SEARCH_MODE"
  --num-graph-candidates "$NUM_GRAPH_CANDIDATES"
  --graph-top-k "$GRAPH_TOP_K"
  --graph-candidate-score-mode "$GRAPH_CANDIDATE_SCORE_MODE"
  --graph-max-steps "$GRAPH_MAX_STEPS"
  --graph-max-messages "$GRAPH_MAX_MESSAGES"
  --graph-max-receiver-fan-in "$GRAPH_MAX_RECEIVER_FAN_IN"
  --graph-repair-attempts "$GRAPH_REPAIR_ATTEMPTS"
  --graph-validation-seeds "$GRAPH_VALIDATION_SEEDS"
)

common_matrix_args=(
  --objectives "$OBJECTIVES"
  --n-agents "$N_AGENTS"
  --array-sizes "$ARRAY_SIZES"
  --llm-provider "$LLM_PROVIDER"
  --model-name "$MODEL_NAME"
  --merge-mode "$MERGE_MODE"
  --init-mode "$INIT_MODE"
)
if ((${#trace_args[@]} > 0)); then
  common_matrix_args+=("${trace_args[@]}")
fi
if ((${#graph_args[@]} > 0)); then
  common_matrix_args+=("${graph_args[@]}")
fi
common_matrix_args+=(
  --max-parallel-runs "$MAX_PARALLEL_RUNS"
  --max-parallel-agents "$MAX_PARALLEL_AGENTS"
  --max-parallel-ministers "$MAX_PARALLEL_MINISTERS"
)

collect_dir() {
  local matrix_dir="$1"
  run_cli collect-matrix \
    --matrix-dir "$matrix_dir" \
    --output-dir "$matrix_dir/collected"
}

run_eval_matrix() {
  local label="$1"
  local skill_dir="$2"
  local planner_modes="$3"
  local planner_policies="$4"
  local topologies="$5"
  local output_dir="$6"

  echo "[eval:$label] -> $output_dir"
  run_cli eval-matrix \
    --skill-dir "$skill_dir" \
    --phase test \
    --planner-modes "$planner_modes" \
    --planner-policies "$planner_policies" \
    --topologies "$topologies" \
    --seeds "$EVAL_SEEDS" \
    "${common_matrix_args[@]}" \
    --output-dir "$output_dir"
  collect_dir "$output_dir"
}

run_train_matrix() {
  local label="$1"
  local skill_dir="$2"
  local output_dir="$3"

  echo "[train:$label] -> $output_dir"
  run_cli run-matrix \
    --skill-dir "$skill_dir" \
    --planner-modes graph_generate \
    --planner-policies free_graph \
    --topologies "" \
    --seeds "$TRAIN_SEEDS" \
    "${common_matrix_args[@]}" \
    --output-dir "$output_dir"
  collect_dir "$output_dir"
}

analyze_insights() {
  local label="$1"
  local skill_dir="$2"
  local collected_dir="$3"
  local output_dir="$4"

  echo "[insights:$label] -> $output_dir"
  run_cli analyze-insights \
    --skill-dir "$skill_dir" \
    --evidence-file "$collected_dir/batch_evidence.jsonl" \
    --summary-file "$collected_dir/cross_seed_metrics.json" \
    --trace-summary-file "$collected_dir/cross_seed_trace_summary.json" \
    --llm-provider "$LLM_PROVIDER" \
    --model-name "$MODEL_NAME" \
    --max-parallel-insight-shards "$MAX_PARALLEL_INSIGHT_SHARDS" \
    --output-dir "$output_dir"
}

prepare_empty_skill_dir() {
  local path="$1"
  mkdir -p "$path"
  if [[ ! -f "$path/.empty_skill_bank" ]]; then
    printf 'empty skill bank for free-DAG self-evolution\n' > "$path/.empty_skill_bank"
  fi
}

prepare_next_skill_dir() {
  local current="$1"
  local next="$2"
  local marker="$3"

  if [[ -f "$next/$marker" ]]; then
    echo "[skills] existing evolved skill dir found, keeping: $next"
    return
  fi
  if [[ -e "$next" ]]; then
    local backup="${next}_backup_$(date +%Y%m%d_%H%M%S)"
    echo "[skills] moving existing $next -> $backup"
    mv "$next" "$backup"
  fi
  mkdir -p "$next"
  if compgen -G "$current/*.yaml" > /dev/null; then
    cp "$current"/*.yaml "$next"/
  fi
  printf 'pending evolution\n' > "$next/.evolution_pending"
}

copy_skill_dir() {
  local source="$1"
  local target="$2"
  local marker_text="$3"
  local tmp="${target}_tmp_$$"

  rm -rf "$tmp"
  mkdir -p "$tmp"
  if compgen -G "$source/*.yaml" > /dev/null; then
    cp "$source"/*.yaml "$tmp"/
  fi
  printf '%s\n' "$marker_text" > "$tmp/.elite_metadata"
  rm -rf "$target"
  mv "$tmp" "$target"
}

evolve_skills() {
  local label="$1"
  local skill_dir="$2"
  local collected_dir="$3"
  local markdown_dir="$4"
  local marker="$5"

  echo "[evolve:$label] -> $skill_dir"
  run_cli evolve-skills \
    --skill-dir "$skill_dir" \
    --evidence-file "$collected_dir/batch_evidence.jsonl" \
    --patch-dir "$collected_dir/batch_patches" \
    --backup \
    --markdown-dir "$markdown_dir" \
    --revision-dir "$OUT_ROOT/revisions"
  printf 'evolved from %s\n' "$label" > "$skill_dir/$marker"
  rm -f "$skill_dir/.evolution_pending"
}

elite_score_json() {
  local collected_dir="$1"
  local label="$2"

  PYTHONPATH=src "$PYTHON_BIN" - "$collected_dir" "$label" <<'PY'
import json
import sys
from pathlib import Path

collected = Path(sys.argv[1])
label = sys.argv[2]
path = collected / "cross_seed_metrics.json"
if not path.exists():
    raise SystemExit(f"missing cross-seed metrics: {path}")
data = json.loads(path.read_text(encoding="utf-8"))
conditions = [row for row in data.get("conditions", []) if isinstance(row, dict)]
if not conditions:
    raise SystemExit(f"no conditions in {path}")
rmse = [float(row.get("mean_rmse", 0.0) or 0.0) for row in conditions]
exact = [float(row.get("exact_match_rate", 0.0) or 0.0) for row in conditions]
tokens = [float(row.get("mean_token_cost", 0.0) or 0.0) for row in conditions]
mean_rmse = sum(rmse) / len(rmse)
payload = {
    "label": label,
    "score": mean_rmse,
    "score_metric": "mean_rmse",
    "score_lower_is_better": True,
    "condition_count": len(conditions),
    "mean_rmse": mean_rmse,
    "mean_exact_match_rate": sum(exact) / len(exact),
    "mean_token_cost": sum(tokens) / len(tokens),
}
print(json.dumps(payload, sort_keys=True))
PY
}

elite_decision() {
  local score_json="$1"
  local state_path="$2"

  PYTHONPATH=src "$PYTHON_BIN" - "$score_json" "$state_path" <<'PY'
import json
import sys
from pathlib import Path

current = json.loads(sys.argv[1])
state_path = Path(sys.argv[2])
if not state_path.exists():
    print("promote")
    raise SystemExit(0)
best = json.loads(state_path.read_text(encoding="utf-8"))
current_rmse = float(current["mean_rmse"])
best_rmse = float(best.get("mean_rmse", best.get("score", float("inf"))))
if current_rmse < best_rmse - 1e-12:
    print("promote")
else:
    print("retain")
PY
}

write_best_state() {
  local score_json="$1"
  local skill_dir="$2"
  local eval_dir="$3"

  PYTHONPATH=src "$PYTHON_BIN" - "$BEST_SO_FAR_STATE" "$score_json" "$skill_dir" "$eval_dir" "$BEST_SKILLS_DIR" <<'PY'
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

state_path = Path(sys.argv[1])
payload = json.loads(sys.argv[2])
payload.update(
    {
        "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "source_skill_dir": sys.argv[3],
        "source_eval_dir": sys.argv[4],
        "best_skill_dir": sys.argv[5],
    }
)
state_path.parent.mkdir(parents=True, exist_ok=True)
state_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

promote_best_so_far() {
  local label="$1"
  local skill_dir="$2"
  local eval_dir="$3"
  local score_json="$4"
  local best_eval_dir="$OUT_ROOT/evolution/best_so_far_eval"
  local archive_dir="$SKILL_ARCHIVE_DIR/$label"

  echo "[elite:$label] compact/promote -> $BEST_SKILLS_DIR"
  run_cli compact-skills \
    --skill-dir "$skill_dir" \
    --output-dir "$BEST_SKILLS_DIR" \
    --archive-dir "$archive_dir" \
    --max-per-condition "$SKILL_TOP_K_PER_CONDITION"
  printf 'best-so-far elite promoted from %s\n' "$label" > "$BEST_SKILLS_DIR/.best_so_far"
  rm -rf "$best_eval_dir"
  mkdir -p "$best_eval_dir"
  if [[ -d "$eval_dir/collected" ]]; then
    cp -R "$eval_dir/collected" "$best_eval_dir/collected"
  fi
  write_best_state "$score_json" "$skill_dir" "$eval_dir"
}

apply_best_so_far_elite() {
  local label="$1"
  local candidate_skills="$2"
  local eval_dir="$3"

  if ! best_so_far_enabled; then
    EVOLUTION_CURRENT_SKILLS="$candidate_skills"
    return
  fi

  local score_json
  score_json="$(elite_score_json "$eval_dir/collected" "$label")"
  local decision
  decision="$(elite_decision "$score_json" "$BEST_SO_FAR_STATE")"
  echo "[elite:$label] score=$score_json decision=$decision"
  if [[ "$decision" == "promote" ]]; then
    promote_best_so_far "$label" "$candidate_skills" "$eval_dir" "$score_json"
  else
    echo "[elite:$label] retain existing best -> $BEST_SKILLS_DIR"
  fi

  if [[ -d "$BEST_SKILLS_DIR" ]]; then
    EVOLUTION_CURRENT_SKILLS="$BEST_SKILLS_DIR"
  else
    EVOLUTION_CURRENT_SKILLS="$candidate_skills"
  fi
}

write_comparison_report() {
  PYTHONPATH=src "$PYTHON_BIN" - "$OUT_ROOT" "$EVOLUTION_ITERS" "$BEST_SO_FAR_MODE" <<'PY'
import csv
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
iters = int(sys.argv[2])
best_so_far_mode = sys.argv[3]
rows = []

sources = [
    ("baseline_fixed_topology", root / "baselines" / "fixed_topology" / "collected"),
    ("baseline_empty_free_dag", root / "baselines" / "empty_free_dag" / "collected"),
    ("baseline_frozen_skillbank_free_dag", root / "baselines" / "frozen_skillbank_free_dag" / "collected"),
    ("baseline_frozen_skill_grounded", root / "baselines" / "frozen_skill_grounded" / "collected"),
]
for i in range(iters):
    sources.append((f"self_evolved_free_dag_iter_{i + 1}", root / "evolution" / f"iter_{i}_eval" / "collected"))
if best_so_far_mode == "on":
    sources.append(("self_evolved_free_dag_best_so_far", root / "evolution" / "best_so_far_eval" / "collected"))

for method, collected in sources:
    path = collected / "cross_seed_metrics.json"
    if not path.exists():
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    for condition in data.get("conditions", []):
        row = {"method": method, **condition}
        rows.append(row)

report_dir = root / "reports"
report_dir.mkdir(parents=True, exist_ok=True)
json_path = report_dir / "autoskill_comparison.json"
csv_path = report_dir / "autoskill_comparison.csv"
md_path = report_dir / "autoskill_comparison.md"
json_path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")

fieldnames = sorted({key for row in rows for key in row})
with csv_path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

summary_fields = [
    "method",
    "objective",
    "planner_policy",
    "topology_name",
    "n_agents",
    "array_size",
    "run_count",
    "mean_rmse",
    "std_rmse",
    "exact_match_rate",
    "mean_messages",
    "mean_model_calls",
    "mean_token_cost",
    "fallback_rate",
]
lines = [
    "# AutoSkill Free-DAG MAS Comparison",
    "",
    f"- root: `{root}`",
    f"- rows: `{len(rows)}`",
    "",
    "| " + " | ".join(summary_fields) + " |",
    "| " + " | ".join("---" for _ in summary_fields) + " |",
]
for row in sorted(rows, key=lambda item: (
    str(item.get("method", "")),
    int(item.get("n_agents", 0)),
    int(item.get("array_size", 0)),
    str(item.get("topology_name", "")),
)):
    values = []
    for field in summary_fields:
        value = row.get(field, "")
        if isinstance(value, float):
            value = f"{value:.6g}"
        values.append(str(value))
    lines.append("| " + " | ".join(values) + " |")
md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

print(f"[report] {md_path}")
print(f"[report] {csv_path}")
PY
}

run_langgraph_paper_workflow() {
  local -a workflow_args
  workflow_args=(
    run-workflow
    --workflow-backend langgraph
    --workflow-config "$LANGGRAPH_CONFIG"
    --repo-dir "$REPO"
    --python-bin "$PYTHON_BIN"
    --skill-dir "$HAND_SKILL_DIR"
    --output-dir "$LANGGRAPH_OUTPUT_DIR"
    --objectives "$OBJECTIVES"
    --topologies "$BASELINE_TOPOLOGIES"
    --n-agents "$N_AGENTS"
    --array-sizes "$ARRAY_SIZES"
    --train-seeds "$TRAIN_SEEDS"
    --test-seeds "$EVAL_SEEDS"
    --llm-provider "$LLM_PROVIDER"
    --model-name "$MODEL_NAME"
    --merge-mode "$MERGE_MODE"
    --init-mode "$INIT_MODE"
    --max-parallel-runs "$MAX_PARALLEL_RUNS"
    --max-parallel-agents "$MAX_PARALLEL_AGENTS"
    --max-parallel-ministers "$MAX_PARALLEL_MINISTERS"
    --max-parallel-insight-shards "$MAX_PARALLEL_INSIGHT_SHARDS"
    --graph-search-mode "$GRAPH_SEARCH_MODE"
    --num-graph-candidates "$NUM_GRAPH_CANDIDATES"
    --graph-top-k "$GRAPH_TOP_K"
    --graph-candidate-score-mode "$GRAPH_CANDIDATE_SCORE_MODE"
    --graph-max-steps "$GRAPH_MAX_STEPS"
    --graph-max-messages "$GRAPH_MAX_MESSAGES"
    --graph-max-receiver-fan-in "$GRAPH_MAX_RECEIVER_FAN_IN"
    --graph-repair-attempts "$GRAPH_REPAIR_ATTEMPTS"
    --graph-validation-seeds "$GRAPH_VALIDATION_SEEDS"
    --debug
    --inspect-artifacts
    --confirm-real-llm
  )
  if truthy "$LANGGRAPH_DRY_RUN"; then
    workflow_args+=(--dry-run)
  fi
  if [[ -n "$LANGGRAPH_STOP_AFTER" ]]; then
    workflow_args+=(--stop-after "$LANGGRAPH_STOP_AFTER")
  fi

  echo "[langgraph-paper] -> $LANGGRAPH_OUTPUT_DIR"
  run_cli "${workflow_args[@]}"
}

if [[ "$PIPELINE_MODE" == "langgraph_paper" ]]; then
  run_langgraph_paper_workflow
  exit 0
fi

if [[ "$PIPELINE_MODE" != "autoskill_free_dag" ]]; then
  echo "Unknown PIPELINE_MODE=$PIPELINE_MODE" >&2
  echo "Use autoskill_free_dag or langgraph_paper." >&2
  exit 2
fi

EMPTY_SKILLS="$OUT_ROOT/skills_iter_0"
prepare_empty_skill_dir "$EMPTY_SKILLS"

echo "[config]"
echo "  out_root: $OUT_ROOT"
echo "  provider: $LLM_PROVIDER"
echo "  model: $MODEL_NAME"
echo "  objectives: $OBJECTIVES"
echo "  n_agents: $N_AGENTS"
echo "  array_sizes: $ARRAY_SIZES"
echo "  train_seeds: $TRAIN_SEEDS"
echo "  eval_seeds: $EVAL_SEEDS"
echo "  evolution_iters: $EVOLUTION_ITERS"
echo "  best_so_far_mode: $BEST_SO_FAR_MODE"
echo "  best_skills_dir: $BEST_SKILLS_DIR"
echo "  skill_top_k_per_condition: $SKILL_TOP_K_PER_CONDITION"
echo "  skill_archive_dir: $SKILL_ARCHIVE_DIR"

if truthy "$RUN_BASELINES"; then
  run_eval_matrix \
    "fixed_topology" \
    "$HAND_SKILL_DIR" \
    "operator_compose" \
    "fixed_topology" \
    "$BASELINE_TOPOLOGIES" \
    "$OUT_ROOT/baselines/fixed_topology"

  run_eval_matrix \
    "empty_free_dag" \
    "$EMPTY_SKILLS" \
    "graph_generate" \
    "free_graph" \
    "" \
    "$OUT_ROOT/baselines/empty_free_dag"

  run_eval_matrix \
    "frozen_skillbank_free_dag" \
    "$HAND_SKILL_DIR" \
    "graph_generate" \
    "free_graph" \
    "" \
    "$OUT_ROOT/baselines/frozen_skillbank_free_dag"

  run_eval_matrix \
    "frozen_skill_grounded" \
    "$HAND_SKILL_DIR" \
    "operator_compose" \
    "skill_grounded,llm_free" \
    "$BASELINE_TOPOLOGIES" \
    "$OUT_ROOT/baselines/frozen_skill_grounded"
fi

if truthy "$RUN_EVOLUTION"; then
  EVOLUTION_CURRENT_SKILLS="$EMPTY_SKILLS"
  if best_so_far_enabled && [[ -f "$BEST_SO_FAR_STATE" && -d "$BEST_SKILLS_DIR" ]]; then
    EVOLUTION_CURRENT_SKILLS="$BEST_SKILLS_DIR"
    echo "[elite] resuming from existing best-so-far: $BEST_SKILLS_DIR"
  fi
  for ((iter = 0; iter < EVOLUTION_ITERS; iter++)); do
    current_skills="$EVOLUTION_CURRENT_SKILLS"
    next_skills="$OUT_ROOT/skills_iter_$((iter + 1))"
    marker=".evolved_from_iter_$iter"
    train_dir="$OUT_ROOT/evolution/iter_${iter}_train"
    insights_dir="$train_dir/insights"
    eval_dir="$OUT_ROOT/evolution/iter_${iter}_eval"
    md_dir="$OUT_ROOT/skills_iter_$((iter + 1))_md"

    echo "[iteration:$iter] current_skills=$current_skills"
    run_train_matrix "iter_${iter}" "$current_skills" "$train_dir"
    analyze_insights "iter_${iter}" "$current_skills" "$train_dir/collected" "$insights_dir"
    prepare_next_skill_dir "$current_skills" "$next_skills" "$marker"
    evolve_skills "iter_${iter}" "$next_skills" "$train_dir/collected" "$md_dir" "$marker"
    run_eval_matrix \
      "self_evolved_free_dag_iter_$((iter + 1))" \
      "$next_skills" \
      "graph_generate" \
      "free_graph" \
      "" \
      "$eval_dir"
    apply_best_so_far_elite \
      "self_evolved_free_dag_iter_$((iter + 1))" \
      "$next_skills" \
      "$eval_dir"
  done
fi

write_comparison_report

echo "[done]"
echo "  root: $OUT_ROOT"
echo "  report: $OUT_ROOT/reports/autoskill_comparison.md"
echo "  csv: $OUT_ROOT/reports/autoskill_comparison.csv"
