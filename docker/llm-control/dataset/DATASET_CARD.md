# UMDL Platform-Independent Underwater Mission Dataset — Seed v0.1

## 목적

자연어 잠수정 임무 명령과 실행 시점의 상태를 입력받아 플랫폼 독립형 UMDL JSON을 생성하는 초기 학습·검증용 데이터셋이다. Stonefish, Girona500, ROS 2 토픽, 추진기 이름과 수치를 정답에 포함하지 않는다.

## 규모

- canonical mission group: 120개
- group당 표현: 6개
- 전체: 720개
- train: 576개 / 96 groups
- validation: 72개 / 12 groups
- test: 72개 / 12 groups
- 분할 단위: `group_id`

동일 canonical mission의 한국어·영어·혼합 표현은 모두 같은 split에 들어간다. 따라서 동일 정답의 paraphrase가 train과 test에 동시에 들어가는 누수를 막는다.

## 구성

12개 family가 각각 60개 sample을 가진다.

- navigation
- area_survey
- target_search
- sar
- target_inspection
- pipeline
- environment
- station
- return
- obstacle
- reject
- ambiguous

결정 분포:

- EXECUTE: 600
- REJECT: 60
- REQUEST_CLARIFICATION: 30
- UNSUPPORTED: 30

언어 분포:

- Korean: 480
- English: 120
- Korean-English mixed: 120

## 파일

- `raw/all.jsonl`: 전체 원본
- `raw/train.jsonl`
- `raw/validation.jsonl`
- `raw/test.jsonl`
- `chat/*.jsonl`: SFT용 `messages` 형식
- `schema/umdl-0.1.schema.json`: UMDL JSON Schema
- `manifests/split_manifest.json`: 생성 설정과 분포
- `manifests/group_split.json`: group별 split

## 한계

이 파일은 데이터 파이프라인과 초기 SFT를 검증하기 위한 seed다. 연구 결과를 주장하기 위한 최종 데이터셋으로 사용해서는 안 된다.

- 표현은 canonical template를 기반으로 생성되어 실제 운용자 발화 다양성이 제한적이다.
- 사람 검수 상태는 `human_reviewed=false`다.
- Stonefish 운항 결과, 경로 성공률, 충돌 여부, 에너지 소비는 포함하지 않는다.
- heading sequence와 제어 데이터는 별도 rollout dataset으로 수집해야 한다.

최종 학습 전에는 최소 5,000개 이상의 검수된 자연어–UMDL 쌍으로 확장하고, test target은 전수 검수하는 것을 권장한다.

## 생성 이력

- 생성 도구: OpenAI ChatGPT
- 생성 모델: GPT-5.6 Thinking
- 추론 수준: high
- 생성일: 2026-08-01
- 생성 방식: canonical-first then paraphrase
- temperature/top-p: ChatGPT UI에서 노출되지 않아 기록하지 않음
- 사람 검수 상태: 완료되지 않음
- 상세 생성 및 검수 계획: `config/generation_settings.json`
