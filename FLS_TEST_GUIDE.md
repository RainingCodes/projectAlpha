# FLS (Forward Looking Sonar) Test Guide

## 개요
이 가이드는 FLS 센서를 사용한 장애물 감지 테스트 환경을 설명합니다.

## 테스트 환경 구성

### 경로
- **시작점**: (0, 0, 3) - NED 좌표, 수심 3m
- **목표점**: (20, 0, 3) - 20m 직선 경로
- **주행 방향**: 정북향 (North)

### 장애물
테스트 경로의 중간 지점(10m 지점)에 좌우로 장애물 배치:

1. **왼쪽 장애물** (ObstacleLeft)
   - 위치: (10, -3, 3) - 경로에서 왼쪽으로 3m
   - 형태: 높이 4m, 반지름 1m의 원기둥
   - 재질: 콘크리트 (회색)

2. **오른쪽 장애물** (ObstacleRight)
   - 위치: (10, 3, 3) - 경로에서 오른쪽으로 3m
   - 형태: 높이 4m, 반지름 1m의 원기둥
   - 재질: 콘크리트 (회색)

### 시각적 마커
- **시작점 마커**: 노란색 구체 (공중 1m, 수면 위)
- **목표점 마커**: 빨간색 구체 (공중 1m, 수면 위)

## 현재 상태

✅ **Phase 1: 환경 구축 (완료)**
- 테스트 시나리오 파일 생성 (fls_test.scn)
- 직선 경로 설정
- 좌우 장애물 배치
- 시작/목표 마커 설정
- 런치 파일 생성 (girona500_fls_test.launch.py)

✅ **Phase 2: 센서 설정 (완료 - WSL2에서 설정만 완료)**
- Girona500에 FLS 센서 추가 및 설정
- FLS 방향: 전방 향함, 가로로 넓게 스캔
- Front Camera 추가 (전방 향함)
- FLS 데이터 시각화 노드 생성 (fls_viewer.py)
- FLS 데이터 기록 노드 생성 (fls_recorder.py)
- 런치 파일에 FLS/Camera 관련 노드 추가

⚠️ **WSL2 제한사항**:
- FLS 센서가 올바르게 파싱되고 시각적 더미는 표시됨
- 하지만 WSL2의 GPU/OpenGL 제한으로 실제 데이터는 발행되지 않음 (Publisher count = 0)
- FLS는 GPU compute shader가 필요하나 WSL2의 MESA/ZINK 스택이 미지원
- **해결 방법**: 네이티브 Ubuntu 환경에서 테스트 필요

## 센서 사양

### FLS (Forward Looking Sonar)
- **위치**: xyz="-0.75 0.0 0.0" (선체 전면부)
- **방향**: rpy="0.0 -1.5708 0.0" (전방 향함)
- **FOV 설정**:
  - horizontal_fov="20.0" (물리적으로는 상하 방향)
  - vertical_fov="90.0" (물리적으로는 좌우 방향)
  - *주의: FOV 값을 스왑하여 실제 가로 스캔 구현*
- **해상도**:
  - beams="64" (빔 수)
  - bins="64" (거리 해상도)
- **탐지 범위**: 1.0m ~ 10.0m
- **업데이트 주파수**: 5 Hz
- **토픽**: `/GIRONA500/fls`

### Front Camera
- **위치**: xyz="-0.75 0.0 -0.1" (FLS 바로 위)
- **방향**: rpy="0.0 -1.5708 0.0" (전방 향함)
- **해상도**: 800x600
- **시야각**: 60도 (horizontal_fov)
- **업데이트 주파수**: 10 Hz
- **토픽**: `/GIRONA500/front_camera`

### 기타 센서
- **DVL**: 속도 및 고도 측정
- **IMU**: 자세 및 각속도
- **Pressure**: 수심 측정
- **GPS**: 수면 위치 측정
- **Odometry**: 실제 동역학 상태

## 최적화 설정

리소스 절약을 위한 설정:
- **Ocean 시뮬레이션**: 활성화 (파도 높이 0.0)
- **FLS 해상도**: 64x64 (GPU 부하 감소)
- **FLS 주파수**: 5 Hz (계산량 감소)
- **초기 카메라**: 줌 아웃 뷰 (전체 씬 보기)

## 실행 방법

### WSL2 환경 (현재 - 설정 확인용)

WSL2에서는 FLS 데이터가 실제로 발행되지 않지만, 설정 검증 및 시각적 확인은 가능합니다.

#### 1. 빌드
```bash
cd /home/foc/projectAlpha
colcon build --packages-select stonefish_ros2 eroas_navigation
source install/setup.bash
```

#### 2. 테스트 실행
```bash
ros2 launch eroas_navigation girona500_fls_test.launch.py
```

#### 3. 확인 사항

**Stonefish 시뮬레이터**:
- [x] AUV가 (0, 0, 3)에서 시작
- [x] 노란색 시작 마커가 수면 위에 보임
- [x] 빨간색 목표 마커가 20m 전방에 보임
- [x] 경로 중간(10m 지점)에 좌우 장애물(회색 원기둥) 보임
- [x] FLS 센서 시각적 더미가 전방을 향하고 가로로 넓게 표시됨
- [x] Front Camera가 전방을 향함
- [ ] AUV가 직선으로 전진 (EROAS 노드 활성화 시)

**RViz**:
- [x] 계획된 경로 표시 (시작 → 목표)
- [x] AUV 위치 및 헤딩 표시
- [x] TF 프레임 표시

**토픽 확인**:
```bash
# FLS 토픽 존재 확인
ros2 topic list | grep fls
# 출력: /GIRONA500/fls

# Publisher 확인 (WSL2에서는 0)
ros2 topic info /GIRONA500/fls
# Publisher count: 0 (WSL2 제한)

# Camera 토픽 확인
ros2 topic list | grep front_camera
# 출력: /GIRONA500/front_camera (정상 작동)
```

**Parser 로그 확인**:
```bash
# FLS가 올바르게 파싱되는지 확인
grep -i fls ~/.ros/log/latest/stonefish_simulator_node-*.log
# 출력 예: [WARN] Noise of sensor 'GIRONA500/fls' not defined - using defaults.
```

### 네이티브 Ubuntu 환경 (권장 - 실제 테스트용)

FLS 센서가 실제로 작동하려면 네이티브 Ubuntu 환경이 필요합니다.

#### 시스템 요구사항
- **OS**: Ubuntu 22.04 또는 20.04
- **GPU**: OpenGL 4.3+ 및 Compute Shader 지원 GPU
  - NVIDIA: GTX 600 시리즈 이상
  - AMD: GCN 1.0 이상
  - Intel: HD Graphics 4000 이상
- **드라이버**:
  - NVIDIA: proprietary driver 설치
  - AMD: Mesa 22.0+ 또는 AMDGPU-PRO
- **ROS2**: Humble 또는 Foxy

#### 환경 이전 방법

1. **코드 이전**
```bash
# WSL2에서 코드 압축
cd /home/foc
tar -czf projectAlpha.tar.gz projectAlpha/

# Ubuntu 환경으로 복사 (USB, scp, git 등 사용)
# Ubuntu에서 압축 해제
tar -xzf projectAlpha.tar.gz
cd projectAlpha
```

2. **의존성 설치**
```bash
# ROS2 Humble 설치 (Ubuntu 22.04)
sudo apt update
sudo apt install ros-humble-desktop

# Stonefish 의존성
sudo apt install -y \
    libglm-dev \
    libsdl2-dev \
    libfreetype6-dev \
    libopenal-dev

# Python 의존성
pip3 install opencv-python numpy
```

3. **빌드 및 실행**
```bash
cd projectAlpha
source /opt/ros/humble/setup.bash
colcon build
source install/setup.bash

# 테스트 실행
ros2 launch eroas_navigation girona500_fls_test.launch.py
```

4. **FLS 데이터 확인 (네이티브 환경)**
```bash
# Publisher 확인 (1 이상이어야 정상)
ros2 topic info /GIRONA500/fls
# Publisher count: 1

# 실시간 데이터 수신 확인
ros2 topic hz /GIRONA500/fls
# average rate: 5.000

# FLS 이미지 확인
ros2 topic echo /GIRONA500/fls --once
```

**예상 결과**:
- [x] FLS 시각화 창에 실제 소나 이미지 표시
- [x] 장애물이 FLS 이미지에 밝은 반사로 나타남
- [x] 좌우 장애물이 소나 이미지의 양쪽에 표시
- [x] FLS Recorder가 데이터를 `/tmp/fls_data/`에 저장
- [x] Front Camera 영상 확인 가능

## 예상 동작

1. AUV가 (0,0,3)에서 시작하여 북쪽으로 전진
2. 10m 지점에서 좌우 3m 거리에 장애물 감지 가능
3. FLS가 장애물을 감지하여 소나 이미지에 표시
4. 장애물 사이(6m 간격)를 통과
5. 20m 지점의 목표점에 도달하여 정지

## 파일 구조

```
src/stonefish_ros2/
├── data/
│   └── girona500auv_console.scn          # FLS + Front Camera 설정
└── scenarios/
    └── fls_test.scn                      # FLS 테스트 시나리오

src/eroas_navigation/
├── eroas_navigation/
│   ├── fls_viewer.py                     # FLS 시각화 노드
│   ├── fls_recorder.py                   # FLS 데이터 기록 노드
│   ├── eroas_node.py                     # EROAS 메인 노드
│   └── cmd_vel_to_thrusters.py           # 추진기 제어 변환
└── launch/
    └── girona500_fls_test.launch.py      # FLS 테스트 런치 파일

FLS_TEST_GUIDE.md                         # 이 가이드 파일
```

## 좌표계 참고

### NED (Stonefish)
- X축: North (북쪽, 전진 방향)
- Y축: East (동쪽, 오른쪽)
- Z축: Down (아래, 수심 증가)

### 장애물 배치 시각화 (위에서 내려다본 모습)
```
        N (X축)
        ↑
        │
   -3m  │  +3m
    ●───┼───●     ← 10m 지점 (장애물)
    L   │   R
        │
    ○   │        ← 0m 지점 (시작)
        │
   20m  ●        ← 목표점
        │
        └──────→ E (Y축)

L: 왼쪽 장애물 (ObstacleLeft)
R: 오른쪽 장애물 (ObstacleRight)
○: 시작점 마커 (노란색)
●: 목표점 마커 (빨간색)
```

## FLS 데이터 확인 방법

### 토픽 확인
```bash
# FLS 토픽 확인
ros2 topic list | grep fls

# FLS 데이터 수신 확인 (네이티브 Ubuntu에서만 작동)
ros2 topic hz /GIRONA500/fls

# FLS 메시지 내용 확인
ros2 topic echo /GIRONA500/fls --once
```

### FLS 이미지 정보
FLS 이미지는 `sensor_msgs/Image` 타입으로 발행됩니다:
- **Encoding**: 32FC1 (32-bit float, single channel) 또는 8UC1
- **Width**: 64 pixels (빔 수)
- **Height**: 64 pixels (빈 수)
- **Frame ID**: GIRONA500/fls_link

### 예상 소나 이미지 (네이티브 환경)

장애물이 감지되면:
```
   좌측 장애물           우측 장애물
      ████                  ████
      ████                  ████
   ║  ████                  ████  ║
   ║  ████                  ████  ║ ← 10m 지점에서 강한 반사
   ║                              ║
   ║                              ║
   ╚══════════════════════════════╝
         AUV 전방 시야각 90도
```

## FLS 데이터 기록 및 맵핑

### 자동 데이터 기록

FLS Recorder 노드가 자동으로 다음 정보를 기록합니다 (네이티브 환경에서만):
- FLS 소나 이미지 (64x64 pixels)
- AUV 위치 (x, y, z)
- AUV 자세 (quaternion)
- 타임스탬프

**저장 위치**: `/tmp/fls_data/`
**파일 형식**: `fls_recording_YYYYMMDD_HHMMSS.pkl` (Python pickle)
**자동 저장**: 10초마다 자동 저장

### 기록된 데이터 로드 및 분석

```python
import pickle
import numpy as np
import matplotlib.pyplot as plt

# 데이터 로드
with open('/tmp/fls_data/fls_recording_20260203_123456.pkl', 'rb') as f:
    data = pickle.load(f)

print(f"Total frames: {data['metadata']['total_frames']}")

# 각 프레임 접근
for record in data['data']:
    timestamp = record['timestamp']
    pose = record['pose']
    fls_image = record['fls_data']

    print(f"Time: {timestamp:.2f}s, Position: ({pose['position']['x']:.2f}, "
          f"{pose['position']['y']:.2f}, {pose['position']['z']:.2f})")

    # FLS 이미지 시각화
    plt.imshow(fls_image, cmap='bone')
    plt.title(f'FLS at t={timestamp:.2f}s')
    plt.show()
```

### 맵핑을 위한 데이터 처리

기록된 FLS 데이터로 할 수 있는 작업:
1. **Occupancy Grid Map 생성**: FLS 반사 강도를 2D/3D 그리드에 투영
2. **SLAM (Simultaneous Localization and Mapping)**: 소나 데이터와 odometry 융합
3. **장애물 맵 구축**: 강한 반사 영역을 장애물로 분류
4. **경로 계획 검증**: 실제 주행 경로와 감지된 장애물 분석

### 수동 기록 제어

런치 파일에서 기록 비활성화:
```python
fls_recorder_node = Node(
    ...
    parameters=[
        {'record_enabled': False}  # 기록 끄기
    ],
)
```

또는 런치 시 파라미터로 제어:
```bash
ros2 launch eroas_navigation girona500_fls_test.launch.py record_enabled:=false
```

## 설정 과정 요약 (FLS 방향 문제 해결)

### 문제점
1. 초기: FLS가 후방을 향하고 있었음
2. pitch 조정 후: 전방을 향했으나 세로로 길게 스캔 (상하로 넓음)
3. roll 추가 시도: 센서가 오른쪽을 향하게 됨

### 최종 해결책
센서의 물리적 회전 대신 **FOV 파라미터를 스왑**:
- `horizontal_fov="20.0"` (물리적으로는 상하 방향, 좁게)
- `vertical_fov="90.0"` (물리적으로는 좌우 방향, 넓게)
- 결과: 센서가 전방을 향하면서 좌우로 넓게 스캔

### 설정 파일
[src/stonefish_ros2/data/girona500auv_console.scn](src/stonefish_ros2/data/girona500auv_console.scn)의 176-182라인:
```xml
<sensor name="fls" type="fls" rate="5.0">
    <link name="Vehicle"/>
    <origin xyz="-0.75 0.0 0.0" rpy="0.0 -1.5708 0.0"/>
    <specs beams="64" bins="64" horizontal_fov="20.0" vertical_fov="90.0"/>
    <settings range_min="1.0" range_max="10.0" gain="1.0"/>
    <ros_publisher topic="/$(arg robot_name)/fls"/>
</sensor>
```

## 다음 단계

### Phase 3: 네이티브 Ubuntu 환경 테스트 (다음 단계)

1. **환경 준비**
   - 네이티브 Ubuntu 22.04 설치
   - GPU 드라이버 설치 및 확인
   - ROS2 Humble 설치

2. **FLS 기능 검증**
   - FLS 데이터가 실제로 발행되는지 확인
   - 장애물 감지 성능 테스트
   - FLS 이미지 품질 확인

3. **데이터 수집**
   - FLS 데이터 기록
   - 다양한 시나리오에서 테스트
   - 장애물 감지 범위 및 정확도 측정

### Phase 4: EROAS 통합

1. **FLS 데이터를 EROAS 노드에 통합**
   - SPD2C: FLS 데이터로 장애물 감지
   - SCG: 장애물 메모리 업데이트
   - ST-CBF: 안전 제약 조건 적용

2. **장애물 회피 테스트**
   - AUV가 장애물을 감지하고 회피하는지 확인
   - 안전한 경로로 목표점 도달

3. **성능 최적화**
   - FLS 처리 속도 최적화
   - 실시간 장애물 회피 성능 개선

## 문제 해결

### WSL2 환경

#### FLS 토픽은 있지만 데이터가 없음
**증상**: `ros2 topic info /GIRONA500/fls`에서 Publisher count: 0

**원인**: WSL2의 GPU/OpenGL 제한
- FLS는 GPU compute shader 필요
- WSL2의 MESA/ZINK 스택이 compute shader 미지원

**해결**: 네이티브 Ubuntu 환경 사용

#### Parser 에러 확인
```bash
# Parser 로그 확인
grep -i error ~/.ros/log/latest/stonefish_simulator_node-*.log

# FLS 파싱 확인
grep -i fls ~/.ros/log/latest/stonefish_simulator_node-*.log
```

### 일반 문제

#### AUV가 시작하지 않음
- odometry 토픽 확인: `ros2 topic echo /GIRONA500/dynamics`
- cmd_vel 토픽 확인: `ros2 topic echo /GIRONA500/cmd_vel`

#### 장애물이 보이지 않음
- Stonefish 시뮬레이터 카메라를 측면/위에서 조정
- 시나리오 로그 확인: `cat ~/.ros/log/latest/*.log`

#### RViz에 경로가 안 보임
- Fixed Frame이 "world_ned"인지 확인
- Path 토픽 확인: `ros2 topic echo /eroas/planned_path`

#### Front Camera 영상이 안 나옴
- 토픽 확인: `ros2 topic list | grep front_camera`
- 이미지 수신 확인: `ros2 topic hz /GIRONA500/front_camera`

## GPU 요구사항 상세

### FLS가 요구하는 GPU 기능
- **OpenGL 4.3 이상**
- **Compute Shader (GLSL 4.3+)**
- **SSBO (Shader Storage Buffer Object)**
- **Image Load/Store**

### 환경별 지원 현황
| 환경 | OpenGL | Compute Shader | FLS 작동 |
|------|--------|----------------|----------|
| WSL2 (MESA/ZINK) | 4.6 | ❌ 미지원 | ❌ |
| Native Ubuntu + NVIDIA | 4.6 | ✅ | ✅ |
| Native Ubuntu + AMD | 4.6 | ✅ | ✅ |
| Native Ubuntu + Intel | 4.3+ | ✅ | ✅ |

### GPU 확인 명령어
```bash
# OpenGL 버전 확인
glxinfo | grep "OpenGL version"

# Compute Shader 지원 확인
glxinfo | grep "GL_ARB_compute_shader"
```

## 참고 자료

- [Stonefish Documentation](https://github.com/patrykcieslak/stonefish)
- [ROS2 Humble Documentation](https://docs.ros.org/en/humble/)
- [OpenGL Compute Shader Tutorial](https://www.khronos.org/opengl/wiki/Compute_Shader)