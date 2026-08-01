# UMDL 데이터셋 및 기존 Stonefish 코드 통합 안내

## 1. 확인한 현재 코드 구조

업로드된 코드의 현재 흐름은 다음과 같다.

```text
POST /control/high_level
  → 자연어 instruction
  → llm_to_twist()
  → TwistOut
  → /GIRONA500/cmd_vel 발행
  → cmd_vel_to_thrusters
  → Stonefish
```

`docker/llm-control/app/main.py`의 기존 `llm_to_twist()`는 자연어를 6개 속도 값으로 직접 변환한다. 짧은 전진·후진 시험에는 사용할 수 있지만, 탐색·점검·귀환·조건부 중단과 같은 임무 데이터셋의 출력 구조로는 적합하지 않다.

이번 통합본은 기존 제어 endpoint를 삭제하지 않고 다음 경로를 별도로 추가한다.

```text
POST /mission/plan
  → 자연어 + runtime_context + available_capabilities
  → UMDL JSON
  → JSON Schema 검사
  → 임무 규칙 검사
  → 계획 반환
  → ROS 명령은 발행하지 않음
```

따라서 `/mission/plan`의 출력은 앞으로 구현할 플랫폼 adapter/compiler에 전달해야 한다.

```text
UMDL
  → task compiler
  → path/waypoint planner
  → heading/depth reference
  → 기존 제어기 또는 MPC
  → ROS 2 / Stonefish
```

## 2. 추가된 구조

```text
docker/llm-control/
├── app/
│   ├── main.py                 # 기존 API + UMDL router 등록
│   └── umdl_router.py          # /mission/plan, /dataset/*
├── config/
│   ├── dataset_settings.json
│   ├── generation_settings.json
│   ├── runtime_umdl_settings.json
│   └── training_settings.json
├── dataset/
│   ├── DATASET_CARD.md
│   ├── raw/
│   │   ├── all.jsonl
│   │   ├── train.jsonl
│   │   ├── validation.jsonl
│   │   └── test.jsonl
│   ├── chat/
│   │   ├── train.jsonl
│   │   ├── validation.jsonl
│   │   └── test.jsonl
│   ├── schema/umdl-0.1.schema.json
│   └── manifests/
├── scripts/
│   ├── make_seed_dataset.py
│   ├── validate_dataset.py
│   ├── summarize_dataset.py
│   ├── inspect_sample.py
│   └── evaluate_predictions.py
└── requirements.txt            # jsonschema 추가
```

## 3. 데이터셋 설정값

`config/dataset_settings.json`에 고정된 값:

- seed: `20260801`
- canonical group: `120`
- sample/group: `6`
- total samples: `720`
- group split: `80/10/10`
- train: `576`
- validation: `72`
- test: `72`

`config/training_settings.json`에는 초기 LoRA smoke test 설정을 기록했다.

- base model: `LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct`
- max sequence length: `2048`
- FP16: enabled
- BF16: disabled
- epoch: `3`
- learning rate: `2e-4`
- batch size: `2`
- gradient accumulation: `16`
- LoRA r/alpha/dropout: `16/32/0.05`

이 720개 데이터는 학습 코드와 출력 형식을 확인하기 위한 seed다. 장기 학습 성능을 판단하기 전에 5,000개 이상으로 확장해야 한다.

## 4. 빌드

저장소 루트에서:

```bash
docker compose \
  -f docker/docker-compose.v100.yml \
  build llm-control
```

전체 실행:

```bash
export DISPLAY=:10

docker compose \
  -f docker/docker-compose.v100.yml \
  up -d vllm llm-control
```

Stonefish까지 실행하려면 기존 방식대로 `stonefish` 서비스도 포함한다.

```bash
docker compose \
  -f docker/docker-compose.v100.yml \
  up -d vllm stonefish llm-control
```

## 5. 컨테이너 안에서 데이터셋 확인

전체 검증:

```bash
docker compose \
  -f docker/docker-compose.v100.yml \
  exec llm-control \
  python3 /app/scripts/validate_dataset.py --root /app/dataset
```

정상 결과 핵심:

```json
{
  "valid": true,
  "sample_counts": {
    "train": 576,
    "validation": 72,
    "test": 72
  },
  "sample_total": 720,
  "group_count": 120,
  "error_count": 0
}
```

분포 확인:

```bash
docker compose \
  -f docker/docker-compose.v100.yml \
  exec llm-control \
  python3 /app/scripts/summarize_dataset.py --root /app/dataset
```

테스트 샘플 1개 확인:

```bash
docker compose \
  -f docker/docker-compose.v100.yml \
  exec llm-control \
  python3 /app/scripts/inspect_sample.py \
    --root /app/dataset \
    --split test \
    --index 0
```

같은 canonical mission에서 만들어진 표현 6개 확인:

```bash
docker compose \
  -f docker/docker-compose.v100.yml \
  exec llm-control \
  python3 /app/scripts/inspect_sample.py \
    --root /app/dataset \
    --split test \
    --group-id avoid_001
```

## 6. HTTP로 데이터셋 확인

UMDL 기능 상태:

```bash
curl -s http://127.0.0.1:8080/umdl/health | python3 -m json.tool
```

전체 분포:

```bash
curl -s http://127.0.0.1:8080/dataset/stats | python3 -m json.tool
```

테스트 샘플:

```bash
curl -s \
  'http://127.0.0.1:8080/dataset/sample?split=test&index=0' \
  | python3 -m json.tool
```

특정 group 전체:

```bash
curl -s \
  'http://127.0.0.1:8080/dataset/sample?split=test&group_id=avoid_001' \
  | python3 -m json.tool
```

## 7. 실제 LLM 경로의 UMDL 출력 확인

```bash
curl -s http://127.0.0.1:8080/mission/plan \
  -H 'Content-Type: application/json' \
  -d '{
    "mission_id": "runtime_demo_001",
    "force_llm": true,
    "instruction": "전방 5m에 장애물이 감지됐어. 즉시 회피하고 안전거리를 확보해.",
    "runtime_context": {
      "depth_m": 10,
      "battery_pct": 65,
      "visibility_m": 4,
      "current": {"speed_kn": 0.3, "direction_deg": 180},
      "obstacles": [
        {"id": "obs_1", "distance_m": 5, "bearing_deg": 0, "relative": "FRONT"}
      ]
    },
    "available_capabilities": [
      "OBSTACLE_AVOIDANCE",
      "DEPTH_CONTROL",
      "DATA_LOGGING"
    ]
  }' | python3 -m json.tool
```

응답에서 확인할 값:

```text
valid=true
validation.schema_errors=[]
validation.rule_errors=[]
execution.ros_command_published=false
```

`valid=false`이면 LLM 출력이 스키마 또는 capability 규칙을 위반한 것이다. 이 응답을 바로 Stonefish에 적용하면 안 된다.

`force_llm=true`는 안전 Fast Path를 우회하고 실제 LLM 생성 경로를
점검하기 위한 테스트 옵션이다. 실제 긴급 장애물 회피 요청에서는 이 옵션을
사용하지 않는다.

## 8. 기존 `/control/high_level`과의 관계

기존 endpoint는 그대로 남아 있다.

```bash
curl -s http://127.0.0.1:8080/control/high_level \
  -H 'Content-Type: application/json' \
  -d '{"instruction":"천천히 전진"}'
```

이 endpoint는 실제 `/GIRONA500/cmd_vel`을 발행한다. 데이터셋과 UMDL 구조를 확인할 때는 `/mission/plan`을 사용해야 한다.

권장 최종 구조는 다음과 같다.

```text
/control/high_level
  → 수동 저수준 시험용으로 한정 또는 향후 폐기

/mission/plan
  → 자연어를 UMDL로 변환

/platform/compile
  → UMDL을 플랫폼별 waypoint/heading으로 컴파일

/controller/execute
  → 기존 제어기/MPC가 실행
```

## 9. 학습 파일 확인

SFT 입력은 `dataset/chat/*.jsonl`이다. 각 행은 다음 형식이다.

```json
{
  "id": "avoid_001_01",
  "group_id": "avoid_001",
  "split": "test",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "...UMDL JSON..."}
  ]
}
```

vLLM은 추론 서버이므로 이 파일을 vLLM 컨테이너에 넣는 것만으로 학습되지는 않는다. 별도의 Transformers/TRL/PEFT 학습 작업에서 adapter를 만든 뒤, vLLM이 그 모델 또는 병합 모델을 로드하도록 변경해야 한다.

## 10. 예측 결과 평가

모델 예측을 다음 JSONL 형식으로 저장한다.

```json
{"id":"avoid_001_01","prediction":{"schema_version":"umdl/0.1","...":"..."}}
```

평가:

```bash
python3 docker/llm-control/scripts/evaluate_predictions.py \
  --gold docker/llm-control/dataset/raw/test.jsonl \
  --pred predictions.jsonl \
  --schema docker/llm-control/dataset/schema/umdl-0.1.schema.json
```

출력 지표:

- schema_valid_rate
- decision_accuracy
- intent_accuracy
- task_sequence_exact_match
- full_exact_match

## 11. 다음 구현 우선순위

1. UMDL seed 720개로 데이터 로딩·SFT·출력 파싱 확인
2. test target 전수 검수
3. 5,000개 이상으로 자연어 표현과 상태 조합 확장
4. `platform_adapter` 구현
5. UMDL task를 waypoint/depth/heading reference로 변환
6. Stonefish rollout으로 completion, collision, CTE, energy 기록
7. 정적 자연어–UMDL 데이터와 동적 상태–replan 데이터를 분리해 평가
