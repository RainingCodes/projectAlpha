#!/usr/bin/env python3
"""
FLS Data Recorder
Records FLS sensor data along with pose information for mapping
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from nav_msgs.msg import Odometry
from cv_bridge import CvBridge
import numpy as np
import pickle
import os
from datetime import datetime


class FLSRecorder(Node):
    """
    Records FLS data with synchronized pose information
    Saves data for offline mapping and analysis
    """

    def __init__(self):
        super().__init__('fls_recorder')

        # Parameters
        self.declare_parameter('namespace', 'GIRONA500')
        self.namespace = self.get_parameter('namespace').value

        self.declare_parameter('output_dir', '/tmp/fls_data')
        self.output_dir = self.get_parameter('output_dir').value

        self.declare_parameter('record_enabled', True)
        self.record_enabled = self.get_parameter('record_enabled').value

        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)

        # CV Bridge
        self.bridge = CvBridge()

        # Data storage
        self.fls_data = []  # List of (timestamp, pose, image_data)
        self.current_pose = None

        # Subscribe to FLS
        self.fls_sub = self.create_subscription(
            Image,
            f'/{self.namespace}/fls',
            self.fls_callback,
            10
        )

        # Subscribe to odometry
        self.odom_sub = self.create_subscription(
            Odometry,
            f'/{self.namespace}/dynamics',
            self.odom_callback,
            10
        )

        # Statistics
        self.frame_count = 0
        self.last_save_time = self.get_clock().now()

        # Auto-save timer (every 10 seconds)
        self.save_timer = self.create_timer(10.0, self.auto_save)

        self.get_logger().info('FLS Recorder initialized')
        self.get_logger().info(f'Namespace: {self.namespace}')
        self.get_logger().info(f'Output directory: {self.output_dir}')
        self.get_logger().info(f'Recording: {"ENABLED" if self.record_enabled else "DISABLED"}')

    def odom_callback(self, msg: Odometry):
        """Store current pose"""
        self.current_pose = {
            'position': {
                'x': msg.pose.pose.position.x,
                'y': msg.pose.pose.position.y,
                'z': msg.pose.pose.position.z
            },
            'orientation': {
                'x': msg.pose.pose.orientation.x,
                'y': msg.pose.pose.orientation.y,
                'z': msg.pose.pose.orientation.z,
                'w': msg.pose.pose.orientation.w
            }
        }

    def fls_callback(self, msg: Image):
        """Record FLS data with pose"""
        if not self.record_enabled or self.current_pose is None:
            return

        try:
            # Convert image to numpy array
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='passthrough')

            # Create data record
            timestamp = self.get_clock().now().nanoseconds / 1e9
            record = {
                'timestamp': timestamp,
                'pose': self.current_pose.copy(),
                'fls_data': cv_image.copy(),
                'encoding': msg.encoding,
                'width': msg.width,
                'height': msg.height
            }

            self.fls_data.append(record)
            self.frame_count += 1

            # Log progress
            if self.frame_count % 50 == 0:
                self.get_logger().info(
                    f'Recorded {self.frame_count} FLS frames, '
                    f'Data size: {len(self.fls_data)} records'
                )

        except Exception as e:
            self.get_logger().error(f'Error recording FLS data: {str(e)}')

    def auto_save(self):
        """Auto-save recorded data"""
        if len(self.fls_data) > 0:
            self.save_data()

    def save_data(self):
        """Save recorded data to file"""
        if len(self.fls_data) == 0:
            return

        try:
            # Generate filename with timestamp
            timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = os.path.join(
                self.output_dir,
                f'fls_recording_{timestamp_str}.pkl'
            )

            # Save data
            with open(filename, 'wb') as f:
                pickle.dump({
                    'metadata': {
                        'namespace': self.namespace,
                        'total_frames': len(self.fls_data),
                        'recording_date': timestamp_str
                    },
                    'data': self.fls_data
                }, f)

            self.get_logger().info(
                f'Saved {len(self.fls_data)} FLS records to {filename}'
            )

            # Clear data after saving
            self.fls_data = []
            self.frame_count = 0

        except Exception as e:
            self.get_logger().error(f'Error saving FLS data: {str(e)}')

    def destroy_node(self):
        """Save any remaining data before shutdown"""
        if len(self.fls_data) > 0:
            self.get_logger().info('Saving remaining data before shutdown...')
            self.save_data()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)

    node = FLSRecorder()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()