#!/usr/bin/env bash
# Strict model-to-model comparison: one model at a time on the same physical GPU.
# This is the preferred path for latency numbers used in reports/papers.
# Example:
#   ./scripts/run-benchmark-matrix.sh \
#     LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct \
#     Qwen/Qwen2.5-3B-Instruct
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-${DOCKER_DIR}/docker-compose.v100.yml}"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <model1> [model2 ...]" >&2
  exit 2
fi

for model in "$@"; do
  echo
  echo "============================================================"
  echo "Fair single-GPU benchmark: $model"
  echo "============================================================"
  RUN_TAG=single_gpu_matrix "$SCRIPT_DIR/run-umdl-benchmark.sh" "$model"
done

docker compose -f "$COMPOSE_FILE" exec -T llm-control \
  python3 /app/scripts/summarize_benchmarks.py --results-dir /app/results || true
