#!/usr/bin/env bash
# Phase 1A: validate dataset/codec/evaluator without vLLM or Stonefish.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-${DOCKER_DIR}/docker-compose.v100.yml}"
cd "$DOCKER_DIR"

echo "[Phase 1A] Build CPU-only llm-control image"
docker compose -f "$COMPOSE_FILE" build llm-control

echo "[Phase 1A] Validate dataset + Compact IR codec"
docker compose -f "$COMPOSE_FILE" run --rm --no-deps llm-control \
  python3 /app/scripts/validate_dataset.py --root /app/dataset

echo "[Phase 1A] Run offline self-test"
docker compose -f "$COMPOSE_FILE" run --rm --no-deps llm-control \
  python3 /app/scripts/self_test.py

echo "[Phase 1A] PASS"
