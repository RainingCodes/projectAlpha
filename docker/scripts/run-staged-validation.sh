#!/usr/bin/env bash
# One command for the requested sequence:
#   1) offline dataset/codec validation
#   2) Stonefish-free LLM benchmark
#   3) Stonefish coexistence smoke
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL="${1:-${VLLM_MODEL:-LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct}}"
PHASE1_LIMIT="${PHASE1_LIMIT:-6}"

echo "============================================================"
echo "STEP 1/3 - Offline dataset/codec check"
echo "============================================================"
"$SCRIPT_DIR/phase1-offline-check.sh"

echo
echo "============================================================"
echo "STEP 2/3 - LLM benchmark WITHOUT Stonefish"
echo "============================================================"
LIMIT="$PHASE1_LIMIT" RUN_TAG=staged_phase1 "$SCRIPT_DIR/run-umdl-benchmark.sh" "$MODEL"

echo
echo "============================================================"
echo "STEP 3/3 - vLLM + Stonefish coexistence"
echo "============================================================"
"$SCRIPT_DIR/phase2-stonefish-smoke.sh" "$MODEL"

echo
echo "All staged checks finished."
