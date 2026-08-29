# 순차 검증 요약

가장 짧은 실행 순서는 아래다.

```bash
cd ~/projectAlpha/docker
cp .env.sample .env

# 1) 데이터셋/codec만 확인
./scripts/phase1-offline-check.sh

# 2) Stonefish 없이 LLM 6개 smoke
LIMIT=6 ./scripts/run-umdl-benchmark.sh \
  LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct

# 3) Stonefish 추가: GPU0=vLLM, GPU1=Stonefish
export DISPLAY=:10
./scripts/phase2-stonefish-smoke.sh \
  LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct
```

한 번에 실행하려면:

```bash
export DISPLAY=:10
PHASE1_LIMIT=6 ./scripts/run-staged-validation.sh \
  LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct
```

GPU 1을 놀리지 않고 두 모델을 빠르게 확인할 때만:

```bash
LIMIT=12 ./scripts/run-benchmark-dual.sh \
  LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct \
  Qwen/Qwen2.5-3B-Instruct
```

Stonefish 단계로 넘어가면 dual service는 스크립트가 자동으로 정지한다.
