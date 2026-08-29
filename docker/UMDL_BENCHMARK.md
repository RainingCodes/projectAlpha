# UMDL LLM Benchmark + Stonefish Staged Validation

이 구성은 실험을 두 단계로 분리한다.

1. **Phase 1 — Stonefish 없이 LLM ↔ Dataset 검증**
2. **Phase 2 — 선택한 LLM을 유지한 채 Stonefish를 GPU 1에 추가하여 공존 환경 검증**

현재 `/mission/plan`은 검증된 Full UMDL을 반환하지만 ROS 명령은 발행하지 않는다. 따라서 Phase 2는 **vLLM + llm-control + Stonefish GPU/OpenGL/ROS 공존 확인**까지이며, UMDL → waypoint/depth/heading → ROS 실행은 추후 Platform Adapter 단계다.

---

## 1. GPU 배치 원칙

### Phase 1 기본/공정 비교

```text
GPU 0 -> vLLM (한 모델씩)
GPU 1 -> 비워 둠
CPU   -> llm-control
Stonefish -> OFF
```

모델 간 latency를 공정하게 비교할 때 이 경로를 사용한다.

### Phase 1 선택형 빠른 스크리닝

```text
GPU 0 -> vLLM model A
GPU 1 -> vLLM model B
CPU   -> llm-control A/B
Stonefish -> OFF
```

두 모델의 accuracy를 동시에 빨리 확인할 때 사용한다. 두 GPU가 같은 V100이더라도 host CPU/IO를 공유하므로 **최종 latency 표는 single-GPU matrix 결과를 사용**하는 것을 권장한다.

### Phase 2 통합 공존

```text
GPU 0 -> vLLM
GPU 1 -> Stonefish (OpenGL/FLS)
CPU   -> llm-control
```

Stonefish와 두 번째 vLLM이 GPU 1을 동시에 잡지 않도록 Compose profile과 스크립트가 서로를 정지시킨다.

---

## 2. Compose profile

`docker-compose.v100.yml` 기본 실행에는 Stonefish가 포함되지 않는다.

```text
default                 -> vllm + llm-control
profile benchmark-dual  -> vllm-secondary + llm-control-secondary 추가
profile simulation      -> stonefish 추가
```

따라서 실수로 Phase 1에서 Stonefish가 GPU 1을 점유하지 않는다.

---

## 3. 최초 설정

```bash
cd ~/projectAlpha/docker
cp .env.sample .env
```

기본값:

```text
VLLM_MODEL=LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct
VLLM_GPU_ID=0
VLLM_GPU_ID_B=1
STONEFISH_GPU_ID=1
VLLM_MAX_MODEL_LEN=4096
VLLM_MAX_NUM_SEQS=16
DISPLAY=:10
```

V100에서는 `dtype=half(FP16)`을 사용한다.

---

## 4. Phase 1A — LLM 없이 Dataset/Codec 검증

```bash
./scripts/phase1-offline-check.sh
```

또는:

```bash
make offline
```

검증 범위:

- Raw dataset 720 samples
- Compact IR v0.2 schema
- Full UMDL schema
- Full → Compact → Full round-trip
- evaluator self-test
- family helper self-test

---

## 5. Phase 1B — Stonefish 없이 한 모델 smoke benchmark

먼저 6개만 확인:

```bash
LIMIT=6 ./scripts/run-umdl-benchmark.sh \
  LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct
```

또는:

```bash
make benchmark MODEL=LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct LIMIT=6
```

전체 test 72개:

```bash
./scripts/run-umdl-benchmark.sh \
  LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct
```

이 단계에서는 Stonefish가 자동으로 정지되어 GPU 1을 사용하지 않는다.

---

## 6. 모델 여러 개를 공정하게 비교

```bash
./scripts/run-benchmark-matrix.sh \
  LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct \
  Qwen/Qwen2.5-3B-Instruct
```

각 모델을 **같은 GPU 0에서 하나씩** 실행한다. 연구용 latency 비교는 이 결과를 기준으로 한다.

---

## 7. 선택: V100 두 장으로 두 모델 동시 스크리닝

```bash
LIMIT=12 ./scripts/run-benchmark-dual.sh \
  LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct \
  Qwen/Qwen2.5-3B-Instruct
```

또는:

```bash
make benchmark-dual \
  MODEL=LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct \
  MODEL_B=Qwen/Qwen2.5-3B-Instruct \
  LIMIT=12
```

이 스크립트는 Stonefish를 먼저 정지하고:

```text
GPU 0 -> model A
GPU 1 -> model B
```

로 평가를 동시에 진행한다.

---

## 8. Phase 2 — Stonefish 추가 검증

### 8.1 통합 Stonefish 이미지가 아직 없다면

저장소 루트에서:

```bash
git submodule update --init --recursive

docker buildx build \
  -f docker/integrated/Dockerfile \
  --build-context stonefish=./stonefish \
  -t projectalpha:jazzy-integrated \
  --load \
  .
```

### 8.2 XRDP 세션에서 실행

```bash
export DISPLAY=:10
./scripts/phase2-stonefish-smoke.sh \
  LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct
```

또는:

```bash
make simulation MODEL=LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct
```

스크립트가 순서대로 확인한다.

```text
1. 호스트 NVIDIA GPU 2장 확인
2. vLLM-secondary 정지 -> GPU 1 해제
3. XRDP Xauthority 생성
4. GPU 0의 vLLM + CPU llm-control 유지/재사용
5. GPU 1에 Stonefish 시작
6. Stonefish renderer가 llvmpipe가 아닌 NVIDIA인지 확인
7. GL_ARB_compute_shader 확인
8. /GIRONA500/* ROS topic 확인
9. Stonefish 실행 중 /umdl/health 확인
10. deterministic safety plan API 확인
11. 기본 3개 sample을 force_llm=true로 다시 평가
```

정상 OpenGL 핵심 출력:

```text
OpenGL vendor string: NVIDIA Corporation
OpenGL renderer string: Tesla V100 ...
OpenGL core profile version string: 4.6.0 NVIDIA ...
GL_ARB_compute_shader: SUPPORTED
```

`llvmpipe`가 나오면 실패로 처리한다.

---

## 9. 한 명령으로 1단계 → 2단계 순차 확인

기본은 Phase 1에서 6개 sample만 확인한 뒤 Stonefish를 추가한다.

```bash
export DISPLAY=:10
./scripts/run-staged-validation.sh \
  LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct
```

또는:

```bash
make staged \
  MODEL=LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct \
  LIMIT=6
```

Phase 1 전체 72개를 먼저 돌리고 싶다면:

```bash
PHASE1_LIMIT=72 ./scripts/run-staged-validation.sh \
  LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct
```

---

## 10. 결과 파일

```text
docker/results/
├── <timestamp>_<model>_test_single_gpu_fair/
│   ├── predictions.jsonl
│   └── metrics.json
├── <timestamp>_<model>_test_dual_gpu_screening/
├── <timestamp>_<model>_test_simulation_coexistence/
└── benchmark_summary.csv
```

`run_tag`가 추가되어 실험 조건을 구분할 수 있다.

주요 metric:

- request success rate
- parse rate
- Compact generation schema valid rate
- Full UMDL schema valid rate
- decision accuracy
- intent accuracy
- task sequence exact match
- parameter field accuracy
- requirements/constraints/clarification accuracy
- Full UMDL exact match
- mean/p50/p95 latency
- token usage
- family별 accuracy

---

## 11. 지금 단계에서 하지 않는 것

현재 Phase 2 성공은 다음을 뜻한다.

```text
자연어 -> LLM -> Compact IR -> Full UMDL 검증
+
vLLM GPU 0 / Stonefish GPU 1 동시 실행
+
Stonefish NVIDIA OpenGL/FLS 조건 확인
+
ROS 2 topic 확인
```

아직 다음을 뜻하지는 않는다.

```text
Full UMDL -> waypoint/depth/heading -> controller -> Stonefish 실제 임무 수행
```

이 연결은 Platform Adapter 구현 후 별도의 Phase 3로 검증한다.
