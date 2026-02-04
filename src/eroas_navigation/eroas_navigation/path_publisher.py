#!/usr/bin/env python3
"""
Path Publisher - publishes vehicle trajectory as nav_msgs/Path for rviz.
"""

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry, Path
from geometry_msgs.msg import PoseStamped


class PathPublisher(Node):
    def __init__(self):
        super().__init__('path_publisher')

        self.declare_parameter('namespace', 'GIRONA500')
        self.namespace = self.get_parameter('namespace').value

        self.declare_parameter('max_path_length', 2000)
        self.max_path_length = self.get_parameter('max_path_length').value

        self.path_msg = Path()
        self.path_msg.header.frame_id = 'world_ned'

        self.odom_sub = self.create_subscription(
            Odometry,
            f'/{self.namespace}/dynamics',
            self.odom_callback,
            10
        )

        self.path_pub = self.create_publisher(Path, f'/{self.namespace}/path', 10)

        self.get_logger().info(f'Path publisher: /{self.namespace}/dynamics -> /{self.namespace}/path')

    def odom_callback(self, msg: Odometry):
        pose = PoseStamped()
        pose.header = msg.header
        pose.header.frame_id = 'world_ned'
        # NED → ENU conversion to match eroas_node marker convention
        pose.pose.position.x = msg.pose.pose.position.y   # NED Y (East) → rviz X
        pose.pose.position.y = msg.pose.pose.position.x   # NED X (North) → rviz Y
        pose.pose.position.z = -msg.pose.pose.position.z  # -NED Z (Up) → rviz Z
        pose.pose.orientation = msg.pose.pose.orientation

        self.path_msg.poses.append(pose)

        if len(self.path_msg.poses) > self.max_path_length:
            self.path_msg.poses = self.path_msg.poses[-self.max_path_length:]

        self.path_msg.header.stamp = msg.header.stamp
        self.path_pub.publish(self.path_msg)


def main(args=None):
    rclpy.init(args=args)
    node = PathPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
