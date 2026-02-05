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
from sensor_msgs.msg import PointCloud2
from visualization_msgs.msg import Marker, MarkerArray
from geometry_msgs.msg import PoseStamped, Vector3
import sensor_msgs_py.point_cloud2 as pc2
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

        # FLS point cloud subscription
        self.fls_sub = self.create_subscription(
            PointCloud2,
            f'/{self.namespace}/fls_pointcloud',
            self.fls_callback,
            10
        )

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

        # Visualization timer (slower rate, independent of navigation state)
        self.viz_timer = self.create_timer(
            0.5,  # 2 Hz
            self.publish_visualization
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

    def fls_callback(self, msg: PointCloud2):
        """
        Process FLS point cloud data
        Converts to beam intensities for SPD2C and updates SCG obstacle memory
        """
        try:
            # Convert PointCloud2 to numpy array
            points = []
            intensities = []

            for point in pc2.read_points(msg, field_names=("x", "y", "z", "intensity"), skip_nans=True):
                points.append([point[0], point[1], point[2]])
                intensities.append(point[3])

            if len(points) == 0:
                # No obstacles detected
                self.sonar_intensities = np.zeros(512)
                return

            points = np.array(points)
            intensities = np.array(intensities)

            # Convert 3D points to 1D beam intensity array for SPD2C
            self.sonar_intensities = self._pointcloud_to_beams(points, intensities)

            # Transform points from FLS frame to world NED frame
            points_world = self._transform_to_world(points)

            # Update SCG obstacle memory
            timestamp = self.get_clock().now().seconds_nanoseconds()[0]
            self.scg.update(points_world, self.position, timestamp)

        except Exception as e:
            self.get_logger().error(f'Error in FLS callback: {str(e)}')

    def _pointcloud_to_beams(self, points: np.ndarray, intensities: np.ndarray) -> np.ndarray:
        """
        Convert 3D point cloud to 1D beam intensity array
        Projects points onto horizontal plane and bins by angle

        Args:
            points: Nx3 array of points in FLS frame
            intensities: N array of intensity values

        Returns:
            512-element beam intensity array
        """
        beam_intensities = np.zeros(512)
        fov_h = np.deg2rad(90.0)

        for i, point in enumerate(points):
            x, y, z = point

            # Calculate bearing angle in horizontal plane
            angle = np.arctan2(y, x)

            # Check if within FOV
            if abs(angle) > fov_h / 2:
                continue

            # Map angle to beam index
            # Angle range: [-45°, 45°] → beam index [0, 511]
            beam_idx = int((angle + fov_h/2) / fov_h * 512)
            beam_idx = np.clip(beam_idx, 0, 511)

            # Use actual intensity from point cloud
            # Take maximum intensity per beam (closest/strongest obstacle)
            beam_intensities[beam_idx] = max(beam_intensities[beam_idx], intensities[i])

        return beam_intensities

    def _transform_to_world(self, points: np.ndarray) -> np.ndarray:
        """
        Transform points from FLS frame to world NED frame

        FLS frame: origin at sensor, X forward, Y right, Z down
        World NED: origin at (0,0,0), X north, Y east, Z down

        Args:
            points: Nx3 array of points in FLS frame

        Returns:
            Nx3 array of points in world NED frame
        """
        # FLS is mounted at vehicle front: xyz="-0.75 0.0 0.0"
        # FLS orientation: rpy="1.5708 0.0 -1.5708"
        # This means FLS X-axis aligns with vehicle X-axis (forward)

        # Rotate points by vehicle heading (yaw in NED frame)
        cos_h = np.cos(self.heading)
        sin_h = np.sin(self.heading)

        points_world = np.zeros_like(points)
        for i, point in enumerate(points):
            # Rotate by heading (yaw) in NED horizontal plane
            x_rel = point[0] * cos_h - point[1] * sin_h
            y_rel = point[0] * sin_h + point[1] * cos_h
            z_rel = point[2]

            # Translate to world frame (add vehicle position)
            # Also account for FLS sensor offset (-0.75m in vehicle X)
            fls_offset_x = -0.75 * cos_h
            fls_offset_y = -0.75 * sin_h

            points_world[i] = [
                self.position[0] + x_rel + fls_offset_x,
                self.position[1] + y_rel + fls_offset_y,
                self.position[2] + z_rel
            ]

        return points_world

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

        # ============================================================
        # EROAS PIPELINE: SPD2C → SCG → ST-CBF
        # ============================================================

        # Step 1: SPD2C - Generate reference commands from sonar scan
        spd2c_output = self.spd2c.process(
            self.sonar_intensities,
            goal_bearing,
            self.heading
        )

        # Extract reference velocity and yaw rate from SPD2C
        v_ref = np.array([spd2c_output.vx_ref, spd2c_output.vy_ref, spd2c_output.vz_ref])
        r_ref = spd2c_output.r_ref

        # Add depth control (independent of horizontal navigation)
        depth_error = self.goal[2] - self.position[2]
        v_ref[2] = 0.5 * depth_error
        v_ref[2] = np.clip(v_ref[2], -0.5, 0.5)

        # Step 2: SCG - Get closest obstacle from memory
        closest_obstacle = self.scg.get_closest_obstacle(
            self.position,
            mode='H'  # Horizontal mode for 2D navigation
        )

        # Step 3: ST-CBF - Filter velocity for safety
        v_safe = self.stcbf.filter(
            v_ref,
            self.position,
            closest_obstacle,
            mode='H'
        )

        # Step 4: Publish safe velocity command
        self.publish_velocity(v_safe, r_ref)

        # Debug logging
        obstacle_status = "obstacle detected" if closest_obstacle is not None else "clear"
        obstacle_dist = np.linalg.norm(self.position[:2] - closest_obstacle[:2]) if closest_obstacle is not None else float('inf')

        self.get_logger().info(
            f'Pos: [{self.position[0]:.2f}, {self.position[1]:.2f}, {self.position[2]:.2f}], '
            f'Dist: {distance_to_goal:.2f}m, '
            f'vx_ref: {spd2c_output.vx_ref:.2f}→{v_safe[0]:.2f}m/s, '
            f'SCG: {self.scg.get_memory_size()} pts, '
            f'Obstacle: {obstacle_status} ({obstacle_dist:.2f}m)',
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

    def publish_visualization(self):
        """Publish visualization markers for RViz"""
        if not self.state_received:
            return

        markers = MarkerArray()
        now = self.get_clock().now().to_msg()

        # NOTE: RViz uses ENU (East-North-Up) but we use NED (North-East-Down)
        # Proper coordinate transformation: ENU_X=NED_Y, ENU_Y=NED_X, ENU_Z=-NED_Z

        # Marker 1: Start position (yellow sphere)
        start_marker = Marker()
        start_marker.header.frame_id = "world_ned"
        start_marker.header.stamp = now
        start_marker.ns = "waypoints"
        start_marker.id = 0
        start_marker.type = Marker.SPHERE
        start_marker.action = Marker.ADD
        # NED to ENU transformation (same as waypoint_navigator.py)
        start_marker.pose.position.x = 0.0  # NED Y -> ENU X
        start_marker.pose.position.y = 0.0  # NED X -> ENU Y
        start_marker.pose.position.z = -(-1.0)  # -NED Z -> ENU Z (start at z=-1.0 in NED)
        start_marker.pose.orientation.w = 1.0
        start_marker.scale.x = 1.0
        start_marker.scale.y = 1.0
        start_marker.scale.z = 1.0
        start_marker.color.r = 1.0
        start_marker.color.g = 1.0
        start_marker.color.b = 0.0
        start_marker.color.a = 1.0
        markers.markers.append(start_marker)

        # Marker 2: Goal position (red sphere)
        goal_marker = Marker()
        goal_marker.header.frame_id = "world_ned"
        goal_marker.header.stamp = now
        goal_marker.ns = "waypoints"
        goal_marker.id = 1
        goal_marker.type = Marker.SPHERE
        goal_marker.action = Marker.ADD
        # NED to ENU transformation (same as waypoint_navigator.py)
        goal_marker.pose.position.x = float(self.goal[1])  # NED Y -> ENU X
        goal_marker.pose.position.y = float(self.goal[0])  # NED X -> ENU Y
        goal_marker.pose.position.z = -float(self.goal[2])  # -NED Z -> ENU Z
        goal_marker.pose.orientation.w = 1.0
        goal_marker.scale.x = 1.0
        goal_marker.scale.y = 1.0
        goal_marker.scale.z = 1.0
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