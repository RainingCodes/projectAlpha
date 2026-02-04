# ProjectAlpha - Stonefish AUV 시뮬레이션 테스트 가이드

## 개요

Ubuntu 24.04 + ROS2 Jazzy + Stonefish 1.6 시뮬레이터 환경에서 Girona500 AUV 시뮬레이션을 테스트한다.
EROAS (Efficient Reactive Obstacle Avoidance System) 내비게이션과 FLS (Forward Looking Sonar) 센서를 사용한다.

---

## 사전 준비

### 환경 설정

```bash
# ROS2 Jazzy 설정
source /opt/ros/jazzy/setup.bash
source ~/projectAlpha_source/projectAlpha/install/setup.bash

# NVIDIA GPU 가속 (FLS Compute Shader 필수)
export __NV_PRIME_RENDER_OFFLOAD=1
export __GLX_VENDOR_LIBRARY_NAME=nvidia
```

위 환경 변수는 `~/.bashrc`에 이미 설정되어 있어야 한다.

### GPU 확인

```bash
# NVIDIA GPU가 사용되는지 확인 (llvmpipe 아님)
glxinfo | grep "OpenGL renderer"
# Expected: OpenGL renderer string: NVIDIA GeForce RTX 3060 Ti/...
# Bad:      OpenGL renderer string: llvmpipe (LLVM ...)
```

FLS 센서는 OpenGL 4.3+ Compute Shader가 필요하다. 소프트웨어 렌더링 (llvmpipe)은 성능 문제를 유발한다.

### 빌드

MVP 관련 패키지는 현재 사용하지 않으므로 임시로 빌드에서 제외한다.
Stonefish가 먼저 빌드/설치되어야 `stonefish_ros2`가 빌드 가능하다.

```bash
# 1) Stonefish 먼저 빌드/설치
cd ~/projectAlpha_source/projectAlpha/stonefish
mkdir -p build && cd build
cmake .. -DCMAKE_INSTALL_PREFIX=/usr/local -DGRAPHICS=ON
make -j$(nproc)
sudo make install

# 2) ROS2 패키지 빌드 (MVP 스킵)
cd ~/projectAlpha_source/projectAlpha
colcon build --symlink-install --packages-skip mvp_control mvp_mission mvp_msgs
source install/setup.bash
```

---

## 수동 시작 모드 (화면 녹화용)

모든 테스트는 기본적으로 시뮬레이터 실행 즉시 AUV가 주행을 시작한다.
화면 세팅 후 녹화를 시작하고 싶다면 `auto_start:=false` 옵션을 사용한다.

### 사용법

```bash
# Terminal 1: 시뮬레이션 실행 (AUV 대기 상태)
ros2 launch eroas_navigation girona500_fls_obstacle_course.launch.py auto_start:=false

# (화면 배치, 녹화 시작 등 준비)

# Terminal 2: 내비게이션 시작
ros2 service call /waypoint_nav/start std_srvs/srv/Trigger
```

### 서비스 명령

| 테스트 | 시작 명령 | 정지 명령 |
|--------|----------|----------|
| Waypoint Test | `ros2 service call /waypoint_nav/start std_srvs/srv/Trigger` | `ros2 service call /waypoint_nav/stop std_srvs/srv/Trigger` |
| FLS Obstacle Course | `ros2 service call /waypoint_nav/start std_srvs/srv/Trigger` | `ros2 service call /waypoint_nav/stop std_srvs/srv/Trigger` |
| EROAS Test | `ros2 service call /eroas/start std_srvs/srv/Trigger` | `ros2 service call /eroas/stop std_srvs/srv/Trigger` |
| FLS Test | `ros2 service call /eroas/start std_srvs/srv/Trigger` | `ros2 service call /eroas/stop std_srvs/srv/Trigger` |

`auto_start:=false`를 지정하지 않으면 기존처럼 즉시 주행을 시작한다.
주행 중에도 `/stop` 서비스를 호출하면 AUV가 정지하고, `/start`로 다시 재개할 수 있다.

---

## 테스트 시나리오

### 1. 웨이포인트 내비게이션 테스트 (`girona500_waypoint_test`)

**목적**: 장애물이 없는 환경에서 AUV 기본 웨이포인트 내비게이션, 수심 제어, 헤딩 제어 확인.

**시나리오**: `waypoint_test.scn` - 개방 수역, 장애물 없음.

**기본 웨이포인트**: 수심 3m에서 10m x 10m 사각형.
- (0, 0, 3) -> (10, 0, 3) -> (10, 10, 3) -> (0, 10, 3) (NED 좌표)

**실행 명령**:
```bash
ros2 launch eroas_navigation girona500_waypoint_test.launch.py
```

**커스텀 웨이포인트**:
```bash
ros2 launch eroas_navigation girona500_waypoint_test.launch.py \
    waypoint_x:='[0.0, 20.0, 20.0, 0.0]' \
    waypoint_y:='[0.0, 0.0, 20.0, 20.0]' \
    waypoint_z:='[3.0, 3.0, 3.0, 3.0]' \
    waypoint_tolerance:='2.0'
```

**검증 항목**:
| 항목 | 확인 방법 |
|------|----------|
| 수심 제어 | AUV가 목표 수심(3m)을 유지 - sensor_monitor xterm 확인 |
| 헤딩 제어 | AUV가 각 웨이포인트로 순차적으로 회전 |
| 웨이포인트 도착 | 로그 출력: "Reached waypoint N" |
| 경로 추적 | rviz: 주황색 "Vehicle Path"가 계획된 웨이포인트를 따름 |
| 계획 경로 | rviz: 주황색 "Planned Path"에 웨이포인트 연결 표시 |
| 이동 경로 | rviz: Cyan "Traveled Path" (waypoint_navigator) |

**실행 노드**:
- `stonefish_simulator` - 물리 시뮬레이션
- `cmd_vel_to_thrusters` - 속도 명령 -> 추진기 매핑
- `waypoint_navigator` - 웨이포인트 추종 로직
- `odom_to_tf` - Odometry -> TF 브릿지
- `robot_state_publisher` - URDF TF 퍼블리시
- `sensor_monitor` - 센서 데이터 모니터링 (xterm 창)
- `path_publisher` - rviz 경로 표시
- `rviz2` - 시각화 (waypoint_navigation.rviz)

---

### 2. EROAS 내비게이션 테스트 (`girona500_eroas`)

**목적**: 장애물이 없는 환경에서 EROAS 단일 목표 내비게이션 테스트. 기본 내비게이션 컨트롤러(헤딩 + 수심 + 전진) 확인.

**시나리오**: `console_test.scn` - 기본 환경, 장애물 없음.

**기본 목표**: (10, 10, 3) NED 좌표 (북쪽 10m, 동쪽 10m, 수심 3m).

**실행 명령**:
```bash
ros2 launch eroas_navigation girona500_eroas.launch.py
```

**커스텀 목표**:
```bash
ros2 launch eroas_navigation girona500_eroas.launch.py \
    goal_x:=20.0 goal_y:=0.0 goal_z:=5.0
```

**검증 항목**:
| 항목 | 확인 방법 |
|------|----------|
| 목표 내비게이션 | AUV가 (10,10) 방향으로 수심 3m 유지 |
| 헤딩 계산 | 로그: 목표 방향으로 헤딩 변화 |
| 수심 제어 | AUV가 수심 3m 도달 및 유지 |
| 목표 도착 | 로그: "Goal reached!" (허용 오차 1.0m 이내) |
| 경로 추적 | rviz: 주황색 "Vehicle Path" 실제 궤적 |
| 계획 경로 | rviz: 초록색 "Planned Path" (EROAS 노드) |
| AUV 마커 | rviz: AUV 위치/헤딩 마커 |

**실행 노드**:
- `stonefish_simulator` - 물리 시뮬레이션
- `cmd_vel_to_thrusters` - 속도 명령 -> 추진기 매핑
- `eroas_node` - EROAS 내비게이션 컨트롤러
- `odom_to_tf` - Odometry -> TF 브릿지
- `robot_state_publisher` - URDF TF 퍼블리시
- `sensor_monitor` - 센서 데이터 모니터링 (xterm 창)
- `path_publisher` - rviz 경로 표시
- `rviz2` - 시각화 (eroas_navigation.rviz)

**참고**: EROAS 장애물 회피 모듈 (SPD2C, SCG, ST-CBF)은 `eroas_node.py`에 구현되어 있으나 현재 주석 처리되어 있음. FLS 통합 완료 후 활성화 예정.

---

### 3. FLS 테스트 (`girona500_fls_test`)

**목적**: FLS 센서 동작, 장애물 감지 시각화, FLS 데이터 기반 EROAS 내비게이션 테스트. FLS 센서 검증의 핵심 테스트.

**시나리오**: `fls_test.scn` - 경로 상 장애물 배치.

**기본 목표**: (20, 0, 3) NED 좌표 (전방 20m, 수심 3m).

**실행 명령**:
```bash
ros2 launch eroas_navigation girona500_fls_test.launch.py
```

**커스텀 목표**:
```bash
ros2 launch eroas_navigation girona500_fls_test.launch.py \
    goal_x:=30.0 goal_y:=5.0 goal_z:=3.0
```

**검증 항목**:
| 항목 | 확인 방법 |
|------|----------|
| FLS 데이터 발행 | `ros2 topic hz /GIRONA500/fls/image` (약 5 Hz) |
| FLS 해상도 | `ros2 topic echo /GIRONA500/fls/image --once` (64x64, 8UC1) |
| FLS 뷰어 | 초록색 소나 팬 디스플레이 창 (V자, 아래로 펼침) |
| 장애물 감지 | 장애물 접근 시 팬 디스플레이에 밝은 점 |
| FLS 수평 스캔 | 팬 디스플레이는 좌우(Port-Starboard) 스캔, 상하 스캔 아님 |
| 내비게이션 | AUV가 목표 방향으로 직진, 수심 유지 |
| 경로 추적 | rviz: 주황색 "Vehicle Path" 실제 궤적 |
| FLS 기록 | `/tmp/fls_data/`에 데이터 저장 (record_enabled 시) |

**실행 노드**:
- `stonefish_simulator` - 물리 시뮬레이션
- `cmd_vel_to_thrusters` - 속도 명령 -> 추진기 매핑
- `eroas_node` - EROAS 내비게이션 컨트롤러
- `odom_to_tf` - Odometry -> TF 브릿지
- `robot_state_publisher` - URDF TF 퍼블리시
- `sensor_monitor` - 센서 데이터 모니터링 (xterm 창)
- `fls_viewer` - Polar 팬 소나 디스플레이 (OpenCV 창)
- `fls_recorder` - FLS 데이터 디스크 기록
- `path_publisher` - rviz 경로 표시
- `rviz2` - 시각화 (eroas_navigation.rviz)

**FLS 센서 파라미터** (`girona500_robot.scn` 기준):
- Beams: 64 (방위각 해상도)
- Bins: 64 (거리 해상도)
- 수평 FOV: 90 deg (좌우 스캔)
- 수직 FOV: 20 deg (상하 범위)
- Range: 1.0 - 10.0 m
- Rate: 5 Hz
- Orientation: rpy="1.5708 0.0 -1.5708" (전방 지향, 수평 스캔)

---

### 4. FLS 장애물 코스 테스트 (`girona500_fls_obstacle_course`)

**목적**: 계곡/골목 형태의 환경에서 웨이포인트를 따라 주행하면서 FLS 소나가 양쪽 벽면을 지속적으로 감지하는지 검증. FLS 데이터가 실시간으로 안정적으로 수신되는지 확인하는 것이 핵심.

**시나리오**: `fls_obstacle_course.scn` - 두 개의 계곡 구간 + 전환 구간.

**경로** (NED 좌표):
```
Start(0,0,3) → [Canyon 1] → WP1(18,0,3) → [Turn] → WP2(23,3,3) → WP3(28,5,3) → [Canyon 2] → Goal(42,5,3)
```

**장애물 배치**:
| 구간 | 위치 (NED) | 형태 | 설명 |
|------|-----------|------|------|
| Canyon 1 | x=3~18, y=±3.5 | 박스 벽 6개 | 폭 6m 직선 협곡, 양쪽 벽면 (높이 6m) |
| 전환 구간 | x=18~28 | 실린더 기둥 4개 | 넓은 공간에서 안내 기둥을 따라 우회전 |
| Canyon 2 | x=28~42, y=1.5/8.5 | 박스 벽 6개 | 폭 6m 직선 협곡, y=5 중심 |
| 바닥 암석 | 각 협곡 내부 | 구 4개 | 바닥에 작은 암석 (변화 감지용) |

**FLS 감지 특성**:
- 벽이 경로 중심에서 **~3m** 거리 → FLS 범위(1~10m) 안에서 **항상 감지**
- 협곡 통과 시 FLS 팬 디스플레이 양쪽에 벽면 반사가 지속 표시
- 전환 구간에서 큰 기둥(r=0.8~1.2m)이 FLS에 뚜렷하게 감지

**실행 명령**:
```bash
ros2 launch eroas_navigation girona500_fls_obstacle_course.launch.py
```

**검증 항목**:
| 항목 | 확인 방법 |
|------|----------|
| 양쪽 벽면 감지 | FLS 뷰어에서 팬 좌우에 벽면 반사가 지속 표시 |
| 실시간 갱신 | 이동에 따라 벽면 반사 패턴이 자연스럽게 변화 |
| 전환 구간 기둥 감지 | 회전 시 기둥이 FLS에 뚜렷한 밝은 점으로 표시 |
| 바닥 암석 감지 | 협곡 바닥 암석이 하단에 미약한 반사로 표시 |
| 경로 추종 | rviz: 주황색 "Vehicle Path"가 웨이포인트를 순차 추종 |
| 웨이포인트 도착 | 로그: "Reached waypoint N" |
| FLS 기록 | `/tmp/fls_obstacle_course/`에 데이터 저장 |

**실행 노드**:
- `stonefish_simulator` - 물리 시뮬레이션
- `cmd_vel_to_thrusters` - 속도 명령 -> 추진기 매핑
- `waypoint_navigator` - 웨이포인트 추종 로직
- `odom_to_tf` - Odometry -> TF 브릿지
- `robot_state_publisher` - URDF TF 퍼블리시
- `sensor_monitor` - 센서 데이터 모니터링 (xterm 창)
- `fls_viewer` - Polar 팬 소나 디스플레이 (OpenCV 창, 400x400)
- `fls_recorder` - FLS 데이터 기록
- `path_publisher` - rviz 경로 표시
- `rviz2` - 시각화 (waypoint_navigation.rviz)

---

## 공통 디버깅 명령

### 토픽 모니터링

```bash
# 활성 토픽 목록
ros2 topic list

# FLS 데이터 속도 확인
ros2 topic hz /GIRONA500/fls/image

# Odometry 데이터 확인
ros2 topic echo /GIRONA500/dynamics --once

# 차량 속도 명령 확인
ros2 topic echo /GIRONA500/cmd_vel --once

# 추진기 세트포인트 확인
ros2 topic echo /GIRONA500/ThrusterSurgePort/setpoint
```

### TF 트리

```bash
# TF 트리 구조 확인
ros2 run tf2_tools view_frames

# 특정 TF 확인
ros2 run tf2_ros tf2_echo world_ned GIRONA500/Vehicle
```

### 노드 모니터링

```bash
# 실행 중 노드 목록
ros2 node list

# 노드 파라미터 확인
ros2 param list /eroas_node
ros2 param get /eroas_node goal_x
```

---

## rviz 통합 뷰 설정

모든 테스트 시나리오는 동일한 rviz 설정을 사용한다.

| 파라미터 | 값 |
|-----------|-------|
| Fixed Frame | `world_ned` |
| View Type | Orbit |
| Distance | 60 |
| Focal Point | (5, 5, -3) |
| Pitch | 1.5708 (90 deg, 수직 탑뷰) |
| Yaw | -1.5708 (-90 deg) |
| Invert Z Axis | false |
| Background | 48; 48; 48 |
| Grid Plane Cell Count | 100 |

### 테스트별 rviz 디스플레이

| Display | Waypoint Test | EROAS Test | FLS Test | FLS Obstacle Course |
|---------|:---:|:---:|:---:|:---:|
| Grid | O | O | O | O |
| TF | O | O | O | O |
| Waypoint Markers | O | - | - | O |
| EROAS Markers | - | O | O | - |
| Planned Path | O | O | O | O |
| Traveled Path | O | - | - | O |
| Vehicle Path (path_publisher) | O | O | O | O |

**Vehicle Path** (`/GIRONA500/path`): `path_publisher` 노드의 주황색 경로. NED->ENU 변환이 적용된 실제 궤적을 표시한다.

---

## 좌표계 참고

### NED (North-East-Down) 기준
- Stonefish 시뮬레이터는 NED 좌표계를 사용한다.
- X = North, Y = East, Z = Down (양수 = 더 깊은 곳)
- 수중 로봇 표준 좌표계

### rviz 시각화 기준
- rviz는 ENU 유사 좌표계를 사용한다.
- 시각화 노드(eroas_node 마커, path_publisher)는 NED->ENU 변환을 적용한다.
  - rviz X = NED Y (East)
  - rviz Y = NED X (North)
  - rviz Z = -NED Z (Up)
- rviz 고정 프레임은 `world_ned`를 사용하지만 코드에서 좌표를 교환한다.

---

## FLS 센서 기술 상세

### Stonefish FLS 방향
- Stonefish FLS 기본 센서 시야 방향: +Z 축, Up 방향: -Y 축
- 로봇 설정 `rpy="1.5708 0.0 -1.5708"` 변환:
  - 센서 Z(시야) -> 차량 -X (Girona500 전방)
  - 센서 X(수평 스캔) -> 차량 -Y (좌현 방향)
  - 센서 Y(Up) -> 차량 +Z (하방)
- 결과: 전방을 보면서 수평 좌우 스캔

### FLS 뷰어 표시
- 부채꼴 팬 형태 (V자, 아래로 펼침)
- 초록색 소나 스타일 컬러맵
- 2m 간격 거리 링 (1-10m 범위)
- 90도 FOV 경계선 표시
- 창 크기 (display_size, 기본 400px) 및 위치 (window_x, window_y) 파라미터 지원

### FLS 토픽
- `/GIRONA500/fls/image` - 원시 소나 데이터 (64x64, 8UC1)
- `/GIRONA500/fls/display` - 컬러 디스플레이 이미지 (rgb8)

---

## 패키지 구조

```
eroas_navigation/
  eroas_navigation/
    eroas_node.py            - EROAS 내비게이션 컨트롤러
    cmd_vel_to_thrusters.py  - 속도 -> 추진기 변환
    waypoint_navigator.py    - 다중 웨이포인트 내비게이터
    fls_viewer.py            - Polar 팬 FLS 디스플레이
    fls_recorder.py          - FLS 데이터 기록
    path_publisher.py        - 차량 궤적 퍼블리셔
  launch/
    girona500_eroas.launch.py         - EROAS 단일 목표 내비게이션
    girona500_fls_test.launch.py              - FLS 센서 + EROAS 내비게이션
    girona500_fls_obstacle_course.launch.py  - FLS 장애물 코스 (웨이포인트 추종)
    girona500_waypoint_test.launch.py        - 다중 웨이포인트 내비게이션
  config/
    eroas_navigation.rviz       - EROAS/FLS 테스트용 rviz 설정
    waypoint_navigation.rviz    - 웨이포인트 테스트용 rviz 설정

stonefish_ros2/
  data/
    girona500_robot.scn    - 로봇 정의 (센서, 액추에이터, 물리)
  scenarios/
    console_test.scn       - 기본 환경 (EROAS 테스트)
    waypoint_test.scn      - 개방 수역 (웨이포인트 테스트)
    fls_test.scn               - 장애물 환경 (FLS 테스트)
    fls_obstacle_course.scn    - 복합 장애물 코스 (FLS 장애물 코스 테스트)
```

---

## 알려진 이슈 및 상태

1. **EROAS 장애물 회피**: SPD2C (갭 탐색), SCG (장애물 기억), ST-CBF (안전 필터링) 모듈은 `eroas_node.py`에 구현되어 있으나 현재 주석 처리되어 있음. FLS 통합 완료 후 활성화 필요.

2. **eroas_node의 FLS 통합**: FLS 토픽 구독이 주석 처리되어 있음 (TODO). FLS 센서는 정상 발행되지만, eroas_node는 아직 장애물 회피에 사용하지 않음.

3. **Shader 경고**: Stonefish 출력에 "Trying to use invalid shader!" 경고가 나타날 수 있음. 디버그 레벨 메시지이며 FLS 데이터 생성에는 영향 없음.

4. **성능**: NVIDIA GPU에서 64x64 / 5Hz FLS 설정은 정상 동작해야 한다. 더 높은 해상도(128x128+) 또는 속도(20Hz+)는 시스템 불안정을 유발할 수 있다.

5. **Stonefish 카메라 사전설정**: Stonefish 시뮬레이터의 카메라 뷰(수직 탑뷰, 로봇 추적)는 시나리오 XML에서 설정할 수 없다. C++ 코드(`ROS2SimulationManager`)에서 `OpenGLTrackball` 및 `GlueToMoving()` API를 통해 프로그래밍 방식으로만 변경 가능하다. 현재는 시뮬레이터 실행 후 수동으로 뷰를 조정해야 한다. FLS 센서 디스플레이 오버레이는 시나리오 XML에 `<display colormap="hot"/>` 추가로 활성화 가능하다.
