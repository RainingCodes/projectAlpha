# 기존 docker/ 전체 교체 방법

이 압축파일 안의 최상위 `docker/` 디렉터리를 기존 프로젝트의 `docker/`와 교체하면 된다.

```bash
cd ~/projectAlpha
mv docker docker.backup.$(date +%Y%m%d_%H%M%S)
```

다운로드한 압축파일을 `~/projectAlpha`에 둔 경우:

```bash
tar -xzf docker_umdl_staged_v03.tar.gz
cd docker
cp .env.sample .env
```

최초 확인:

```bash
./scripts/phase1-offline-check.sh
```

Stonefish 없이 LLM smoke:

```bash
LIMIT=6 ./scripts/run-umdl-benchmark.sh \
  LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct
```

그 다음 Stonefish 포함:

```bash
export DISPLAY=:10
./scripts/phase2-stonefish-smoke.sh \
  LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct
```

한 번에 순차 실행:

```bash
export DISPLAY=:10
PHASE1_LIMIT=6 ./scripts/run-staged-validation.sh \
  LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct
```

## 이 버전에서 GPU 사용

```text
Phase 1 fair benchmark
GPU 0 -> vLLM
GPU 1 -> free
CPU   -> llm-control

Phase 1 dual screening (선택)
GPU 0 -> model A
GPU 1 -> model B
CPU   -> llm-control A/B

Phase 2 simulation
GPU 0 -> vLLM
GPU 1 -> Stonefish
CPU   -> llm-control
```

`benchmark-dual`과 `simulation` profile은 동시에 사용하지 않는 것이 전제이며, 제공 스크립트는 전환 시 경쟁 서비스를 먼저 정지한다.
