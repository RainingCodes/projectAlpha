"""
EROAS (Efficient Reactive Obstacle Avoidance System) ROS2 Node
Main navigation node integrating SPD2C, SCG, and ST-CBF modules
"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, Point
from nav_msgs.msg import Odometry, Path
from std_msgs.msg import Float32MultiArray, ColorRGBA
from std_srvs.srv import Trigger
from visualization_msgs.msg import Marker, MarkerArray
from geometry_msgs.msg import PoseStamped, Vector3
import numpy as np
from typing import Optional

from .spd2c import SPD2C
from .scg import SCG
from .st_cbf import STCBF


class EROASNode(Node):
    """
    Main EROAS navigation node

    Integrates reactive obstacle avoidance using:
    - SPD2C: Gap finding and directional decisions
    - SCG: Obstacle memory management
    - ST-CBF: Safety filtering through QP
    """

    def __init__(self):
        super().__init__('eroas_node')

        # Declare parameters
        self.declare_parameter('namespace', 'GIRONA500')
        self.declare_parameter('control_frequency', 10.0)
        self.declare_parameter('goal_x', 10.0)
        self.declare_parameter('goal_y', 10.0)
        self.declare_parameter('goal_z', -3.0)
        self.declare_parameter('goal_tolerance', 1.0)
        self.declare_parameter('auto_start', True)

        # Get parameters
        self.namespace = self.get_parameter('namespace').value
        self.control_freq = self.get_parameter('control_frequency').value
        self.goal_tolerance = self.get_parameter('goal_tolerance').value

        # Goal position
        self.goal = np.array([
            self.get_parameter('goal_x').value,
            self.get_parameter('goal_y').value,
            self.get_parameter('goal_z').value
        ])

        # Auto-start: if False, waits for /eroas/start service call
        self.navigation_active = self.get_parameter('auto_start').value

        # Vehicle state
        self.position = np.zeros(3)
        self.velocity = np.zeros(3)
        self.heading = 0.0  # yaw in radians
        self.state_received = False

        # Sonar data (placeholder - will be replaced with actual FLS subscription)
        self.sonar_intensities = np.zeros(512)

        # Initialize EROAS modules
        spd2c_params = {
            'num_beams': 512,
            'fov_horizontal': np.deg2rad(90),
            'intensity_threshold': 15.0,
            'gap_length': 150,
            'convergence_threshold': 0.02,
            'v_max': 1.0,
            'r_max': np.deg2rad(15),
            'Kv': 0.35,
            'Kt': 0.12,
            'Kr': 0.175
        }

        self.spd2c = SPD2C(spd2c_params)
        self.scg = SCG(memory_radius=15.0)
        self.stcbf = STCBF(
            obstacle_radius=2.0,
            cbf_gain=1.0,
            v_max=1.0
        )

        # ROS2 subscribers
        self.odom_sub = self.create_subscription(
            Odometry,
            f'/{self.namespace}/dynamics',
            self.odom_callback,
            10
        )

        # TODO: Add FLS sonar subscription
        # self.sonar_sub = self.create_subscription(
        #     SonarScan,
        #     f'/{self.namespace}/sonar',
        #     self.sonar_callback,
        #     10
        # )

        # ROS2 publishers
        self.cmd_vel_pub = self.create_publisher(
            Twist,
            f'/{self.namespace}/cmd_vel',
            10
        )

        # Visualization publishers
        self.marker_pub = self.create_publisher(
            MarkerArray,
            '/eroas/visualization_markers',
            10
        )
        self.path_pub = self.create_publisher(
            Path,
            '/eroas/planned_path',
            10
        )

        # Start/Stop services
        self.start_srv = self.create_service(
            Trigger, '/eroas/start', self.start_callback)
        self.stop_srv = self.create_service(
            Trigger, '/eroas/stop', self.stop_callback)

        # Control timer
        self.control_timer = self.create_timer(
            1.0 / self.control_freq,
            self.control_loop
        )

        self.get_logger().info('EROAS Node initialized')
        self.get_logger().info(f'Namespace: {self.namespace}')
        self.get_logger().info(f'Goal: {self.goal}')
        self.get_logger().info(f'Control frequency: {self.control_freq} Hz')
        if not self.navigation_active:
            self.get_logger().info(
                'Navigation PAUSED - call /eroas/start to begin')

    def odom_callback(self, msg: Odometry):
        """Update vehicle state from odometry"""
        # Extract position (NED frame)
        self.position = np.array([
            msg.pose.pose.position.x,
            msg.pose.pose.position.y,
            msg.pose.pose.position.z
        ])

        # Extract velocity
        self.velocity = np.array([
            msg.twist.twist.linear.x,
            msg.twist.twist.linear.y,
            msg.twist.twist.linear.z
        ])

        # Extract heading (yaw from quaternion)
        # NED frame: heading is measured from North (X-axis)
        q = msg.pose.pose.orientation
        # Standard yaw calculation - add pi to flip from tail to head direction
        self.heading = np.arctan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y**2 + q.z**2)
        ) + np.pi

        # Normalize to [-pi, pi]
        while self.heading > np.pi:
            self.heading -= 2 * np.pi
        while self.heading < -np.pi:
            self.heading += 2 * np.pi

        self.state_received = True

    def sonar_callback(self, msg):
        """
        Process FLS sonar data
        TODO: Replace with actual Stonefish FLS message type
        """
        # Placeholder - will extract intensity array from FLS message
        self.sonar_intensities = np.array(msg.data)

    def start_callback(self, request, response):
        """Start navigation service callback"""
        if self.navigation_active:
            response.success = True
            response.message = 'Navigation already active'
        else:
            self.navigation_active = True
            response.success = True
            response.message = 'Navigation started'
            self.get_logger().info('Navigation STARTED via service call')
        return response

    def stop_callback(self, request, response):
        """Stop navigation service callback"""
        self.navigation_active = False
        self.publish_zero_velocity()
        response.success = True
        response.message = 'Navigation stopped'
        self.get_logger().info('Navigation STOPPED via service call')
        return response

    def control_loop(self):
        """Main control loop - runs at control_frequency Hz"""
        if not self.state_received:
            self.get_logger().warn('No odometry received yet', throttle_duration_sec=5.0)
            return

        if not self.navigation_active:
            self.publish_zero_velocity()
            return

        # Check if goal reached
        distance_to_goal = np.linalg.norm(self.position - self.goal)

        if distance_to_goal < self.goal_tolerance:
            # Goal reached - stop
            self.publish_zero_velocity()
            self.get_logger().info('Goal reached!', throttle_duration_sec=5.0)
            return

        # Calculate goal bearing (global frame)
        goal_bearing = np.arctan2(
            self.goal[1] - self.position[1],
            self.goal[0] - self.position[0]
        )

        # TODO: For now, use simple direct navigation without sonar
        # Will integrate SPD2C once FLS is working
        # Step 1: SPD2C - Generate reference commands from sonar scan
        # spd2c_output = self.spd2c.process(
        #     self.sonar_intensities,
        #     goal_bearing,
        #     self.heading
        # )

        # Simple direct navigation to goal
        heading_error = goal_bearing - self.heading
        # Normalize to [-pi, pi]
        while heading_error > np.pi:
            heading_error -= 2 * np.pi
        while heading_error < -np.pi:
            heading_error += 2 * np.pi

        # EROAS-inspired control: reduce speed when heading error is large
        # If heading error > 90 degrees, stop and rotate in place
        abs_heading_error = abs(heading_error)

        if abs_heading_error > np.deg2rad(90):
            # Large heading error: rotate in place, no forward motion
            vx_ref = 0.0
            Kt = 1.0  # Moderate rotation speed
        else:
            # Small heading error: move forward with speed proportional to alignment
            max_heading_error = np.deg2rad(45)  # 45 degrees tolerance
            heading_factor = max(0.0, 1.0 - abs_heading_error / max_heading_error)

            v_max = 0.8
            vx_ref = v_max * heading_factor
            vx_ref = max(0.2, vx_ref)  # Minimum forward speed when heading is good
            Kt = 1.5  # Faster rotation when moving

        # Yaw rate control
        yaw_rate_ref = Kt * heading_error
        yaw_rate_ref = np.clip(yaw_rate_ref, -1.0, 1.0)

        # Depth control
        depth_error = self.goal[2] - self.position[2]
        vz_ref = 0.5 * depth_error
        vz_ref = np.clip(vz_ref, -0.5, 0.5)

        # Construct reference velocity vector
        v_ref = np.array([vx_ref, 0.0, vz_ref])
        r_ref = yaw_rate_ref

        # TODO: Step 2: SCG - Update obstacle memory (disabled until FLS working)
        # TODO: Step 3: ST-CBF - Filter velocity for safety (disabled until FLS working)

        # For now, directly publish reference velocity without obstacle avoidance
        v_safe = v_ref

        # Step 4: Publish safe velocity command
        self.publish_velocity(v_safe, r_ref)

        # Step 5: Publish visualization markers
        self.publish_visualization(v_safe, r_ref)

        # Debug logging - use INFO to see it
        self.get_logger().info(
            f'Pos: [{self.position[0]:.2f}, {self.position[1]:.2f}, {self.position[2]:.2f}], '
            f'Dist: {distance_to_goal:.2f}m, '
            f'Hdg_err: {np.rad2deg(heading_error):.1f}deg, '
            f'vx: {vx_ref:.2f}m/s, yaw_rate: {np.rad2deg(yaw_rate_ref):.1f}deg/s',
            throttle_duration_sec=1.0
        )

    def publish_velocity(self, velocity: np.ndarray, yaw_rate: float):
        """Publish velocity command"""
        cmd = Twist()
        cmd.linear.x = float(velocity[0])
        cmd.linear.y = float(velocity[1])
        cmd.linear.z = float(velocity[2])
        cmd.angular.x = 0.0
        cmd.angular.y = 0.0
        cmd.angular.z = float(yaw_rate)

        self.cmd_vel_pub.publish(cmd)

    def publish_zero_velocity(self):
        """Stop the vehicle"""
        cmd = Twist()
        self.cmd_vel_pub.publish(cmd)

    def publish_visualization(self, velocity: np.ndarray, yaw_rate: float):
        """Publish visualization markers for RViz"""
        markers = MarkerArray()
        now = self.get_clock().now().to_msg()

        # NOTE: RViz uses ENU (East-North-Up) but we use NED (North-East-Down)
        # Proper coordinate transformation: ENU_X=NED_Y, ENU_Y=NED_X, ENU_Z=-NED_Z

        # Marker 1: Start position (yellow sphere) - floating in air like Stonefish
        # Stonefish has it at z=-1.0 (1m above water surface)
        start_marker = Marker()
        start_marker.header.frame_id = "world_ned"
        start_marker.header.stamp = now
        start_marker.ns = "waypoints"
        start_marker.id = 0
        start_marker.type = Marker.SPHERE
        start_marker.action = Marker.ADD
        start_marker.pose.position.x = 0.0  # NED Y (East)
        start_marker.pose.position.y = 0.0  # NED X (North)
        start_marker.pose.position.z = 1.0  # -NED Z (Up)
        start_marker.pose.orientation.w = 1.0
        start_marker.scale.x = 0.5
        start_marker.scale.y = 0.5
        start_marker.scale.z = 0.5
        start_marker.color.r = 1.0
        start_marker.color.g = 1.0
        start_marker.color.b = 0.0
        start_marker.color.a = 1.0
        markers.markers.append(start_marker)

        # Marker 2: Goal position (red sphere) - floating in air like Stonefish
        # Stonefish has it at z=-1.0 (1m above water surface)
        goal_marker = Marker()
        goal_marker.header.frame_id = "world_ned"
        goal_marker.header.stamp = now
        goal_marker.ns = "waypoints"
        goal_marker.id = 1
        goal_marker.type = Marker.SPHERE
        goal_marker.action = Marker.ADD
        goal_marker.pose.position.x = float(self.goal[1])  # NED Y (East)
        goal_marker.pose.position.y = float(self.goal[0])  # NED X (North)
        goal_marker.pose.position.z = 1.0  # -NED Z (Up)
        goal_marker.pose.orientation.w = 1.0
        goal_marker.scale.x = 0.5
        goal_marker.scale.y = 0.5
        goal_marker.scale.z = 0.5
        goal_marker.color.r = 1.0
        goal_marker.color.g = 0.0
        goal_marker.color.b = 0.0
        goal_marker.color.a = 1.0
        markers.markers.append(goal_marker)

        # Marker 3: Current AUV position (green sphere)
        auv_marker = Marker()
        auv_marker.header.frame_id = "world_ned"
        auv_marker.header.stamp = now
        auv_marker.ns = "auv"
        auv_marker.id = 2
        auv_marker.type = Marker.SPHERE
        auv_marker.action = Marker.ADD
        auv_marker.pose.position.x = float(self.position[1])  # NED Y (East)
        auv_marker.pose.position.y = float(self.position[0])  # NED X (North)
        auv_marker.pose.position.z = -float(self.position[2])  # -NED Z (Up)
        auv_marker.pose.orientation.w = 1.0
        auv_marker.scale.x = 0.3
        auv_marker.scale.y = 0.3
        auv_marker.scale.z = 0.3
        auv_marker.color.r = 0.0
        auv_marker.color.g = 1.0
        auv_marker.color.b = 0.0
        auv_marker.color.a = 1.0
        markers.markers.append(auv_marker)

        # Marker 4: Heading arrow (blue)
        heading_marker = Marker()
        heading_marker.header.frame_id = "world_ned"
        heading_marker.header.stamp = now
        heading_marker.ns = "heading"
        heading_marker.id = 3
        heading_marker.type = Marker.ARROW
        heading_marker.action = Marker.ADD
        heading_marker.pose.position.x = float(self.position[1])  # NED Y (East)
        heading_marker.pose.position.y = float(self.position[0])  # NED X (North)
        heading_marker.pose.position.z = -float(self.position[2])  # -NED Z (Up)

        # Convert heading to quaternion for ENU frame
        # NED heading (from North) → ENU heading (from East)
        enu_heading = np.pi/2 - self.heading
        cy = np.cos(enu_heading * 0.5)
        sy = np.sin(enu_heading * 0.5)
        heading_marker.pose.orientation.x = 0.0
        heading_marker.pose.orientation.y = 0.0
        heading_marker.pose.orientation.z = sy
        heading_marker.pose.orientation.w = cy

        heading_marker.scale.x = 1.5  # Arrow length
        heading_marker.scale.y = 0.1  # Arrow width
        heading_marker.scale.z = 0.1  # Arrow height
        heading_marker.color.r = 0.0
        heading_marker.color.g = 0.0
        heading_marker.color.b = 1.0
        heading_marker.color.a = 1.0
        markers.markers.append(heading_marker)

        # Marker 5: Velocity vector (cyan)
        if np.linalg.norm(velocity) > 0.01:
            vel_marker = Marker()
            vel_marker.header.frame_id = "world_ned"
            vel_marker.header.stamp = now
            vel_marker.ns = "velocity"
            vel_marker.id = 4
            vel_marker.type = Marker.ARROW
            vel_marker.action = Marker.ADD

            # Start point (NED → ENU)
            vel_marker.points.append(Point(
                x=float(self.position[1]),  # NED Y
                y=float(self.position[0]),  # NED X
                z=-float(self.position[2])  # -NED Z
            ))

            # End point (velocity in body frame, need to convert to world frame)
            vel_world_x_ned = float(self.position[0] + velocity[0] * np.cos(self.heading) - velocity[1] * np.sin(self.heading))
            vel_world_y_ned = float(self.position[1] + velocity[0] * np.sin(self.heading) + velocity[1] * np.cos(self.heading))
            vel_world_z_ned = float(self.position[2] + velocity[2])

            # Convert NED to ENU
            vel_marker.points.append(Point(
                x=vel_world_y_ned,  # NED Y → ENU X
                y=vel_world_x_ned,  # NED X → ENU Y
                z=-vel_world_z_ned  # -NED Z → ENU Z
            ))

            vel_marker.scale.x = 0.1  # Shaft diameter
            vel_marker.scale.y = 0.2  # Head diameter
            vel_marker.color.r = 0.0
            vel_marker.color.g = 1.0
            vel_marker.color.b = 1.0
            vel_marker.color.a = 1.0
            markers.markers.append(vel_marker)

        # Publish all markers
        self.marker_pub.publish(markers)

        # Publish path (simple straight line from start to goal)
        path = Path()
        path.header.frame_id = "world_ned"
        path.header.stamp = now

        # Start pose (NED → ENU)
        start_pose = PoseStamped()
        start_pose.header = path.header
        start_pose.pose.position.x = 0.0  # NED Y
        start_pose.pose.position.y = 0.0  # NED X
        start_pose.pose.position.z = -3.0  # -NED Z
        start_pose.pose.orientation.w = 1.0
        path.poses.append(start_pose)

        # Goal pose (NED → ENU)
        goal_pose = PoseStamped()
        goal_pose.header = path.header
        goal_pose.pose.position.x = float(self.goal[1])  # NED Y
        goal_pose.pose.position.y = float(self.goal[0])  # NED X
        goal_pose.pose.position.z = -float(self.goal[2])  # -NED Z
        goal_pose.pose.orientation.w = 1.0
        path.poses.append(goal_pose)

        self.path_pub.publish(path)


def main(args=None):
    rclpy.init(args=args)

    node = EROASNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()