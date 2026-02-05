"""
FLS to PointCloud Converter
Converts FLS Image (sensor_msgs/Image) to 3D point cloud (sensor_msgs/PointCloud2)
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, PointCloud2, PointField
from std_msgs.msg import Header
import sensor_msgs_py.point_cloud2 as pc2
import numpy as np
import cv2
from cv_bridge import CvBridge
import struct


class FLSToPointCloud(Node):
    """
    Converts FLS Image to 3D point cloud

    Subscribes to: /{namespace}/fls (sensor_msgs/Image)
    Publishes to: /{namespace}/fls_pointcloud (sensor_msgs/PointCloud2)
    """

    def __init__(self):
        super().__init__('fls_to_pointcloud')

        # Declare parameters
        self.declare_parameter('namespace', 'GIRONA500')
        self.declare_parameter('num_beams', 512)
        self.declare_parameter('num_bins', 128)
        self.declare_parameter('horizontal_fov', 90.0)  # degrees
        self.declare_parameter('vertical_fov', 20.0)    # degrees
        self.declare_parameter('range_min', 1.0)        # meters
        self.declare_parameter('range_max', 20.0)       # meters
        self.declare_parameter('intensity_threshold', 15.0)

        # Get parameters
        self.namespace = self.get_parameter('namespace').value
        self.num_beams = self.get_parameter('num_beams').value
        self.num_bins = self.get_parameter('num_bins').value
        self.h_fov = np.deg2rad(self.get_parameter('horizontal_fov').value)
        self.v_fov = np.deg2rad(self.get_parameter('vertical_fov').value)
        self.range_min = self.get_parameter('range_min').value
        self.range_max = self.get_parameter('range_max').value
        self.intensity_threshold = self.get_parameter('intensity_threshold').value

        # Pre-compute beam angles (horizontal)
        self.beam_angles = np.linspace(
            -self.h_fov / 2,
            self.h_fov / 2,
            self.num_beams
        )

        # Pre-compute range bins
        self.range_bins = np.linspace(
            self.range_min,
            self.range_max,
            self.num_bins
        )

        # CV Bridge for image conversion
        self.bridge = CvBridge()

        # Subscribers
        self.fls_sub = self.create_subscription(
            Image,
            f'/{self.namespace}/fls',
            self.fls_callback,
            10
        )

        # Publishers
        self.pc_pub = self.create_publisher(
            PointCloud2,
            f'/{self.namespace}/fls_pointcloud',
            10
        )

        self.get_logger().info('FLS to PointCloud converter initialized')
        self.get_logger().info(f'Namespace: {self.namespace}')
        self.get_logger().info(f'Beams: {self.num_beams}, Bins: {self.num_bins}')
        self.get_logger().info(f'H-FOV: {np.rad2deg(self.h_fov):.1f}°, Range: {self.range_min}-{self.range_max}m')
        self.get_logger().info(f'Intensity threshold: {self.intensity_threshold}')

    def fls_callback(self, msg: Image):
        """
        Process FLS image and convert to point cloud

        Args:
            msg: FLS image (sensor_msgs/Image)
                 Format: 32FC1 or 8UC1
                 Dimensions: num_bins (height) x num_beams (width)
        """
        try:
            # Convert ROS Image to numpy array
            # FLS format: rows = bins (range), cols = beams (angle)
            fls_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='passthrough')

            # Check dimensions
            if fls_image.shape[1] != self.num_beams or fls_image.shape[0] != self.num_bins:
                self.get_logger().warn(
                    f'FLS image size mismatch: got {fls_image.shape}, expected ({self.num_bins}, {self.num_beams})',
                    throttle_duration_sec=5.0
                )
                # Update dimensions to match actual image
                self.num_bins = fls_image.shape[0]
                self.num_beams = fls_image.shape[1]
                self.beam_angles = np.linspace(-self.h_fov/2, self.h_fov/2, self.num_beams)
                self.range_bins = np.linspace(self.range_min, self.range_max, self.num_bins)

            # Convert to float if needed
            if fls_image.dtype != np.float32:
                fls_image = fls_image.astype(np.float32)

            # Extract 3D points from FLS image
            points = []
            intensities = []

            for beam_idx in range(self.num_beams):
                # Get beam data (all range bins for this angle)
                beam_data = fls_image[:, beam_idx]

                # Find first strong return (closest obstacle)
                strong_returns = np.where(beam_data > self.intensity_threshold)[0]

                if len(strong_returns) > 0:
                    bin_idx = strong_returns[0]  # Closest return
                    range_val = self.range_bins[bin_idx]
                    angle = self.beam_angles[beam_idx]
                    intensity = beam_data[bin_idx]

                    # Convert polar (range, angle) to Cartesian (x, y, z)
                    # FLS frame: X forward, Y right, Z down (NED-like)
                    # Horizontal scan: z = 0
                    x = range_val * np.cos(angle)  # Forward component
                    y = range_val * np.sin(angle)  # Lateral component
                    z = 0.0  # 2D horizontal scan

                    points.append([x, y, z])
                    intensities.append(intensity)

            # Publish point cloud
            if len(points) > 0:
                self.publish_pointcloud(points, intensities, msg.header)
            else:
                # Publish empty point cloud
                self.publish_pointcloud([], [], msg.header)

        except Exception as e:
            self.get_logger().error(f'Error in FLS callback: {str(e)}')

    def publish_pointcloud(self, points: list, intensities: list, header: Header):
        """
        Publish point cloud with intensity field

        Args:
            points: List of [x, y, z] points
            intensities: List of intensity values
            header: Header from original FLS message
        """
        # Create PointCloud2 message
        fields = [
            PointField(name='x', offset=0, datatype=PointField.FLOAT32, count=1),
            PointField(name='y', offset=4, datatype=PointField.FLOAT32, count=1),
            PointField(name='z', offset=8, datatype=PointField.FLOAT32, count=1),
            PointField(name='intensity', offset=12, datatype=PointField.FLOAT32, count=1)
        ]

        # Pack point data
        cloud_data = []
        for i, point in enumerate(points):
            intensity = intensities[i] if i < len(intensities) else 0.0
            # Pack as binary data: x, y, z, intensity (4 floats = 16 bytes)
            cloud_data.append(struct.pack('ffff', point[0], point[1], point[2], intensity))

        # Create PointCloud2
        pc_msg = PointCloud2()
        pc_msg.header = header
        pc_msg.header.frame_id = f'{self.namespace}/fls'  # FLS sensor frame
        pc_msg.height = 1
        pc_msg.width = len(points)
        pc_msg.is_bigendian = False
        pc_msg.point_step = 16  # 4 fields * 4 bytes
        pc_msg.row_step = pc_msg.point_step * pc_msg.width
        pc_msg.is_dense = True
        pc_msg.fields = fields
        pc_msg.data = b''.join(cloud_data)

        self.pc_pub.publish(pc_msg)

        # Debug logging
        if len(points) > 0:
            self.get_logger().debug(
                f'Published point cloud: {len(points)} points',
                throttle_duration_sec=2.0
            )


def main(args=None):
    rclpy.init(args=args)

    node = FLSToPointCloud()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
