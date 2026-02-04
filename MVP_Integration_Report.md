# Girona500 AUV에 MVP Control Framework 통합 프로젝트 보고서

## 1. 프로젝트 개요

### 1.1 목적
URI Ocean Robotics의 MVP (Marine Vehicle Packages) 제어 프레임워크를 Stonefish 시뮬레이터의 Girona500 AUV 모델에 통합하여 자율 수중 로봇의 행동 기반 제어 시스템을 구현

### 1.2 개발 환경
- **ROS 버전**: ROS2 Jazzy (LTS)
- **시뮬레이터**: Stonefish 1.6
- **로봇 모델**: Girona500 AUV (5-DOF 제어: surge, sway, heave, pitch, yaw)
- **제어 프레임워크**: MVP Control + MVP Helm + MVP Mission

### 1.3 시스템 아키텍처
```
Stonefish Simulator → Odometry → MVP Control → Thruster Commands → Stonefish
                         ↓
                    TF Tree (좌표계 변환)
                         ↓
                  MVP Helm (미션 제어)
```

## 2. 발생한 문제들과 해결 과정

### 문제 #1: MVP Control 초기 세그먼테이션 폴트 (Segfault)

#### 문제 상황
```bash
[ERROR] [mvp_control_ros_node-6]: process has died [pid 2358268, exit code -11]
```
- MVP Control 노드가 시작 직후 크래시 (exit code -11 = segfault)
- 초기 가설: URDF 또는 robot_description 파라미터 누락

#### 분석 과정
1. MVP Control 소스코드 분석 → TF(Transform) 기반 시스템임을 확인
2. Stonefish 설정 확인 → odometry는 발행하지만 TF는 발행하지 않음을 발견
3. 실제 원인: TF 트리가 구성되지 않아 MVP Control이 좌표계 변환을 수행할 수 없음

#### 해결 방법
**단계 1**: URDF 파일 생성 (`src/stonefish_ros2/urdf/girona500.urdf`)
```xml
<?xml version="1.0"?>
<robot name="girona500">
  <link name="base_link">
    <inertial>
      <mass value="160.0"/>
      <origin xyz="0 0 0" rpy="0 0 0"/>
      <inertia ixx="20.0" iyy="40.0" izz="40.0"/>
    </inertial>
  </link>

  <!-- 5개 추진기 링크 정의 -->
  <link name="thruster_surge_port"/>
  <joint name="thruster_surge_port_joint" type="fixed">
    <parent link="base_link"/>
    <child link="thruster_surge_port"/>
    <origin xyz="-0.3297 -0.2587 -0.021" rpy="3.1416 0.0 0.0"/>
  </joint>
  <!-- ... 나머지 4개 추진기 -->
</robot>
```

**단계 2**: Odometry-to-TF 변환 노드 생성 (`src/stonefish_ros2/scripts/odom_to_tf.py`)
```python
class OdomToTF(Node):
    def __init__(self):
        self.tf_broadcaster = TransformBroadcaster(self)
        self.odom_sub = self.create_subscription(
            Odometry, '/GIRONA500/dynamics', self.odom_callback, 10)

    def odom_callback(self, msg):
        t = TransformStamped()
        t.header.stamp = msg.header.stamp
        t.header.frame_id = 'GIRONA500/world_ned'
        t.child_frame_id = 'GIRONA500/Vehicle'
        t.transform.translation.x = msg.pose.pose.position.x
        t.transform.translation.y = msg.pose.pose.position.y
        t.transform.translation.z = msg.pose.pose.position.z
        t.transform.rotation = msg.pose.pose.orientation
        self.tf_broadcaster.sendTransform(t)
```

**단계 3**: 정적 TF 발행자 추가
```python
# world_ned → GIRONA500/world_ned (브릿지)
static_tf_world_ned = Node(
    package='tf2_ros',
    executable='static_transform_publisher',
    arguments=['0', '0', '0', '0', '0', '0', 'world_ned', 'GIRONA500/world_ned']
)

# GIRONA500/Vehicle → GIRONA500/base_link (브릿지)
static_tf_vehicle_baselink = Node(
    package='tf2_ros',
    executable='static_transform_publisher',
    arguments=['0', '0', '0', '0', '0', '0', 'GIRONA500/Vehicle', 'GIRONA500/base_link']
)
```

#### 결과
TF 트리 완성:
```
world_ned
  └─ GIRONA500/world_ned (static)
       └─ GIRONA500/Vehicle (dynamic, from odometry)
            └─ GIRONA500/base_link (static)
                 ├─ thruster_surge_port
                 ├─ thruster_surge_starboard
                 ├─ thruster_heave_bow
                 ├─ thruster_heave_stern
                 └─ thruster_sway
```

### 문제 #2: 시나리오 파일 파싱 오류

#### 문제 상황
```
[ERROR] Environment settings not defined!
```
- `girona500auv_console.scn` 파일을 직접 로드 시도 시 발생

#### 분석
- `girona500auv_console.scn`은 include 전용 파일 (환경 설정 없음)
- 완전한 시나리오 파일이 필요함

#### 해결
- `console_test.scn` 사용 (환경 + Girona500 포함)
- launch 파일 수정:
```python
scenario_desc = os.path.join(pkg_stonefish_ros2, 'scenarios', 'console_test.scn')
```

### 문제 #3: DOF(자유도) 명명 불일치

#### 문제 상황
```
[ERROR] Unknown freedom name passed 'surge'
Possible values are 'x, y, z, roll, pitch, yaw, surge, sway, heave'
```

#### 분석
- MVP Control의 YAML 파서가 `x, y, z` 명명을 기대
- 초기 설정은 `surge, sway, heave` 사용

#### 해결
`src/stonefish_ros2/config/girona500_control_modes.yaml` 수정:
```yaml
# 변경 전
teleop:
  surge: {p: 1.0, i: 3.0, d: 5.0}
  sway: {p: 1.0, i: 3.0, d: 5.0}

# 변경 후
teleop:
  x: {p: 1.0, i: 3.0, d: 5.0, v: 0.0, pid_max: 10.0, pid_min: -10.0}
  y: {p: 1.0, i: 3.0, d: 5.0, v: 0.0, pid_max: 10.0, pid_min: -10.0}
```

### 문제 #4: Rate 제어 DOF 오류

#### 문제 상황
```
[ERROR] Unknown freedom name passed 'yaw_rate'
```

#### 분석
- MVP Control은 rate 제어를 별도 설정이 아닌 내부적으로 처리
- `yaw_rate`, `pitch_rate` 명칭을 인식하지 못함

#### 해결
```yaml
# 변경 전
teleop:
  yaw_rate: {p: 2.0, i: 0.5, d: 3.0}
  pitch_rate: {p: 2.0, i: 0.5, d: 3.0}

# 변경 후
teleop:
  yaw: {p: 2.0, i: 0.5, d: 3.0, v: 0.0, pid_max: 20.0, pid_min: -20.0}
  pitch: {p: 2.0, i: 0.5, d: 3.0, v: 0.0, pid_max: 20.0, pid_min: -20.0}
```

### 문제 #5: TF Prefix 중복 오류

#### 문제 상황
```
[ERROR] "GIRONA500/GIRONA500/world_ned" passed to lookupTransform does not exist
```

#### 분석
MVP Control 코드 분석:
```cpp
// MVP Control 내부
std::string frame_id = m_tf_prefix + "/" + world_link_initial;
// "GIRONA500" + "/" + "GIRONA500/world_ned" = "GIRONA500/GIRONA500/world_ned" (잘못됨)
```

#### 해결
`src/stonefish_ros2/config/girona500_mvp_control.yaml` 수정:
```yaml
# 변경 전
/GIRONA500/mvp_control:
  ros__parameters:
    tf_prefix: "GIRONA500"
    world_link_initial: "GIRONA500/world_ned"
    child_link_initial: "GIRONA500/base_link"

# 변경 후
/GIRONA500/mvp_control:
  ros__parameters:
    tf_prefix: "GIRONA500"
    world_link_initial: "world_ned"          # prefix 제거
    child_link_initial: "base_link"          # prefix 제거
```

### 문제 #6: TF 트리 연결 끊김

#### 문제 상황
```
[ERROR] Could not find a connection between 'GIRONA500/world_ned' and 'GIRONA500/base_link'
because they are not part of the same tree. Tf has two or more unconnected trees.
```

#### 분석
1. TF 트리가 두 개의 독립적인 그래프로 분리됨
2. 원인: Stonefish가 `world_ned` → `GIRONA500/Vehicle` TF를 발행하지 않음
3. Odometry 메시지만 발행, TF는 미발행

#### 검증
```bash
$ ros2 topic echo /tf_static --once
# world_ned → GIRONA500/world_ned만 존재

$ ros2 topic echo /tf --once
# (비어있음 - 동적 TF 없음)
```

#### 해결
이미 문제 #1에서 `odom_to_tf.py`로 해결됨

### 문제 #7: 추진기 미검출

#### 문제 상황
```
[WARN] !!! No thruster specified !!!
[ERROR] terminate called after throwing an instance of 'ctrl::control_ros_exception'
  what(): no thruster specified
```

#### 분석
1. MVP Control이 TF 프레임을 찾았지만 추진기 설정이 없음
2. MVP Control 소스코드 분석 (`src/mvp_control/src/mvp_control/mvp_control_ros.cpp:1827-1899`):
```cpp
if(map["thruster_ids"]) {
    for(YAML::const_iterator it=map["thruster_ids"].begin(); ...) {
        std::string t_name = it->first.as<std::string>();

        // control_tf: TF 프레임 이름
        param_name = map["thruster_ids"][t_name]["control_tf"].as<std::string>();

        // command_topic: 추력 명령 토픽
        param_name = map["thruster_ids"][t_name]["command_topic"].as<std::string>();

        // force_topic: 힘 피드백 토픽
        param_name = map["thruster_ids"][t_name]["force_topic"].as<std::string>();

        // limits: [min, max] 추력 한계
        min_max = map["thruster_ids"][t_name]["limits"].as<std::vector<float>>();

        // delta_limit: 추력 변화율 제한
        delta_limit = map["thruster_ids"][t_name]["delta_limit"].as<double>();

        // polynomials: 힘-RPM 변환 다항식
        poly_coef = map["thruster_ids"][t_name]["polynomials"].as<std::vector<double>>();
    }
}
```

#### 해결
`src/stonefish_ros2/config/girona500_control_modes.yaml`에 추진기 설정 추가:

```yaml
thruster_ids:
  ThrusterSurgePort:
    control_tf: "thruster_surge_port"
    command_topic: "/GIRONA500/ThrusterSurgePort/setpoint"
    force_topic: "/GIRONA500/ThrusterSurgePort/force"
    limits: [-50.0, 50.0]    # Newton
    delta_limit: 200.0        # N/s
    polynomials: [0.0, 1.0]   # force = 0.0 + 1.0*RPM

  ThrusterSurgeStarboard:
    control_tf: "thruster_surge_starboard"
    command_topic: "/GIRONA500/ThrusterSurgeStarboard/setpoint"
    force_topic: "/GIRONA500/ThrusterSurgeStarboard/force"
    limits: [-50.0, 50.0]
    delta_limit: 200.0
    polynomials: [0.0, 1.0]

  ThrusterHeaveBow:
    control_tf: "thruster_heave_bow"
    command_topic: "/GIRONA500/ThrusterHeaveBow/setpoint"
    force_topic: "/GIRONA500/ThrusterHeaveBow/force"
    limits: [-50.0, 50.0]
    delta_limit: 200.0
    polynomials: [0.0, 1.0]

  ThrusterHeaveStern:
    control_tf: "thruster_heave_stern"
    command_topic: "/GIRONA500/ThrusterHeaveStern/setpoint"
    force_topic: "/GIRONA500/ThrusterHeaveStern/force"
    limits: [-50.0, 50.0]
    delta_limit: 200.0
    polynomials: [0.0, 1.0]

  ThrusterSway:
    control_tf: "thruster_sway"
    command_topic: "/GIRONA500/ThrusterSway/setpoint"
    force_topic: "/GIRONA500/ThrusterSway/force"
    limits: [-50.0, 50.0]
    delta_limit: 200.0
    polynomials: [0.0, 1.0]
```

#### 추진기 위치 정보 출처
시나리오 파일 (`src/stonefish_ros2/scenarios/girona500auv_console.scn`)에서 추출:
```xml
<actuator name="ThrusterSurgePort" type="thruster">
    <link name="Vehicle"/>
    <origin rpy="3.1416 0.0 0.0" xyz="-0.3297 -0.2587 -0.021"/>
    <!-- ... -->
</actuator>
```

### 문제 #8: Odometry Frame ID 불일치

#### 문제 상황
```
[WARN] Can't compute process values!, check odometry!:
Invalid argument "" passed to lookupTransform argument source_frame -
in tf2 frame_ids cannot be empty
```

#### 분석
Stonefish가 발행하는 odometry 메시지 확인:
```bash
$ ros2 topic echo /GIRONA500/dynamics --once
header:
  frame_id: world_ned                    # MVP는 GIRONA500/world_ned 기대
child_frame_id: GIRONA500/dynamics      # MVP는 GIRONA500/base_link 기대
```

MVP Control이 기대하는 프레임:
- `frame_id`: `tf_prefix + "/" + world_link_initial` = `"GIRONA500/world_ned"`
- `child_frame_id`: `tf_prefix + "/" + child_link_initial` = `"GIRONA500/base_link"`

#### 해결
Odometry 프레임 수정 노드 생성 (`src/stonefish_ros2/scripts/odom_frame_fixer.py`):

```python
class OdomFrameFixer(Node):
    def __init__(self):
        self.odom_sub = self.create_subscription(
            Odometry, '/GIRONA500/dynamics', self.odom_callback, 10)
        self.odom_pub = self.create_publisher(
            Odometry, '/GIRONA500/dynamics_fixed', 10)

    def odom_callback(self, msg):
        fixed_msg = Odometry()
        fixed_msg.header = msg.header
        fixed_msg.header.frame_id = 'GIRONA500/world_ned'      # 수정
        fixed_msg.child_frame_id = 'GIRONA500/base_link'       # 수정
        fixed_msg.pose = msg.pose
        fixed_msg.twist = msg.twist
        self.odom_pub.publish(fixed_msg)
```

Launch 파일에서 remapping 수정:
```python
mvp_control_node = Node(
    remappings=[
        ('/GIRONA500/odometry/filtered', '/GIRONA500/dynamics_fixed'),  # 수정됨
    ],
)

mvp_helm_node = Node(
    remappings=[
        ('/GIRONA500/odometry/filtered', '/GIRONA500/dynamics_fixed'),  # 수정됨
    ],
)
```

## 3. 최종 시스템 아키텍처

### 3.1 노드 구성
```
┌─────────────────────────────────────────────────────────────┐
│                    Stonefish Simulator                       │
│  - 물리 시뮬레이션                                             │
│  - Odometry 발행: /GIRONA500/dynamics                        │
│  - Thruster 명령 수신: /GIRONA500/Thruster*/setpoint        │
└─────────────────────────────────────────────────────────────┘
                            ↓ odometry
┌─────────────────────────────────────────────────────────────┐
│                    odom_to_tf.py                             │
│  - Odometry → TF 변환                                         │
│  - 발행: GIRONA500/world_ned → GIRONA500/Vehicle (동적)      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                  odom_frame_fixer.py                         │
│  - Frame ID 수정                                              │
│  - 발행: /GIRONA500/dynamics_fixed                           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    MVP Control                               │
│  - PID 제어                                                   │
│  - 추진기 할당 행렬 생성                                        │
│  - 발행: 추력 명령 (5개 추진기)                                 │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                     MVP Helm                                 │
│  - 유한 상태 기계 (FSM)                                        │
│  - 행동 기반 제어 (Behavior-based Control)                    │
│  - 모드: teleop, flight, hold_dof                            │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 TF 트리 (최종)
```
world_ned
  └─ GIRONA500/world_ned (static transform)
       └─ GIRONA500/Vehicle (dynamic, from odom_to_tf)
            └─ GIRONA500/base_link (static transform)
                 ├─ thruster_surge_port (from robot_state_publisher)
                 ├─ thruster_surge_starboard
                 ├─ thruster_heave_bow
                 ├─ thruster_heave_stern
                 └─ thruster_sway
```

### 3.3 토픽 맵
| 토픽 | 타입 | 발행자 | 구독자 | 설명 |
|------|------|--------|--------|------|
| `/GIRONA500/dynamics` | `nav_msgs/Odometry` | Stonefish | odom_to_tf, odom_frame_fixer | 원본 odometry |
| `/GIRONA500/dynamics_fixed` | `nav_msgs/Odometry` | odom_frame_fixer | MVP Control, MVP Helm | Frame ID 수정된 odometry |
| `/GIRONA500/ThrusterSurgePort/setpoint` | `std_msgs/Float64` | MVP Control | Stonefish | 추력 명령 |
| `/GIRONA500/ThrusterSurgePort/force` | `std_msgs/Float64` | MVP Control | - | 추력 피드백 |
| `/tf` | `tf2_msgs/TFMessage` | odom_to_tf | MVP Control | 동적 TF |
| `/tf_static` | `tf2_msgs/TFMessage` | static_transform_publisher, robot_state_publisher | MVP Control | 정적 TF |

## 4. 생성된 파일 목록

### 4.1 새로 생성된 파일
1. **`src/stonefish_ros2/urdf/girona500.urdf`**
   - 로봇 구조 정의
   - 추진기 위치 및 프레임 정의

2. **`src/stonefish_ros2/scripts/odom_to_tf.py`**
   - Odometry → TF 변환 노드
   - 동적 TF 발행

3. **`src/stonefish_ros2/scripts/odom_frame_fixer.py`**
   - Odometry frame ID 수정 노드

4. **`src/stonefish_ros2/config/girona500_control_modes.yaml`**
   - PID 제어 파라미터
   - 추진기 설정

5. **`src/stonefish_ros2/config/girona500_mvp_control.yaml`**
   - MVP Control ROS2 파라미터
   - TF prefix 설정

6. **`src/stonefish_ros2/launch/girona500_mvp.launch.py`**
   - 통합 launch 파일

### 4.2 수정된 파일
1. **`src/stonefish_ros2/CMakeLists.txt`** (line 109-118)
   - 새 Python 스크립트 설치 추가
   - URDF 디렉토리 설치 추가

## 5. 검증 및 결과

### 5.1 시스템 시작 로그
```bash
$ ros2 launch stonefish_ros2 girona500_mvp.launch.py

[mvp_control_ros_node] ####Thruster: ThrusterSurgePort, topic name: /GIRONA500/ThrusterSurgePort/setpoint
[mvp_control_ros_node] ####Thruster: ThrusterSurgeStarboard, topic name: /GIRONA500/ThrusterSurgeStarboard/setpoint
[mvp_control_ros_node] ####Thruster: ThrusterHeaveBow, topic name: /GIRONA500/ThrusterHeaveBow/setpoint
[mvp_control_ros_node] ####Thruster: ThrusterHeaveStern, topic name: /GIRONA500/ThrusterHeaveStern/setpoint
[mvp_control_ros_node] ####Thruster: ThrusterSway, topic name: /GIRONA500/ThrusterSway/setpoint
[mvp_control_ros_node] #########regular thruster allocation generated ##############
[mvp_control_ros_node] allocation matrix initialized
[mvp_control_ros_node] #### MVP Control initialized #####
[stonefish_simulator] [INFO] Ready for running...
[mvp_helm] ###Waypoint loaded properly, GIRONA500/world_ned
```

### 5.2 TF 트리 검증
```bash
$ ros2 run tf2_ros tf2_echo GIRONA500/world_ned GIRONA500/base_link
At time 0.0
- Translation: [0.571, 0.129, 0.435]
- Rotation: in Quaternion [-0.236, 0.971, 0.002, 0.009]
# ✅ 성공: 연결된 TF 트리
```

### 5.3 추력 명령 발행 확인
```bash
$ ros2 topic echo /GIRONA500/ThrusterSurgePort/setpoint
data: 0.0
# ✅ 성공: MVP Control이 명령 발행 중 (idle 모드에서 0.0)
```

### 5.4 Odometry Frame 검증
```bash
$ ros2 topic echo /GIRONA500/dynamics_fixed --once
header:
  frame_id: GIRONA500/world_ned        # ✅ 올바름
child_frame_id: GIRONA500/base_link    # ✅ 올바름
```

## 6. 결론

### 6.1 달성 사항
1. ✅ MVP Control Framework를 Stonefish Girona500에 성공적으로 통합
2. ✅ TF 트리 완전 구성 (world → robot → thrusters)
3. ✅ 자동 추진기 할당 행렬 생성
4. ✅ 5-DOF 제어 시스템 구현
5. ✅ 행동 기반 미션 제어 시스템 활성화

### 6.2 핵심 기술적 기여
1. **TF 브릿징 솔루션**: Stonefish와 MVP 간 좌표계 불일치 해결
2. **Frame ID 정규화**: 자동 프레임 ID 변환 노드
3. **통합 설정 시스템**: YAML 기반 추진기 및 제어 설정

### 6.3 학습된 교훈
1. **프레임워크 통합 시 좌표계 일관성이 핵심**: TF 트리 구조를 먼저 설계해야 함
2. **소스코드 분석의 중요성**: 문서화되지 않은 요구사항 발견
3. **점진적 디버깅**: 각 문제를 독립적으로 해결하여 복잡도 관리

### 6.4 향후 작업
1. 추진기 다항식 보정 (현재 선형 근사)
2. 실제 힘 한계값 측정 및 적용
3. 고급 제어 모드 구현 (station keeping, path following)
4. 미션 시나리오 테스트

## 7. 참고 문헌

1. MVP Framework: https://github.com/uri-ocean-robotics/mvp_control
2. Stonefish Documentation: https://stonefish.readthedocs.io/
3. ROS2 TF2: https://docs.ros.org/en/jazzy/Tutorials/Intermediate/Tf2/
4. Girona500 AUV: CIRS (Underwater Robotics Research Center)

---

**프로젝트 완료일**: 2026-01-27
**시스템 상태**: 정상 작동, 테스트 준비 완료