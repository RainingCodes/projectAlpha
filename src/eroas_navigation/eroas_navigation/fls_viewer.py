#!/usr/bin/env python3
"""
FLS (Forward Looking Sonar) Viewer - Polar Fan Display
Displays sonar data in a fan-shaped polar coordinate view,
similar to real sonar displays.
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2
import numpy as np
import math


class FLSViewer(Node):
    def __init__(self):
        super().__init__('fls_viewer')

        self.declare_parameter('namespace', 'GIRONA500')
        self.namespace = self.get_parameter('namespace').value

        self.declare_parameter('window_name', 'FLS - Forward Looking Sonar')
        self.window_name = self.get_parameter('window_name').value

        # FLS sensor parameters (must match girona500_robot.scn)
        self.declare_parameter('horizontal_fov', 60.0)
        self.declare_parameter('range_min', 1.0)
        self.declare_parameter('range_max', 10.0)

        self.fov = self.get_parameter('horizontal_fov').value
        self.range_min = self.get_parameter('range_min').value
        self.range_max = self.get_parameter('range_max').value

        # Display settings
        self.declare_parameter('display_size', 400)
        self.declare_parameter('window_x', -1)
        self.declare_parameter('window_y', -1)

        self.display_size = self.get_parameter('display_size').value
        self.window_x = self.get_parameter('window_x').value
        self.window_y = self.get_parameter('window_y').value

        self.bridge = CvBridge()

        # Subscribe to raw FLS image
        self.fls_sub = self.create_subscription(
            Image,
            f'/{self.namespace}/fls',
            self.fls_callback,
            10
        )

        self.fan_image = None
        self.lookup_table = None

        cv2.namedWindow(self.window_name, cv2.WINDOW_AUTOSIZE)
        if self.window_x >= 0 and self.window_y >= 0:
            cv2.moveWindow(self.window_name, self.window_x, self.window_y)

        self.frame_count = 0
        self.last_log_time = self.get_clock().now()

        self.get_logger().info(f'FLS Viewer: FOV={self.fov}deg, '
                               f'Range={self.range_min}-{self.range_max}m')

    def _build_lookup_table(self, n_beams, n_bins):
        """Pre-compute pixel-to-beam/bin mapping for polar display."""
        size = self.display_size
        cx = size // 2
        cy = 20  # top margin, fan opens downward

        half_fov = math.radians(self.fov / 2.0)
        max_radius = size - cy - 40  # leave bottom margin

        lut_beam = np.full((size, size), -1, dtype=np.int32)
        lut_bin = np.full((size, size), -1, dtype=np.int32)

        for y in range(size):
            for x in range(size):
                dx = x - cx
                dy = y - cy
                r = math.sqrt(dx * dx + dy * dy)
                if r < 1.0 or r > max_radius:
                    continue

                angle = math.atan2(dx, dy)  # angle from center-down
                if abs(angle) > half_fov:
                    continue

                # Map radius to bin index
                bin_frac = r / max_radius
                bin_idx = int(bin_frac * n_bins)
                if bin_idx >= n_bins:
                    continue

                # Map angle to beam index
                beam_frac = (angle + half_fov) / (2.0 * half_fov)
                beam_idx = int(beam_frac * n_beams)
                if beam_idx >= n_beams:
                    beam_idx = n_beams - 1

                lut_beam[y, x] = beam_idx
                lut_bin[y, x] = bin_idx

        self.lookup_table = (lut_beam, lut_bin)
        self.get_logger().info(f'Lookup table built: {n_beams}x{n_bins} -> {size}x{size}')

    def _draw_overlay(self, image, n_beams, n_bins):
        """Draw range rings and angle lines on the fan display."""
        size = self.display_size
        cx = size // 2
        cy = 20
        half_fov = math.radians(self.fov / 2.0)
        max_radius = size - cy - 40

        color = (0, 180, 0)  # green overlay

        # Range rings
        n_rings = 5
        for i in range(1, n_rings + 1):
            r = int(max_radius * i / n_rings)
            range_val = self.range_min + (self.range_max - self.range_min) * i / n_rings

            start_angle_deg = 90 - math.degrees(half_fov)
            end_angle_deg = 90 + math.degrees(half_fov)
            cv2.ellipse(image, (cx, cy), (r, r),
                        -90, -math.degrees(half_fov), math.degrees(half_fov),
                        color, 1, cv2.LINE_AA)

            # Range label
            label_x = cx + int(r * math.sin(half_fov)) + 5
            label_y = cy + int(r * math.cos(half_fov))
            cv2.putText(image, f'{range_val:.0f}m',
                        (label_x, label_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)

        # Boundary lines
        for sign in [-1, 1]:
            angle = sign * half_fov
            ex = cx + int(max_radius * math.sin(angle))
            ey = cy + int(max_radius * math.cos(angle))
            cv2.line(image, (cx, cy), (ex, ey), color, 1, cv2.LINE_AA)

        # Center line
        cv2.line(image, (cx, cy), (cx, cy + max_radius),
                 (0, 100, 0), 1, cv2.LINE_AA)

        # Info text
        cv2.putText(image, f'FLS {self.namespace} | FOV:{self.fov:.0f}deg | '
                    f'Range:{self.range_min:.0f}-{self.range_max:.0f}m | '
                    f'Frame:{self.frame_count}',
                    (10, size - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1, cv2.LINE_AA)

    def fls_callback(self, msg: Image):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='passthrough')

            # Get dimensions: width=beams (azimuth), height=bins (range)
            n_bins, n_beams = cv_image.shape[:2]

            # Build lookup table on first frame
            if self.lookup_table is None:
                self._build_lookup_table(n_beams, n_bins)

            # Normalize to uint8
            if cv_image.dtype == np.float32 or cv_image.dtype == np.float64:
                img_u8 = cv2.normalize(cv_image, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            elif cv_image.dtype == np.uint8:
                img_u8 = cv_image
            else:
                img_u8 = (cv_image / cv_image.max() * 255).astype(np.uint8) if cv_image.max() > 0 else cv_image.astype(np.uint8)

            # Handle multi-channel images
            if len(img_u8.shape) == 3:
                img_u8 = cv2.cvtColor(img_u8, cv2.COLOR_BGR2GRAY)

            # Create fan display
            size = self.display_size
            fan = np.zeros((size, size), dtype=np.uint8)

            lut_beam, lut_bin = self.lookup_table
            valid = (lut_beam >= 0) & (lut_bin >= 0)
            fan[valid] = img_u8[lut_bin[valid], lut_beam[valid]]

            # Apply sonar-style green colormap
            fan_colored = np.zeros((size, size, 3), dtype=np.uint8)
            fan_colored[:, :, 1] = fan  # green channel
            fan_colored[:, :, 0] = fan // 4  # slight blue
            fan_colored[:, :, 2] = fan // 6  # slight red

            # Draw overlay
            self._draw_overlay(fan_colored, n_beams, n_bins)


            cv2.imshow(self.window_name, fan_colored)
            cv2.waitKey(1)

            self.frame_count += 1

            now = self.get_clock().now()
            if (now - self.last_log_time).nanoseconds > 5e9:
                fps = self.frame_count / 5.0
                self.get_logger().info(
                    f'FLS: {fps:.1f} Hz, {n_beams}x{n_bins}, enc={msg.encoding}')
                self.frame_count = 0
                self.last_log_time = now

        except Exception as e:
            self.get_logger().error(f'FLS error: {str(e)}')

    def destroy_node(self):
        cv2.destroyAllWindows()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = FLSViewer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
