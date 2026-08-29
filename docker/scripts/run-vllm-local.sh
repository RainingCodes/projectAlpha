#!/usr/bin/env bash
# Host-side vLLM helper. Docker Compose users normally use docker-compose.v100.yml instead.
set -euo pipefail

MODEL="${VLLM_MODEL:-LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct}"
PORT="${VLLM_PORT:-8000}"
HOST="${VLLM_HOST:-0.0.0.0}"
GPU_ID="${VLLM_GPU_ID:-0}"
DTYPE="${VLLM_DTYPE:-half}"

export CUDA_VISIBLE_DEVICES="$GPU_ID"

echo "=== vLLM local server ==="
echo "  model : $MODEL"
echo "  host GPU : $GPU_ID"
echo "  dtype : $DTYPE"
echo "  URL   : http://${HOST}:${PORT}/v1/chat/completions"
echo

if command -v vllm >/dev/null 2>&1; then
  exec vllm serve "$MODEL" --host "$HOST" --port "$PORT" --dtype "$DTYPE" --trust-remote-code "$@"
fi
if python3 -c "import vllm" 2>/dev/null; then
  exec python3 -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" --host "$HOST" --port "$PORT" --dtype "$DTYPE" --trust-remote-code "$@"
fi

echo "ERROR: vLLM is not installed." >&2
exit 1
