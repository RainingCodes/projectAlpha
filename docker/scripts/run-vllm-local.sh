#!/usr/bin/env bash
# 호스트에서 vLLM OpenAI 호환 서버를 띄웁니다. (Docker의 llm-control 이 HF 로컬 모드로 붙을 때 사용)
#
# 사전 요구: NVIDIA 드라이버 + CUDA, Python 3.10+ 권장
#   pip install vllm
# 문서: https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html
#
# 환경 변수:
#   VLLM_MODEL   Hugging Face 모델 id (기본: Qwen/Qwen2.5-3B-Instruct)
#   VLLM_PORT    listen 포트 (기본: 8000)
#   VLLM_HOST    bind 주소 (기본: 0.0.0.0 — Docker에서 host.docker.internal 로 접근)
#   HF_TOKEN     게이트된 모델이면 vLLM이 가중치 받을 때 필요할 수 있음
#
# 사용 예:
#   ./docker/scripts/run-vllm-local.sh
#   VLLM_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct VLLM_PORT=8000 ./docker/scripts/run-vllm-local.sh --dtype auto
#
# llm-control(docker) 설정 예 (docker/llm-settings.env):
#   LLM_PROVIDER=huggingface
#   HF_API_BASE=http://host.docker.internal:8000/v1   # VLLM_PORT 와 맞출 것
#   HUGGINGFACE_MODEL=<위 VLLM_MODEL 과 동일>
#
# vLLM에 --api-key 를 쓰는 경우, llm-control 쪽에 동일 값을 HF_TOKEN 으로 넣어 Bearer 로 보냅니다.

set -euo pipefail

MODEL="${VLLM_MODEL:-Qwen/Qwen2.5-3B-Instruct}"
PORT="${VLLM_PORT:-8000}"
HOST="${VLLM_HOST:-0.0.0.0}"

echo "=== vLLM 로컬 서버 ==="
echo "  model : $MODEL"
echo "  URL   : http://${HOST}:${PORT}/v1/chat/completions"
echo "  docker llm-control 용 HF_API_BASE:"
echo "        http://host.docker.internal:${PORT}/v1"
echo "  HUGGINGFACE_MODEL 은 위 model 과 동일하게 맞추세요."
echo ""

if command -v vllm >/dev/null 2>&1; then
  exec vllm serve "$MODEL" --host "$HOST" --port "$PORT" "$@"
fi

if python3 -c "import vllm" 2>/dev/null; then
  exec python3 -m vllm.entrypoints.openai.api_server --model "$MODEL" --host "$HOST" --port "$PORT" "$@"
fi

echo "오류: vllm 이 설치되어 있지 않습니다. 호스트에서 다음을 실행하세요:" >&2
echo "  pip install vllm" >&2
exit 1
