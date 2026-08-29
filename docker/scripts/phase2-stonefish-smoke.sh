#!/usr/bin/env bash
# Phase 2: coexistence/infrastructure smoke test.
# GPU 0 -> vLLM, GPU 1 -> Stonefish, llm-control -> CPU.
# This verifies GPU/OpenGL/FLS prerequisites + ROS visibility + LLM API coexistence.
# It does NOT claim UMDL->Stonefish execution; the platform adapter is still a later step.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-${DOCKER_DIR}/docker-compose.v100.yml}"
MODEL="${1:-${VLLM_MODEL:-LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct}}"
export VLLM_MODEL="$MODEL"
export VLLM_GPU_ID="${VLLM_GPU_ID:-0}"
export STONEFISH_GPU_ID="${STONEFISH_GPU_ID:-1}"
export DISPLAY="${DISPLAY:-:10}"
RUN_LLM_SMOKE="${RUN_LLM_SMOKE:-1}"
LLM_SMOKE_LIMIT="${LLM_SMOKE_LIMIT:-3}"

if [[ "$VLLM_GPU_ID" == "$STONEFISH_GPU_ID" ]]; then
  echo "ERROR: simulation mode requires different physical GPU IDs for vLLM and Stonefish." >&2
  exit 2
fi

cd "$DOCKER_DIR"

echo "[Phase 2 1/8] host GPU preflight"
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "ERROR: nvidia-smi not found on host." >&2
  exit 1
fi
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
GPU_COUNT="$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l | tr -d ' ')"
if (( GPU_COUNT < 2 )); then
  echo "ERROR: expected at least two NVIDIA GPUs; found $GPU_COUNT" >&2
  exit 1
fi

echo "[Phase 2 2/8] stop dual benchmark services to release GPU 1"
docker compose -f "$COMPOSE_FILE" --profile benchmark-dual stop llm-control-secondary vllm-secondary >/dev/null 2>&1 || true

echo "[Phase 2 3/8] prepare XRDP/X11 authorization"
"$SCRIPT_DIR/prepare-stonefish-x11.sh"

echo "[Phase 2 4/8] keep/reuse primary vLLM + llm-control"
docker compose -f "$COMPOSE_FILE" up -d --build vllm llm-control

ready=0
for _ in $(seq 1 120); do
  if curl -fsS http://127.0.0.1:8080/umdl/health >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [[ "$ready" != "1" ]]; then
  echo "ERROR: primary UMDL API is not healthy." >&2
  docker compose -f "$COMPOSE_FILE" logs --tail=120 vllm llm-control >&2 || true
  exit 1
fi

echo "[Phase 2 5/8] start Stonefish on GPU $STONEFISH_GPU_ID"
docker compose -f "$COMPOSE_FILE" --profile simulation up -d stonefish
sleep "${STONEFISH_STARTUP_WAIT_SECONDS:-12}"

if ! docker compose -f "$COMPOSE_FILE" --profile simulation ps --status running stonefish | grep -q stonefish; then
  echo "ERROR: Stonefish container is not running." >&2
  docker compose -f "$COMPOSE_FILE" --profile simulation logs --tail=180 stonefish >&2 || true
  exit 1
fi

echo "[Phase 2 6/8] verify GPU isolation + NVIDIA OpenGL/Compute Shader"
echo "--- vLLM visible GPU (container-local index may appear as 0)"
docker compose -f "$COMPOSE_FILE" exec -T vllm nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

echo "--- Stonefish visible GPU (container-local index may appear as 0)"
docker compose -f "$COMPOSE_FILE" --profile simulation exec -T stonefish \
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

echo "--- Stonefish OpenGL"
docker compose -f "$COMPOSE_FILE" --profile simulation exec -T stonefish bash -lc \
  'glxinfo -B | grep -E "direct rendering|OpenGL vendor|OpenGL renderer|OpenGL core profile version|OpenGL version"'

if docker compose -f "$COMPOSE_FILE" --profile simulation exec -T stonefish bash -lc \
  'glxinfo -B | grep -qi llvmpipe'; then
  echo "ERROR: Stonefish is using llvmpipe software rendering." >&2
  exit 1
fi

docker compose -f "$COMPOSE_FILE" --profile simulation exec -T stonefish bash -lc \
  'glxinfo | grep -m1 GL_ARB_compute_shader >/dev/null && echo "GL_ARB_compute_shader: SUPPORTED"'

echo "[Phase 2 7/8] verify ROS 2 Stonefish topics"
docker compose -f "$COMPOSE_FILE" --profile simulation exec -T stonefish bash -lc \
  'source /opt/ros/jazzy/setup.bash; source /ws/install/setup.bash; timeout 10 ros2 topic list | grep -E "^/GIRONA500/" | head -n 40'

echo "[Phase 2 8/8] verify UMDL API while Stonefish is active"
curl -fsS http://127.0.0.1:8080/umdl/health | python3 -m json.tool

# Deterministic safety-path API smoke: validates the planning service without conflating
# coexistence with the model's semantic accuracy.
curl -fsS -X POST http://127.0.0.1:8080/mission/plan \
  -H 'Content-Type: application/json' \
  -d '{
    "instruction": "전방 장애물을 회피하고 안전한 위치에서 정지 후 결과를 보고해",
    "runtime_context": {"obstacles": [{"id": "front_obstacle"}]},
    "available_capabilities": ["OBSTACLE_AVOIDANCE", "DATA_LOGGING"],
    "mission_id": "phase2_coexistence_smoke",
    "force_llm": false
  }' | python3 -m json.tool

if [[ "$RUN_LLM_SMOKE" == "1" ]]; then
  echo "[Phase 2] run ${LLM_SMOKE_LIMIT}-sample forced-LLM benchmark while Stonefish stays active"
  docker compose -f "$COMPOSE_FILE" exec -T llm-control \
    python3 /app/scripts/benchmark_umdl.py \
      --split test --limit "$LLM_SMOKE_LIMIT" --concurrency 1 \
      --model-name "$MODEL" --run-tag simulation_coexistence
fi

echo "[Phase 2] PASS"
echo "GPU 0=vLLM, GPU 1=Stonefish, llm-control=CPU coexistence is healthy."
echo "NOTE: UMDL -> waypoint/depth/heading -> ROS execution is not tested because the platform adapter is not implemented yet."
