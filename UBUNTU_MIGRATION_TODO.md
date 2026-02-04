# Ubuntu 환경 이전 작업 목록

## 개요
이 문서는 WSL2 환경에서 네이티브 Ubuntu 환경으로 프로젝트를 이전하고, FLS 센서를 실제로 테스트하기 위한 작업 목록입니다.

**목적**: WSL2의 GPU/OpenGL 제한을 벗어나 FLS 센서의 실제 작동을 확인하고, 장애물 감지 기능을 검증합니다.

---

## Phase 1: 환경 준비 ✅ (WSL2에서 완료)

### 완료된 작업
- [x] 프로젝트 코드 압축 (`projectAlpha.tar.gz`)
- [x] FLS 센서 설정 완료 (방향, FOV, 해상도)
- [x] Front Camera 추가
- [x] FLS Viewer 노드 구현
- [x] FLS Recorder 노드 구현
- [x] 테스트 시나리오 구성 (장애물, 경로)
- [x] 문서화 (FLS_TEST_GUIDE.md)

### 이전 파일
- **압축 파일**: `projectAlpha.tar.gz`
- **위치**: `/home/foc/projectAlpha.tar.gz`
- **크기**: 확인 필요
- **이전 방법**: USB, SCP, 또는 Git

---

## Phase 2: Ubuntu 시스템 설정 (네이티브 Ubuntu에서)

### 2.1 시스템 요구사항 확인

#### OS 확인
```bash
# Ubuntu 버전 확인 (24.04 권장)
lsb_release -a
```
- [ ] Ubuntu 24.04 LTS (권장) 또는 22.04 LTS

#### GPU 및 드라이버 확인
```bash
# GPU 정보 확인
lspci | grep -i vga

# OpenGL 버전 확인 (4.3+ 필요)
glxinfo | grep "OpenGL version"

# Compute Shader 지원 확인
glxinfo | grep "GL_ARB_compute_shader"
```

**예상 출력**:
```
OpenGL version string: 4.6.0 NVIDIA 535.xxx
GL_ARB_compute_shader
```

- [ ] GPU 인식됨 (NVIDIA/AMD/Intel)
- [ ] OpenGL 4.3 이상
- [ ] Compute Shader 지원 (GL_ARB_compute_shader)

#### GPU 드라이버 설치 (필요 시)

**NVIDIA GPU**:
```bash
# 권장 드라이버 확인
ubuntu-drivers devices

# 자동 설치 (권장)
sudo ubuntu-drivers autoinstall

# 또는 특정 버전 설치
sudo apt install nvidia-driver-535

# 재부팅 후 확인
nvidia-smi
```
- [ ] NVIDIA 드라이버 설치 완료
- [ ] `nvidia-smi` 정상 작동

**AMD GPU**:
```bash
# Mesa 드라이버 (보통 기본 설치됨)
sudo apt install mesa-vulkan-drivers mesa-utils

# 버전 확인 (22.0+ 권장)
glxinfo | grep "OpenGL version"
```
- [ ] Mesa 드라이버 최신 버전
- [ ] OpenGL 4.3+ 지원

**Intel GPU**:
```bash
# Intel GPU 드라이버 (보통 기본 설치됨)
sudo apt install mesa-utils intel-gpu-tools

# 확인
glxinfo | grep "OpenGL"
```
- [ ] Intel GPU 드라이버 정상
- [ ] OpenGL 4.3+ 지원

---

### 2.2 ROS2 설치

#### ROS2 Jazzy (Ubuntu 24.04)
```bash
# locale 설정
sudo apt update && sudo apt install -y locales
sudo locale-gen en_US en_US.UTF-8
sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
export LANG=en_US.UTF-8

# ROS2 GPG 키 추가
sudo apt install -y software-properties-common curl
sudo add-apt-repository universe -y
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg

# ROS2 저장소 추가
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null

# ROS2 Jazzy 설치
sudo apt update
sudo apt upgrade -y
sudo apt install -y ros-jazzy-desktop

# 환경 설정
echo "source /opt/ros/jazzy/setup.bash" >> ~/.bashrc
source ~/.bashrc
```
- [ ] ROS2 Jazzy 설치 완료
- [ ] ROS2 명령어 정상 작동

#### ROS2 개발 도구
```bash
sudo apt install python3-colcon-common-extensions
sudo apt install python3-rosdep
sudo rosdep init
rosdep update
```
- [ ] colcon 설치 완료
- [ ] rosdep 초기화 완료

---

### 2.3 Stonefish 의존성 설치

```bash
# 기본 의존성
sudo apt install -y \
    git \
    cmake \
    build-essential \
    libglm-dev \
    libsdl2-dev \
    libfreetype6-dev \
    libopenal-dev \
    libxml2-dev \
    libboost-all-dev \
    libpcl-dev

# ROS2 의존성
sudo apt install -y \
    ros-jazzy-geometry-msgs \
    ros-jazzy-sensor-msgs \
    ros-jazzy-std-msgs \
    ros-jazzy-tf2 \
    ros-jazzy-tf2-ros \
    ros-jazzy-visualization-msgs
```
- [ ] Stonefish 의존성 설치 완료
- [ ] ROS2 메시지 패키지 설치 완료

---

### 2.4 Python 의존성 설치

```bash
# Python 패키지 (apt 우선)
sudo apt install -y \
    python3-pip \
    python3-opencv \
    python3-numpy \
    python3-matplotlib

# transforms3d (pip로 설치)
pip3 install transforms3d --break-system-packages
```
- [ ] Python 패키지 설치 완료

---

## Phase 3: 프로젝트 빌드 및 테스트

### 3.1 프로젝트 이전

```bash
# 작업 디렉토리 생성
mkdir -p ~/workspace
cd ~/workspace

# 압축 해제 (USB/네트워크에서 복사 후)
tar -xzf projectAlpha.tar.gz
cd projectAlpha
```
- [ ] 프로젝트 압축 해제 완료
- [ ] 파일 구조 확인

### 3.2 의존성 확인 및 설치

```bash
cd ~/workspace/projectAlpha

# ROS 의존성 확인
rosdep install --from-paths src --ignore-src -r -y
```
- [ ] rosdep 의존성 설치 완료

### 3.3 프로젝트 빌드

```bash
cd ~/workspace/projectAlpha

# 환경 설정
source /opt/ros/humble/setup.bash

# 빌드
colcon build

# 환경 변수 로드
source install/setup.bash
```

**예상 출력**:
```
Starting >>> Stonefish
Starting >>> stonefish_ros2
Finished <<< Stonefish [XXs]
Starting >>> eroas_navigation
Finished <<< stonefish_ros2 [XXs]
Finished <<< eroas_navigation [XXs]

Summary: X packages finished [XXs]
```

- [ ] 빌드 성공 (에러 없음)
- [ ] 모든 패키지 빌드 완료

#### 빌드 실패 시 문제 해결

**에러: Stonefish not found**
```bash
# Stonefish 서브모듈 확인
cd ~/workspace/projectAlpha
git submodule update --init --recursive

# 또는 수동으로 클론
cd ~/workspace
git clone https://github.com/patrykcieslak/stonefish.git
cd stonefish
mkdir build && cd build
cmake .. -DCMAKE_INSTALL_PREFIX=/usr/local
make -j$(nproc)
sudo make install
```

**에러: OpenGL 관련**
```bash
# OpenGL 라이브러리 확인
sudo apt install libgl1-mesa-dev libglu1-mesa-dev
```

---

## Phase 4: FLS 센서 테스트 (핵심!)

### 4.1 기본 시뮬레이션 테스트

```bash
cd ~/workspace/projectAlpha
source install/setup.bash

# FLS 테스트 실행
ros2 launch eroas_navigation girona500_fls_test.launch.py
```

**확인 사항**:
- [ ] Stonefish 시뮬레이터 창 열림
- [ ] AUV가 (0,0,3)에서 시작
- [ ] 좌우 장애물(회색 원기둥) 보임
- [ ] FLS 센서 시각적 더미가 전방을 향하고 가로로 넓게 표시
- [ ] Front Camera가 전방을 향함
- [ ] RViz 창 열림 (경로 표시)

### 4.2 FLS 데이터 발행 확인 (중요!)

**새 터미널 열기**:
```bash
cd ~/workspace/projectAlpha
source install/setup.bash

# FLS 토픽 확인
ros2 topic list | grep fls
# 출력: /GIRONA500/fls

# Publisher 확인 (1 이상이어야 정상!)
ros2 topic info /GIRONA500/fls
```

**예상 출력 (정상)**:
```
Topic: /GIRONA500/fls
Publisher count: 1          <-- 중요! WSL2에서는 0이었음
Subscription count: 1
```

- [ ] **FLS 토픽 존재**
- [ ] **Publisher count: 1 이상** (핵심!)
- [ ] FLS Viewer 노드가 subscriber로 나타남

#### 데이터 수신 확인
```bash
# 실시간 데이터 수신률 확인
ros2 topic hz /GIRONA500/fls
# 예상: average rate: 5.000

# FLS 이미지 메시지 확인
ros2 topic echo /GIRONA500/fls --once
```

**예상 출력**:
```
header:
  stamp:
    sec: ...
    nanosec: ...
  frame_id: GIRONA500/fls_link
height: 64
width: 64
encoding: 32FC1  (또는 8UC1)
...
data: [...]
```

- [ ] **FLS 데이터 5Hz로 수신됨** (핵심!)
- [ ] 이미지 메시지 정상 출력
- [ ] encoding: 32FC1 또는 8UC1

### 4.3 FLS 시각화 확인

**FLS Viewer 창 확인**:
- [ ] "FLS - Forward Looking Sonar" OpenCV 창 열림
- [ ] 소나 이미지가 실시간으로 업데이트됨
- [ ] 이미지가 검은색이 아님 (실제 데이터)
- [ ] 바닥 반사가 이미지 하단에 나타남 (밝은 부분)

**시뮬레이터에서 AUV 이동 후**:
- [ ] AUV가 전진하면서 장애물 접근
- [ ] 10m 지점에서 좌우 장애물이 FLS 이미지에 나타남
- [ ] 장애물이 밝은 반사로 표시됨
- [ ] 좌측 장애물이 이미지 왼쪽에, 우측 장애물이 오른쪽에 표시

### 4.4 Camera 데이터 확인

```bash
# Camera 토픽 확인
ros2 topic list | grep front_camera
# 출력: /GIRONA500/front_camera

# Camera 데이터 수신 확인
ros2 topic hz /GIRONA500/front_camera
# 예상: average rate: 10.000

# 이미지 메시지 확인
ros2 topic echo /GIRONA500/front_camera --once
```

- [ ] Front Camera 토픽 존재
- [ ] 카메라 데이터 10Hz로 수신
- [ ] 이미지 해상도: 800x600

### 4.5 FLS 데이터 기록 확인

```bash
# 기록 디렉토리 확인
ls -lh /tmp/fls_data/
```

**예상 출력**:
```
fls_recording_20260203_HHMMSS.pkl
```

- [ ] FLS 데이터 자동 기록됨
- [ ] 파일 크기가 증가하는지 확인 (10초마다 저장)

#### 기록된 데이터 로드 테스트
```bash
# Python으로 데이터 로드 테스트
python3 << EOF
import pickle

# 최신 파일 로드
import glob
files = sorted(glob.glob('/tmp/fls_data/*.pkl'))
if files:
    with open(files[-1], 'rb') as f:
        data = pickle.load(f)
    print(f"Total frames: {data['metadata']['total_frames']}")
    print(f"Duration: {data['metadata']['duration']:.2f}s")
    print("Data recording SUCCESS!")
else:
    print("No data files found!")
EOF
```

- [ ] 데이터 로드 성공
- [ ] 프레임 수가 0보다 큼
- [ ] 메타데이터 정상

---

## Phase 5: 성능 및 품질 검증

### 5.1 FLS 이미지 품질 확인

**터미널에서 시각화**:
```python
import pickle
import matplotlib.pyplot as plt
import numpy as np
import glob

# 최신 기록 파일 로드
files = sorted(glob.glob('/tmp/fls_data/*.pkl'))
with open(files[-1], 'rb') as f:
    data = pickle.load(f)

# 여러 프레임 시각화
fig, axes = plt.subplots(2, 3, figsize=(15, 10))
for i, ax in enumerate(axes.flat):
    if i < len(data['data']):
        record = data['data'][i]
        img = record['fls_data']
        pose = record['pose']

        ax.imshow(img, cmap='bone')
        ax.set_title(f"t={record['timestamp']:.1f}s\n"
                     f"x={pose['position']['x']:.1f}m")
        ax.axis('off')

plt.tight_layout()
plt.savefig('/tmp/fls_quality_check.png')
print("Saved to /tmp/fls_quality_check.png")
plt.show()
```

**확인 사항**:
- [ ] 이미지가 의미있는 데이터를 포함 (검은색만이 아님)
- [ ] 시간에 따라 이미지가 변화함
- [ ] 장애물이 감지될 때 밝은 반사 영역이 나타남
- [ ] 노이즈가 과도하지 않음

### 5.2 장애물 감지 성능 테스트

**시나리오**:
1. AUV를 (0, 0, 3)에서 시작
2. 북쪽으로 20m 전진 (목표: 20, 0, 3)
3. 10m 지점에서 좌우 장애물 통과

**측정 항목**:
- [ ] 장애물이 약 10m 지점에서 FLS에 처음 감지됨
- [ ] 좌우 장애물이 구분되어 보임
- [ ] 장애물 간격(6m)이 FLS 이미지에 반영됨
- [ ] AUV가 장애물을 통과할 때 이미지 변화가 관찰됨

### 5.3 성능 모니터링

```bash
# CPU/GPU 사용률 모니터링
# 터미널 1: GPU 모니터링 (NVIDIA)
watch -n 1 nvidia-smi

# 터미널 2: CPU 모니터링
htop

# 터미널 3: ROS2 노드 상태
ros2 node list
ros2 topic hz /GIRONA500/fls
```

**확인 사항**:
- [ ] GPU 사용률 < 80% (안정적)
- [ ] CPU 사용률 < 100%
- [ ] FLS 데이터 주파수 안정적 (~5Hz)
- [ ] 시뮬레이터 프레임률 정상 (30fps+)

---

## Phase 6: 문제 해결 및 최적화

### 6.1 FLS 데이터가 여전히 안 나오는 경우

#### 문제 1: Publisher count: 0
```bash
# Stonefish 로그 확인
grep -i "fls\|error\|opengl" ~/.ros/log/latest/*.log

# OpenGL 버전 재확인
glxinfo | grep -i "opengl\|compute"
```

**가능한 원인**:
1. OpenGL 버전 < 4.3
2. Compute Shader 미지원
3. Stonefish가 console 모드로 실행됨

**해결 방법**:
- GPU 드라이버 업데이트
- Stonefish 빌드 옵션 확인 (`-DGRAPHICS=ON`)

#### 문제 2: 이미지가 검은색만 나옴
```bash
# FLS 설정 확인
grep -A 10 "sensor name=\"fls\"" src/stonefish_ros2/data/girona500auv_console.scn
```

**확인 항목**:
- range_min, range_max 설정이 적절한지
- gain 값이 너무 낮지 않은지
- 센서 방향이 올바른지

### 6.2 성능 최적화 (필요 시)

#### FLS 해상도 조정
```xml
<!-- src/stonefish_ros2/data/girona500auv_console.scn -->
<specs beams="32" bins="32" .../>  <!-- 64에서 32로 감소 -->
```

#### FLS 주파수 조정
```xml
<sensor name="fls" type="fls" rate="3.0">  <!-- 5Hz에서 3Hz로 감소 -->
```

#### Ocean 시뮬레이션 비활성화
```xml
<!-- src/stonefish_ros2/scenarios/fls_test.scn -->
<ocean>
    <waves height="0.0"/>  <!-- 파도 비활성화 -->
</ocean>
```

---

## Phase 7: 다음 단계 준비

### 7.1 FLS 데이터 분석

**기록된 데이터로 오프라인 분석**:
```python
import pickle
import numpy as np
import matplotlib.pyplot as plt

# 데이터 로드
with open('/tmp/fls_data/fls_recording_YYYYMMDD_HHMMSS.pkl', 'rb') as f:
    data = pickle.load(f)

# 장애물 감지 분석
for record in data['data']:
    fls_img = record['fls_data']
    pos = record['pose']['position']

    # 장애물 감지 (간단한 임계값 기반)
    threshold = np.mean(fls_img) + 2 * np.std(fls_img)
    obstacles = fls_img > threshold

    if np.any(obstacles):
        print(f"Obstacle detected at x={pos['x']:.1f}m, y={pos['y']:.1f}m")
```

- [ ] 10m 지점에서 장애물 감지 확인
- [ ] 좌우 장애물 구분 가능
- [ ] 감지 거리 및 각도 측정

### 7.2 EROAS 통합 준비

**EROAS 노드에 FLS 콜백 추가 준비**:
```python
# src/eroas_navigation/eroas_navigation/eroas_node.py
def fls_callback(self, msg):
    """FLS 데이터 처리"""
    # SPD2C: 장애물 감지
    obstacles = self.detect_obstacles(msg)

    # SCG: 장애물 메모리 업데이트
    self.update_obstacle_memory(obstacles)

    # ST-CBF: 안전 제약 조건 계산
    safe_velocity = self.compute_safe_velocity(obstacles)
```

- [ ] FLS subscriber 추가
- [ ] 장애물 감지 알고리즘 구현
- [ ] 회피 로직 통합

### 7.3 추가 테스트 시나리오 작성

**다양한 환경 테스트**:
1. 단일 장애물 (정면)
2. 좁은 통로
3. 복잡한 장애물 배치
4. 동적 장애물 (움직이는 물체)

---

## 체크리스트 요약

### 필수 완료 항목 (FLS 작동을 위한 최소 요구사항)
- [ ] Ubuntu 22.04/20.04 설치
- [ ] GPU 드라이버 설치 (OpenGL 4.3+, Compute Shader)
- [ ] ROS2 Humble 설치
- [ ] Stonefish 의존성 설치
- [ ] 프로젝트 빌드 성공
- [ ] **FLS Publisher count: 1 이상** (핵심!)
- [ ] **FLS 데이터 5Hz로 수신** (핵심!)
- [ ] **FLS 이미지에 실제 데이터 표시** (핵심!)

### 검증 완료 항목 (기능 확인)
- [ ] 장애물이 FLS 이미지에 나타남
- [ ] 좌우 장애물 구분 가능
- [ ] FLS 데이터 기록 동작
- [ ] Camera 데이터 정상 수신
- [ ] 성능 안정적 (GPU < 80%, 5Hz 안정)

### 다음 단계 (EROAS 통합)
- [ ] FLS 기반 장애물 감지 알고리즘 구현
- [ ] SPD2C 모듈 통합
- [ ] SCG 장애물 메모리 구현
- [ ] ST-CBF 안전 제약 조건 적용
- [ ] 장애물 회피 테스트

---

## 문제 발생 시 연락 정보

**Stonefish GitHub**: https://github.com/patrykcieslak/stonefish/issues
**ROS2 Discourse**: https://discourse.ros.org/

**주요 로그 파일**:
- `~/.ros/log/latest/stonefish_simulator_node-*.log`
- `~/.ros/log/latest/fls_viewer-*.log`
- `/tmp/fls_data/` (FLS 데이터)

---

## 예상 소요 시간

- Phase 2 (시스템 설정): 1-2시간
- Phase 3 (프로젝트 빌드): 30분
- Phase 4 (FLS 테스트): 1시간
- Phase 5 (검증): 1시간
- Phase 6 (문제 해결): 가변적
- **총 예상 시간**: 4-6시간

---

## 성공 기준

### 최소 성공 기준 (Phase 4 완료)
✅ FLS Publisher count: 1 이상
✅ FLS 데이터 5Hz로 수신
✅ FLS 이미지에 실제 데이터 표시 (검은색만이 아님)

### 완전 성공 기준 (Phase 5 완료)
✅ 장애물이 FLS 이미지에 명확히 나타남
✅ 좌우 장애물 구분 가능
✅ FLS 데이터 기록 및 분석 가능
✅ 성능 안정적

### 다음 단계 준비 완료 (Phase 7 완료)
✅ FLS 데이터 분석 완료
✅ 장애물 감지 알고리즘 검증
✅ EROAS 통합 준비 완료

---

**중요**: WSL2에서는 불가능했던 FLS 데이터 발행이 네이티브 Ubuntu에서는 정상 작동해야 합니다. 만약 여전히 Publisher count: 0이라면, GPU 드라이버와 OpenGL 지원을 반드시 재확인하세요!