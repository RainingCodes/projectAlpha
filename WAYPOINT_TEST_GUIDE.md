# Girona500 Waypoint Following Test Guide

## 개요
이 가이드는 Girona500 AUV가 미리 정의된 waypoint 경로를 따라가는 테스트를 수행하는 방법을 설명합니다.

## 현재 설정된 경로
정사각형 경로 (10m x 10m, 수심 3m):
```
(0,0,-3) → (10,0,-3) → (10,10,-3) → (0,10,-3) → (0,0,-3)
```

## 실행 방법

### 1. RViz와 함께 시스템 시작
```bash
cd ~/projectAlpha
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch stonefish_ros2 girona500_mvp_rviz.launch.py
```

**실행되는 것들:**
- Stonefish 시뮬레이터 (3D 시각화)
- MVP Control (제어 시스템)
- MVP Helm (미션 관리)
- RViz2 (경로 시각화)
- Robot Trail Publisher (궤적 기록)

### 2. Survey 모드 활성화 (Waypoint Following 시작)

새 터미널을 열어서:
```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 run stonefish_ros2 mission_commander.py survey
```

또는 직접 토픽으로:
```bash
ros2 topic pub /GIRONA500/mvp_helm/change_state_caller std_msgs/String "data: 'survey'" --once
```

### 3. Teleop 모드로 전환 (수동 제어)
```bash
ros2 run stonefish_ros2 mission_commander.py teleop
```

또는:
```bash
ros2 topic pub /GIRONA500/mvp_helm/change_state_caller std_msgs/String "data: 'teleop'" --once
```

### 4. 시스템 정지
```bash
ros2 run stonefish_ros2 mission_commander.py kill
```

또는:
```bash
ros2 topic pub /GIRONA500/mvp_helm/change_state_caller std_msgs/String "data: 'kill'" --once
```

## RViz에서 보이는 것들

### 시각화 요소
1. **TF Frames** (좌표계)
   - `world_ned`: 전역 좌표계
   - `GIRONA500/base_link`: 로봇 본체
   - `GIRONA500/thruster_*`: 추진기들

2. **Robot Trail** (빨간색 선)
   - 로봇이 지나온 경로 표시
   - 최대 1000개 포즈 저장

3. **Path** (초록색 선)
   - MVP가 계획한 경로
   - `/GIRONA500/path_following/trajectory` 토픽

4. **Waypoints** (구체)
   - 목표 waypoint들
   - `/GIRONA500/path_following/waypoints` 토픽

5. **Vehicle Axes**
   - 로봇의 현재 자세 (X: 빨강, Y: 초록, Z: 파랑)

6. **Grid**
   - 바닥면 참조용 격자

## 카메라 조작 (RViz)
- **회전**: 마우스 왼쪽 버튼 드래그
- **팬**: Shift + 마우스 왼쪽 버튼 드래그
- **줌**: 마우스 휠
- **Reset**: View → Reset View

## 상태 모니터링

### 현재 상태 확인
```bash
ros2 topic echo /GIRONA500/helm/state
```

### 로봇 위치 확인
```bash
ros2 topic echo /GIRONA500/dynamics_fixed --field pose.pose.position
```

### 추력 명령 확인
```bash
ros2 topic echo /GIRONA500/ThrusterSurgePort/setpoint
```

### 제어 모드 확인
```bash
ros2 topic echo /GIRONA500/mvp_control/control_mode
```

## 경로 수정

경로를 변경하려면 `src/stonefish_ros2/config/girona500_helm.yaml` 파일을 수정:

```yaml
behaviors:
  bhv_path:
    plugin: helm/PathFollowing
    priority:
      survey: 2
    waypoints:
      frame_id: GIRONA500/world_ned
      points:
        - {x: 0.0, y: 0.0, z: -5.0}    # 시작점
        - {x: 20.0, y: 0.0, z: -5.0}   # 새 waypoint 추가
        - {x: 20.0, y: 20.0, z: -5.0}  # 크기 변경 가능
        # ... 원하는 만큼 추가
```

수정 후 재빌드:
```bash
colcon build --packages-select stonefish_ros2
```

## 트러블슈팅

### 로봇이 움직이지 않음
1. Helm 상태 확인: `ros2 topic echo /GIRONA500/helm/state`
2. Survey 모드 활성화 확인
3. MVP Control 로그 확인

### RViz에 경로가 안 보임
1. Path 토픽 확인: `ros2 topic list | grep path`
2. MVP Helm이 실행 중인지 확인
3. RViz Display 패널에서 Path/Waypoints 체크

### 경로를 벗어남
1. PID 게인 튜닝 필요 (`girona500_control_modes.yaml`)
2. 제어 주파수 확인
3. 추진기 한계값 확인

## 고급 기능

### 실시간 PID 튜닝
```bash
ros2 run rqt_reconfigure rqt_reconfigure
```

### 데이터 플로팅
```bash
ros2 run plotjuggler plotjuggler
```

### TF 트리 시각화
```bash
ros2 run tf2_tools view_frames
evince frames.pdf
```

## 예제 미션 시나리오

### 1. 간단한 직선 경로
```yaml
points:
  - {x: 0.0, y: 0.0, z: -3.0}
  - {x: 15.0, y: 0.0, z: -3.0}
```

### 2. 삼각형 경로
```yaml
points:
  - {x: 0.0, y: 0.0, z: -4.0}
  - {x: 10.0, y: 0.0, z: -4.0}
  - {x: 5.0, y: 8.66, z: -4.0}
  - {x: 0.0, y: 0.0, z: -4.0}
```

### 3. 깊이 변화 경로
```yaml
points:
  - {x: 0.0, y: 0.0, z: -2.0}
  - {x: 10.0, y: 0.0, z: -5.0}
  - {x: 10.0, y: 10.0, z: -3.0}
  - {x: 0.0, y: 10.0, z: -2.0}
```

## 참고 사항
- NED 좌표계 사용 (North-East-Down)
- Z축: 음수 = 수중 (예: -3.0 = 수심 3m)
- 단위: 미터 (m)
- Waypoint 도달 허용 오차: 설정에 따라 다름 (기본 ~0.5m)

## 문제 신고
문제가 발생하면 다음 정보와 함께 문의:
1. ROS2 버전
2. 에러 로그
3. `ros2 topic list` 출력
4. `ros2 node list` 출력