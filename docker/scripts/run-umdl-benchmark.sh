#!/usr/bin/env bash
# Phase 1B: fair single-GPU model benchmark. Stonefish stays OFF and GPU 1 stays free.
# Usage:
#   ./scripts/run-umdl-benchmark.sh LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct
#   SPLIT=test LIMIT=12 CONCURRENCY=1 ./scripts/run-umdl-benchmark.sh <model>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-${DOCKER_DIR}/docker-compose.v100.yml}"
MODEL="${1:-${VLLM_MODEL:-LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct}}"
SPLIT="${SPLIT:-test}"
LIMIT="${LIMIT:-0}"
CONCURRENCY="${CONCURRENCY:-1}"
VLLM_GPU_ID="${VLLM_GPU_ID:-0}"
RUN_TAG="${RUN_TAG:-single_gpu_fair}"

export VLLM_MODEL="$MODEL"
export VLLM_GPU_ID

cd "$DOCKER_DIR"
mkdir -p results

# Safety: dual benchmark services and Stonefish may both contend for GPU 1.
# They are not needed in the fair single-GPU run.
docker compose -f "$COMPOSE_FILE" --profile benchmark-dual stop llm-control-secondary vllm-secondary >/dev/null 2>&1 || true
docker compose -f "$COMPOSE_FILE" --profile simulation stop stonefish >/dev/null 2>&1 || true

echo "[Phase 1B 1/4] model=$VLLM_MODEL physical_gpu=$VLLM_GPU_ID mode=$RUN_TAG"
echo "[Phase 1B 2/4] starting vLLM + llm-control only"
docker compose -f "$COMPOSE_FILE" up -d --build vllm llm-control

echo "[Phase 1B 3/4] waiting for UMDL API"
ready=0
for _ in $(seq 1 120); do
  if curl -fsS http://127.0.0.1:8080/umdl/health >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [[ "$ready" != "1" ]]; then
  echo "ERROR: llm-control did not become healthy." >&2
  docker compose -f "$COMPOSE_FILE" logs --tail=120 vllm llm-control >&2 || true
  exit 1
fi
curl -fsS http://127.0.0.1:8080/health | python3 -m json.tool

args=(--split "$SPLIT" --concurrency "$CONCURRENCY" --model-name "$MODEL" --run-tag "$RUN_TAG")
if [[ "$LIMIT" != "0" ]]; then
  args+=(--limit "$LIMIT")
fi

echo "[Phase 1B 4/4] running benchmark"
docker compose -f "$COMPOSE_FILE" exec -T llm-control \
  python3 /app/scripts/benchmark_umdl.py "${args[@]}"

echo "Results: ${DOCKER_DIR}/results"
