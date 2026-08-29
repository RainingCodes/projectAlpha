# UMDL Compact IR v0.2

## 현재 생성 경로

```text
operator command + runtime_context + available_capabilities
  -> LLM
  -> Compact UMDL IR v0.2
  -> deterministic compiler
  -> Full UMDL 0.1
  -> JSON Schema + runtime rule validation
```

`/mission/plan`은 ROS 명령을 발행하지 않는다. 긴급 장애물 요청은 실제 runtime에서 Safety Fast Path를 사용할 수 있지만, `benchmark_umdl.py`는 `force_llm=true`로 이 경로를 우회하여 LLM 자체 성능을 비교한다.

## v0.2에서 해결한 문제

v0.1 Compact IR은 `parameters`와 pattern의 세부 수치를 담지 못해 거리, 방위, 목표 수심, 측정 시간, survey spacing 등이 컴파일 과정에서 유실될 수 있었다. v0.2는 다음을 보존한다.

- task parameters: `bearing_deg`, `distance_m`, `target_depth_m`, `duration_s`, `metric`, `inspection_focus`, `direction`, `target`
- pattern parameters: 현재 seed dataset의 `spacing_m`
- `constraints_policy`
- `contingency_policy`
- dataset에 사용된 sensor role과 reason code 문자열
- 한글이 포함된 target reference

현재 seed 720개는 `Full UMDL -> Compact IR v0.2 -> Full UMDL` exact round-trip 720/720을 통과한다.

## Health 정상 예

```json
{
  "schema_ready": true,
  "generation_schema_ready": true,
  "generation_mode": "compact_ir_v0.2_then_compile",
  "guided_json": true,
  "few_shot_enabled": false,
  "family_hints_enabled": false,
  "safety_fast_path": true
}
```

## Baseline benchmark 설정

모델 자체를 비교할 때는 다음을 권장한다.

```text
UMDL_FEW_SHOT=0
UMDL_FAMILY_HINTS=0
UMDL_MAX_RETRIES=0
```

Few-shot 효과를 별도로 볼 때만 `UMDL_FEW_SHOT=1`로 바꾼다. keyword family hint는 benchmark 기본값에서 꺼 두어, rule classifier의 오분류가 LLM 점수를 대신 결정하지 않도록 한다.

## 검증

```bash
docker compose -f docker-compose.v100.yml exec -T llm-control \
  python3 /app/scripts/validate_dataset.py --root /app/dataset

docker compose -f docker-compose.v100.yml exec -T llm-control \
  python3 /app/scripts/self_test.py
```

정상 기준은 `error_count=0`, `compact_schema_valid_count=720`, `compact_roundtrip_exact_count=720`이다.
