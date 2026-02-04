#!/usr/bin/env python3
"""
Multi-waypoint Navigator for EROAS
Navigates through a sequence of waypoints and returns to start
"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, Point
from nav_msgs.msg import Odometry, Path
from std_msgs.msg import ColorRGBA
from std_srvs.srv import Trigger
from visualization_msgs.msg import Marker, MarkerArray
from geometry_msgs.msg import PoseStamped
import numpy as np
from typing import List, Tuple


class WaypointNavigator(Node):
    """
    Multi-waypoint navigation node
    Navigates through a list of waypoints and visualizes the path
    """

    def __init__(self):
        super().__init__('waypoint_navigator')

        # Parameters
        self.declare_parameter('namespace', 'GIRONA500')
        self.namespace = self.get_parameter('namespace').value

        self.declare_parameter('control_frequency', 10.0)
        self.control_freq = self.get_parameter('control_frequency').value

        # Waypoint tolerance (meters)
        self.declare_parameter('waypoint_tolerance', 1.5)
        self.waypoint_tolerance = self.get_parameter('waypoint_tolerance').value

        # Auto-start: if False, waits for /waypoint_nav/start service call
        self.declare_parameter('auto_start', True)
        self.navigation_active = self.get_parameter('auto_start').value

        # Define waypoints (NED coordinates: North, East, Down)
        # Square pattern: Start -> P1 -> P2 -> P3 -> Start
        self.declare_parameter('waypoint_x', [0.0, 10.0, 10.0, 0.0])
        self.declare_parameter('waypoint_y', [0.0, 0.0, 10.0, 10.0])
        self.declare_parameter('waypoint_z', [3.0, 3.0, 3.0, 3.0])

        waypoint_x = self.get_parameter('waypoint_x').value
        waypoint_y = self.get_parameter('waypoint_y').value
        waypoint_z = self.get_parameter('waypoint_z').value

        self.waypoints = [
            np.array([x, y, z])
            for x, y, z in zip(waypoint_x, waypoint_y, waypoint_z)
        ]

        # Navigation state
        self.current_waypoint_idx = 0
        self.mission_complete = False

        # Vehicle state
        self.position = np.array([0.0, 0.0, 0.0])
        self.velocity = np.array([0.0, 0.0, 0.0])
        self.heading = 0.0
        self.state_received = False

        # Path tracking
        self.traveled_path = []  # List of positions

        # ROS2 subscribers
        self.odom_sub = self.create_subscription(
            Odometry,
            f'/{self.namespace}/dynamics',
            self.odometry_callback,
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
            '/waypoint_nav/visualization_markers',
            10
        )
        self.planned_path_pub = self.create_publisher(
            Path,
            '/waypoint_nav/planned_path',
            10
        )
        self.traveled_path_pub = self.create_publisher(
            Path,
            '/waypoint_nav/traveled_path',
            10
        )

        # Start/Stop services
        self.start_srv = self.create_service(
            Trigger, '/waypoint_nav/start', self.start_callback)
        self.stop_srv = self.create_service(
            Trigger, '/waypoint_nav/stop', self.stop_callback)

        # Control timer
        self.control_timer = self.create_timer(
            1.0 / self.control_freq,
            self.control_loop
        )

        # Visualization timer (slower rate)
        self.viz_timer = self.create_timer(
            0.5,  # 2 Hz
            self.publish_visualization
        )

        self.get_logger().info('Waypoint Navigator initialized')
        self.get_logger().info(f'Namespace: {self.namespace}')
        self.get_logger().info(f'Number of waypoints: {len(self.waypoints)}')
        self.get_logger().info(f'Waypoint tolerance: {self.waypoint_tolerance}m')
        if not self.navigation_active:
            self.get_logger().info(
                'Navigation PAUSED - call /waypoint_nav/start to begin')

    def odometry_callback(self, msg: Odometry):
        """Process odometry data"""
        # Extract position
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
        q = msg.pose.pose.orientation
        self.heading = np.arctan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y**2 + q.z**2)
        ) + np.pi

        # Normalize to [-pi, pi]
        while self.heading > np.pi:
            self.heading -= 2 * np.pi
        while self.heading < -np.pi:
            self.heading += 2 * np.pi

        # Record position for traveled path
        if len(self.traveled_path) == 0 or \
           np.linalg.norm(self.position - self.traveled_path[-1]) > 0.2:
            self.traveled_path.append(self.position.copy())

        self.state_received = True

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
        """Main control loop"""
        if not self.state_received:
            return

        if not self.navigation_active:
            self.publish_zero_velocity()
            return

        if self.mission_complete:
            self.publish_zero_velocity()
            return

        # Get current target waypoint
        current_target = self.waypoints[self.current_waypoint_idx]

        # Check if reached current waypoint
        distance_to_waypoint = np.linalg.norm(self.position - current_target)

        if distance_to_waypoint < self.waypoint_tolerance:
            self.get_logger().info(
                f'Reached waypoint {self.current_waypoint_idx} '
                f'at [{current_target[0]:.1f}, {current_target[1]:.1f}, {current_target[2]:.1f}]'
            )

            # Move to next waypoint
            self.current_waypoint_idx += 1

            if self.current_waypoint_idx >= len(self.waypoints):
                self.get_logger().info('Mission complete! All waypoints visited.')
                self.mission_complete = True
                self.publish_zero_velocity()
                return

            self.get_logger().info(
                f'Moving to waypoint {self.current_waypoint_idx}: '
                f'{self.waypoints[self.current_waypoint_idx]}'
            )

        # Calculate control commands to current target
        goal_bearing = np.arctan2(
            current_target[1] - self.position[1],
            current_target[0] - self.position[0]
        )

        heading_error = goal_bearing - self.heading
        # Normalize to [-pi, pi]
        while heading_error > np.pi:
            heading_error -= 2 * np.pi
        while heading_error < -np.pi:
            heading_error += 2 * np.pi

        # Control logic: similar to basic EROAS but for waypoint navigation
        abs_heading_error = abs(heading_error)

        if abs_heading_error > np.deg2rad(90):
            # Large heading error: rotate in place
            vx_ref = 0.0
            Kt = 1.0
        else:
            # Small heading error: move forward with speed modulation
            max_heading_error = np.deg2rad(45)
            heading_factor = max(0.0, 1.0 - abs_heading_error / max_heading_error)

            # Speed control: slow down as approaching waypoint
            distance_factor = min(1.0, distance_to_waypoint / 5.0)

            v_max = 0.8
            vx_ref = v_max * heading_factor * distance_factor
            vx_ref = max(0.2, vx_ref)  # Minimum speed
            Kt = 1.5

        # Yaw rate control
        yaw_rate_ref = Kt * heading_error
        yaw_rate_ref = np.clip(yaw_rate_ref, -1.0, 1.0)

        # Depth control
        depth_error = current_target[2] - self.position[2]
        vz_ref = 0.5 * depth_error
        vz_ref = np.clip(vz_ref, -0.5, 0.5)

        # Construct velocity command
        v_ref = np.array([vx_ref, 0.0, vz_ref])

        # Publish velocity command
        self.publish_velocity(v_ref, yaw_rate_ref)

        # Debug logging
        self.get_logger().info(
            f'WP {self.current_waypoint_idx}/{len(self.waypoints)-1}: '
            f'Dist: {distance_to_waypoint:.2f}m, '
            f'Hdg_err: {np.rad2deg(heading_error):.1f}deg, '
            f'vx: {vx_ref:.2f}m/s',
            throttle_duration_sec=1.0
        )

    def publish_velocity(self, velocity: np.ndarray, yaw_rate: float):
        """Publish velocity command"""
        cmd = Twist()
        cmd.linear.x = float(velocity[0])
        cmd.linear.y = float(velocity[1])
        cmd.linear.z = float(velocity[2])
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

        # Waypoint colors (RGBA)
        waypoint_colors = [
            (0.0, 1.0, 0.0, 1.0),  # Green (start)
            (1.0, 0.5, 0.0, 1.0),  # Orange
            (1.0, 0.0, 1.0, 1.0),  # Magenta
            (0.0, 0.5, 1.0, 1.0),  # Light blue
        ]

        # Visualize all waypoints
        for i, wp in enumerate(self.waypoints):
            marker = Marker()
            marker.header.frame_id = "world_ned"
            marker.header.stamp = now
            marker.ns = "waypoints"
            marker.id = i
            marker.type = Marker.SPHERE
            marker.action = Marker.ADD

            # NED to ENU transformation
            marker.pose.position.x = float(wp[1])  # NED Y -> ENU X
            marker.pose.position.y = float(wp[0])  # NED X -> ENU Y
            marker.pose.position.z = -float(wp[2])  # -NED Z -> ENU Z
            marker.pose.orientation.w = 1.0

            # Size: current target is larger
            if i == self.current_waypoint_idx and not self.mission_complete:
                marker.scale.x = 1.0
                marker.scale.y = 1.0
                marker.scale.z = 1.0
            else:
                marker.scale.x = 0.6
                marker.scale.y = 0.6
                marker.scale.z = 0.6

            # Color
            color = waypoint_colors[i % len(waypoint_colors)]
            marker.color.r = color[0]
            marker.color.g = color[1]
            marker.color.b = color[2]
            marker.color.a = color[3]

            # Make visited waypoints semi-transparent
            if i < self.current_waypoint_idx:
                marker.color.a = 0.3

            markers.markers.append(marker)

            # Add waypoint number text
            text_marker = Marker()
            text_marker.header.frame_id = "world_ned"
            text_marker.header.stamp = now
            text_marker.ns = "waypoint_labels"
            text_marker.id = 100 + i
            text_marker.type = Marker.TEXT_VIEW_FACING
            text_marker.action = Marker.ADD
            text_marker.pose.position.x = float(wp[1])
            text_marker.pose.position.y = float(wp[0])
            text_marker.pose.position.z = -float(wp[2]) + 1.0  # Above waypoint
            text_marker.scale.z = 0.5
            text_marker.color.r = 1.0
            text_marker.color.g = 1.0
            text_marker.color.b = 1.0
            text_marker.color.a = 1.0
            text_marker.text = f"WP{i}"
            markers.markers.append(text_marker)

        # Current AUV position marker
        auv_marker = Marker()
        auv_marker.header.frame_id = "world_ned"
        auv_marker.header.stamp = now
        auv_marker.ns = "auv"
        auv_marker.id = 200
        auv_marker.type = Marker.SPHERE
        auv_marker.action = Marker.ADD
        auv_marker.pose.position.x = float(self.position[1])
        auv_marker.pose.position.y = float(self.position[0])
        auv_marker.pose.position.z = -float(self.position[2])
        auv_marker.pose.orientation.w = 1.0
        auv_marker.scale.x = 0.5
        auv_marker.scale.y = 0.5
        auv_marker.scale.z = 0.5
        auv_marker.color.r = 1.0
        auv_marker.color.g = 1.0
        auv_marker.color.b = 0.0
        auv_marker.color.a = 1.0
        markers.markers.append(auv_marker)

        # Heading arrow
        heading_marker = Marker()
        heading_marker.header.frame_id = "world_ned"
        heading_marker.header.stamp = now
        heading_marker.ns = "heading"
        heading_marker.id = 201
        heading_marker.type = Marker.ARROW
        heading_marker.action = Marker.ADD
        heading_marker.pose.position.x = float(self.position[1])
        heading_marker.pose.position.y = float(self.position[0])
        heading_marker.pose.position.z = -float(self.position[2])

        # Convert heading to ENU frame quaternion
        enu_heading = np.pi/2 - self.heading
        cy = np.cos(enu_heading * 0.5)
        sy = np.sin(enu_heading * 0.5)
        heading_marker.pose.orientation.x = 0.0
        heading_marker.pose.orientation.y = 0.0
        heading_marker.pose.orientation.z = sy
        heading_marker.pose.orientation.w = cy

        heading_marker.scale.x = 1.5
        heading_marker.scale.y = 0.15
        heading_marker.scale.z = 0.15
        heading_marker.color.r = 0.0
        heading_marker.color.g = 0.0
        heading_marker.color.b = 1.0
        heading_marker.color.a = 1.0
        markers.markers.append(heading_marker)

        self.marker_pub.publish(markers)

        # Publish planned path (all waypoints)
        planned_path = Path()
        planned_path.header.frame_id = "world_ned"
        planned_path.header.stamp = now

        for wp in self.waypoints:
            pose = PoseStamped()
            pose.header = planned_path.header
            pose.pose.position.x = float(wp[1])  # NED Y -> ENU X
            pose.pose.position.y = float(wp[0])  # NED X -> ENU Y
            pose.pose.position.z = -float(wp[2])  # -NED Z -> ENU Z
            pose.pose.orientation.w = 1.0
            planned_path.poses.append(pose)

        self.planned_path_pub.publish(planned_path)

        # Publish traveled path
        if len(self.traveled_path) > 1:
            traveled_path = Path()
            traveled_path.header.frame_id = "world_ned"
            traveled_path.header.stamp = now

            for pos in self.traveled_path:
                pose = PoseStamped()
                pose.header = traveled_path.header
                pose.pose.position.x = float(pos[1])  # NED Y -> ENU X
                pose.pose.position.y = float(pos[0])  # NED X -> ENU Y
                pose.pose.position.z = -float(pos[2])  # -NED Z -> ENU Z
                pose.pose.orientation.w = 1.0
                traveled_path.poses.append(pose)

            self.traveled_path_pub.publish(traveled_path)


def main(args=None):
    rclpy.init(args=args)

    node = WaypointNavigator()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()