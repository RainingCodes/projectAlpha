#!/usr/bin/env bash
# Phase 1C: optional throughput mode using both V100s concurrently.
# GPU 0 -> model A, GPU 1 -> model B. Stonefish is forced OFF.
# Use the single-GPU matrix for strict latency comparisons; use this for faster accuracy screening.
# Usage: ./scripts/run-benchmark-dual.sh <model-a> <model-b>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-${DOCKER_DIR}/docker-compose.v100.yml}"
MODEL_A="${1:-}"
MODEL_B="${2:-}"
SPLIT="${SPLIT:-test}"
LIMIT="${LIMIT:-0}"
CONCURRENCY="${CONCURRENCY:-1}"

if [[ -z "$MODEL_A" || -z "$MODEL_B" ]]; then
  echo "Usage: $0 <model-a> <model-b>" >&2
  exit 2
fi

export VLLM_MODEL="$MODEL_A"
export VLLM_MODEL_B="$MODEL_B"
export VLLM_GPU_ID="${VLLM_GPU_ID:-0}"
export VLLM_GPU_ID_B="${VLLM_GPU_ID_B:-1}"

if [[ "$VLLM_GPU_ID" == "$VLLM_GPU_ID_B" ]]; then
  echo "ERROR: dual mode requires different physical GPU IDs." >&2
  exit 2
fi

cd "$DOCKER_DIR"
mkdir -p results

echo "[Phase 1C] stopping Stonefish so GPU ${VLLM_GPU_ID_B} is free"
docker compose -f "$COMPOSE_FILE" --profile simulation stop stonefish >/dev/null 2>&1 || true

echo "[Phase 1C] A=$MODEL_A -> GPU $VLLM_GPU_ID"
echo "[Phase 1C] B=$MODEL_B -> GPU $VLLM_GPU_ID_B"
docker compose -f "$COMPOSE_FILE" --profile benchmark-dual up -d --build \
  vllm vllm-secondary llm-control llm-control-secondary

for port in 8080 8081; do
  ready=0
  for _ in $(seq 1 120); do
    if curl -fsS "http://127.0.0.1:${port}/umdl/health" >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 2
  done
  if [[ "$ready" != "1" ]]; then
    echo "ERROR: API on port $port did not become healthy." >&2
    docker compose -f "$COMPOSE_FILE" --profile benchmark-dual logs --tail=160 >&2 || true
    exit 1
  fi
done

common=(--split "$SPLIT" --concurrency "$CONCURRENCY")
if [[ "$LIMIT" != "0" ]]; then
  common+=(--limit "$LIMIT")
fi

set +e
docker compose -f "$COMPOSE_FILE" --profile benchmark-dual exec -T llm-control \
  python3 /app/scripts/benchmark_umdl.py "${common[@]}" --model-name "$MODEL_A" --run-tag dual_gpu_screening_gpu0 &
pid_a=$!

docker compose -f "$COMPOSE_FILE" --profile benchmark-dual exec -T llm-control-secondary \
  python3 /app/scripts/benchmark_umdl.py "${common[@]}" --model-name "$MODEL_B" --run-tag dual_gpu_screening_gpu1 &
pid_b=$!

wait "$pid_a"; rc_a=$?
wait "$pid_b"; rc_b=$?
set -e

# Summary can be generated from either CPU evaluator because both mount ./results.
docker compose -f "$COMPOSE_FILE" --profile benchmark-dual exec -T llm-control \
  python3 /app/scripts/summarize_benchmarks.py --results-dir /app/results || true

if [[ "$rc_a" != "0" || "$rc_b" != "0" ]]; then
  echo "ERROR: dual benchmark failed: rc_a=$rc_a rc_b=$rc_b" >&2
  exit 1
fi

echo "[Phase 1C] PASS - results in ${DOCKER_DIR}/results"
echo "NOTE: use run-benchmark-matrix.sh for strict latency comparison under identical single-GPU conditions."
