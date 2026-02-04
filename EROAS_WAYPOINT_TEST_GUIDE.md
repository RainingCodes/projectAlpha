# EROAS Multi-Waypoint Navigation Test Guide

## 개요
이 가이드는 EROAS 기반 멀티 웨이포인트 네비게이션 테스트를 실행하는 방법을 설명합니다.

## 테스트 기능

웨이포인트 네비게이션 테스트는 다음 기능을 시연합니다:

1. **순차적 웨이포인트 추적**: AUV가 4개의 미리 정의된 웨이포인트를 순서대로 방문
2. **자동 웨이포인트 전환**: 웨이포인트의 일정 범위 내에 도착하면 자동으로 다음 포인트로 이동
3. **미션 완료**: 모든 웨이포인트를 방문하면 테스트 종료 (시작점으로 복귀)
4. **RViz 시각화**: 실시간으로 다음을 표시
   - 모든 웨이포인트 (색상 구분)
   - 계획된 경로 (주황색 선)
   - 실제 주행 경로 (청록색 선)
   - 현재 AUV 위치와 헤딩
   - 웨이포인트 라벨 (WP0, WP1, WP2, WP3)

## 기본 웨이포인트 설정

기본 테스트는 NED 좌표계에서 정사각형 패턴을 사용합니다:

- **Waypoint 0 (시작)**: (0, 0, 3) - 녹색 구체
- **Waypoint 1**: (10, 0, 3) - 주황색 구체
- **Waypoint 2**: (10, 10, 3) - 자홍색 구체
- **Waypoint 3**: (0, 10, 3) - 밝은 파란색 구체

모든 웨이포인트는 수심 3m에 위치하며, 10m x 10m 정사각형 패턴을 형성합니다.

## 테스트 실행

### 1. 패키지 빌드

```bash
cd /home/foc/projectAlpha
colcon build --packages-select eroas_navigation
source install/setup.bash
```

### 2. 테스트 실행

```bash
ros2 launch eroas_navigation girona500_waypoint_test.launch.py
```

실행되는 노드들:
- Stonefish 시뮬레이터 (웨이포인트 마커 포함)
- Waypoint Navigator 노드
- Velocity to Thruster 변환기
- RViz 시각화
- Sensor Monitor (별도 xterm 창)

### 3. 진행 상황 모니터링

Waypoint Navigator는 다음과 같은 로그 메시지를 출력합니다:

```
[waypoint_navigator] WP 0/3: Dist: 5.23m, Hdg_err: 12.3deg, vx: 0.65m/s
[waypoint_navigator] Reached waypoint 0 at [0.0, 0.0, 3.0]
[waypoint_navigator] Moving to waypoint 1: [10.0  0.0  3.0]
```

### 4. RViz 시각화

RViz에서 다음을 확인할 수 있습니다:
- **녹색 구체**: 시작점 (WP0)
- **주황색 구체**: Waypoint 1
- **자홍색 구체**: Waypoint 2
- **밝은 파란색 구체**: Waypoint 3
- **노란색 구체**: 현재 AUV 위치
- **파란색 화살표**: AUV 헤딩
- **주황색 선**: 모든 웨이포인트를 연결한 계획 경로
- **청록색 선**: 실제 주행한 경로

현재 타겟 웨이포인트는 다른 것들보다 크게 표시됩니다. 방문한 웨이포인트는 반투명하게 됩니다.

## 웨이포인트 커스터마이징

런치 인자를 사용하여 웨이포인트를 커스터마이징할 수 있습니다:

```bash
ros2 launch eroas_navigation girona500_waypoint_test.launch.py \
    waypoint_x:="[0.0, 15.0, 15.0, 0.0]" \
    waypoint_y:="[0.0, 0.0, 15.0, 15.0]" \
    waypoint_z:="[2.0, 2.0, 4.0, 4.0]" \
    waypoint_tolerance:=2.0
```

파라미터 설명:
- `waypoint_x`: North 좌표 리스트 (NED X축)
- `waypoint_y`: East 좌표 리스트 (NED Y축)
- `waypoint_z`: Down 좌표 리스트 (NED Z축, 양수 = 더 깊음)
- `waypoint_tolerance`: 웨이포인트 도착 판정 거리 (미터)

## 생성된 파일들

### 새로 생성된 파일

1. **네비게이션 노드**:
   - `src/eroas_navigation/eroas_navigation/waypoint_navigator.py`

2. **런치 파일**:
   - `src/eroas_navigation/launch/girona500_waypoint_test.launch.py`

3. **시각화 설정**:
   - `src/eroas_navigation/config/waypoint_navigation.rviz`

4. **Stonefish 시나리오**:
   - `src/stonefish_ros2/scenarios/waypoint_test.scn`

### 기존 파일 (변경 없음)

기본 포인트 투 포인트 테스트는 그대로 유지됩니다:
- 기존 런치: `ros2 launch eroas_navigation girona500_eroas.launch.py`
- 기존 노드: `eroas_node`

## 좌표계 참고사항

- **Stonefish는 NED 사용** (North-East-Down):
  - X축: North
  - Y축: East
  - Z축: Down (양수 = 수중 더 깊음)

- **RViz는 ENU 사용** (East-North-Up):
  - X축: East
  - Y축: North
  - Z축: Up (양수 = 공중으로 높음)

Waypoint Navigator는 시각화를 위한 좌표 변환을 자동으로 처리합니다.

## 문제 해결

### AUV가 움직이지 않음
- 추진기 변환기가 실행 중인지 확인
- Odometry 토픽 확인: `ros2 topic echo /GIRONA500/dynamics`
- 속도 명령 확인: `ros2 topic echo /GIRONA500/cmd_vel`

### RViz에 마커가 보이지 않음
- Fixed Frame이 "world_ned"로 설정되었는지 확인
- 토픽 확인: `ros2 topic echo /waypoint_nav/visualization_markers`
- RViz에서 MarkerArray 디스플레이가 활성화되었는지 확인

### 미션이 너무 빨리 완료됨
- `waypoint_tolerance` 파라미터 증가
- AUV가 웨이포인트에 도달하는지 확인: 터미널 로그 모니터링

### RViz와 Stonefish가 일치하지 않음
- 이것은 예상된 동작입니다 - 서로 다른 좌표계 사용
- 좌표 변환은 자동으로 처리됩니다
- 경로 추적은 RViz 시각화를 신뢰하세요

## 예상 동작

1. AUV가 (0, 0, 3)에서 시작하여 WP1을 향함
2. (10, 0, 3)로 이동 - WP1 도달 시 반투명으로 변경
3. 회전하여 (10, 10, 3)로 이동 - WP2
4. 회전하여 (0, 10, 3)로 이동 - WP3
5. 시작점 (0, 0, 3)로 복귀 - 미션 완료
6. AUV가 정지하고 최종 위치에 유지

총 미션 거리: 약 40미터 (10x10m 정사각형 둘레)
예상 소요 시간: 제어 파라미터에 따라 2-3분

## 시각화 토픽

- `/waypoint_nav/visualization_markers`: 웨이포인트, AUV 위치, 헤딩 마커
- `/waypoint_nav/planned_path`: 계획된 경로 (주황색 선)
- `/waypoint_nav/traveled_path`: 실제 주행 경로 (청록색 선)

## 제어 파라미터 조정

더 나은 성능을 위해 런치 파일에서 제어 스케일을 조정할 수 있습니다:

```python
# src/eroas_navigation/launch/girona500_waypoint_test.launch.py
cmd_vel_to_thrusters_node = Node(
    ...
    parameters=[
        {'surge_scale': 1.0},   # 전진/후진 (증가 = 더 빠름)
        {'sway_scale': 1.0},    # 좌우 이동
        {'heave_scale': 3.0},   # 상하 이동
        {'yaw_scale': 0.5}      # 회전 (증가 = 더 빠른 회전)
    ],
)
```

## 기존 테스트와의 차이점

| 특징 | 기본 테스트 | 웨이포인트 테스트 |
|------|------------|-----------------|
| 목표점 수 | 1개 (고정) | 4개 (커스터마이징 가능) |
| 경로 | 직선 | 정사각형 (또는 커스텀) |
| 시각화 | 시작/목표/현재 | 모든 WP + 경로 추적 |
| 자동 전환 | 없음 | 웨이포인트 도달 시 자동 |
| 미션 완료 | 목표 도달 | 모든 WP 방문 후 |

## 다음 단계

1. **장애물 회피 추가**: SPD2C + SCG + ST-CBF 통합
2. **동적 경로 계획**: 실시간 경로 재계획
3. **FLS 센서 통합**: Sonar 데이터 기반 장애물 감지
4. **성능 최적화**: PID 튜닝, 속도 프로파일 개선