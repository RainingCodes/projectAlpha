#!/usr/bin/env python3
"""
Simple velocity to thruster command converter
Converts cmd_vel to individual thruster setpoints for Girona500
"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import Float64
import numpy as np


class CmdVelToThrusters(Node):
    """
    Converts cmd_vel to thruster setpoints

    Girona500 has 5 thrusters:
    - 2 surge (forward): ThrusterSurgePort, ThrusterSurgeStarboard
    - 2 heave (vertical): ThrusterHeaveBow, ThrusterHeaveStern
    - 1 sway (lateral): ThrusterSway
    """

    def __init__(self):
        super().__init__('cmd_vel_to_thrusters')

        # Parameters
        self.declare_parameter('namespace', 'GIRONA500')
        self.namespace = self.get_parameter('namespace').value

        # Scaling factors (tune these for better performance)
        self.declare_parameter('surge_scale', 30.0)  # Forward/backward
        self.declare_parameter('sway_scale', 30.0)   # Left/right
        self.declare_parameter('heave_scale', 30.0)  # Up/down
        self.declare_parameter('yaw_scale', 20.0)    # Rotation

        self.surge_scale = self.get_parameter('surge_scale').value
        self.sway_scale = self.get_parameter('sway_scale').value
        self.heave_scale = self.get_parameter('heave_scale').value
        self.yaw_scale = self.get_parameter('yaw_scale').value

        # Maximum thruster output (normalized -1 to 1)
        self.max_thrust = 1.0

        # Subscribe to cmd_vel
        self.cmd_vel_sub = self.create_subscription(
            Twist,
            f'/{self.namespace}/cmd_vel',
            self.cmd_vel_callback,
            10
        )

        # Publishers for each thruster
        self.surge_port_pub = self.create_publisher(
            Float64,
            f'/{self.namespace}/ThrusterSurgePort/setpoint',
            10
        )
        self.surge_starboard_pub = self.create_publisher(
            Float64,
            f'/{self.namespace}/ThrusterSurgeStarboard/setpoint',
            10
        )
        self.heave_bow_pub = self.create_publisher(
            Float64,
            f'/{self.namespace}/ThrusterHeaveBow/setpoint',
            10
        )
        self.heave_stern_pub = self.create_publisher(
            Float64,
            f'/{self.namespace}/ThrusterHeaveStern/setpoint',
            10
        )
        self.sway_pub = self.create_publisher(
            Float64,
            f'/{self.namespace}/ThrusterSway/setpoint',
            10
        )

        self.get_logger().info('Cmd_vel to thrusters converter initialized')
        self.get_logger().info(f'Namespace: {self.namespace}')

    def cmd_vel_callback(self, msg: Twist):
        """Convert cmd_vel to thruster commands"""
        # Extract velocity commands
        vx = msg.linear.x   # Forward velocity
        vy = msg.linear.y   # Lateral velocity
        vz = msg.linear.z   # Vertical velocity
        yaw_rate = msg.angular.z  # Yaw rate

        # Calculate thruster commands
        # Surge thrusters: forward velocity + yaw contribution
        surge_forward = vx * self.surge_scale
        yaw_contribution = yaw_rate * self.yaw_scale

        surge_port = surge_forward - yaw_contribution
        surge_starboard = surge_forward + yaw_contribution

        # Sway thruster: lateral velocity
        sway = vy * self.sway_scale

        # Heave thrusters: vertical velocity
        # NOTE: Negated because NED frame (positive Z = down) + inverted_setpoint
        heave = -vz * self.heave_scale

        # Clip to max thrust
        surge_port = np.clip(surge_port, -self.max_thrust, self.max_thrust)
        surge_starboard = np.clip(surge_starboard, -self.max_thrust, self.max_thrust)
        sway = np.clip(sway, -self.max_thrust, self.max_thrust)
        heave = np.clip(heave, -self.max_thrust, self.max_thrust)

        # Publish thruster commands
        self.surge_port_pub.publish(Float64(data=float(surge_port)))
        self.surge_starboard_pub.publish(Float64(data=float(surge_starboard)))
        self.heave_bow_pub.publish(Float64(data=float(heave)))
        self.heave_stern_pub.publish(Float64(data=float(heave)))
        self.sway_pub.publish(Float64(data=float(sway)))

        # Debug logging
        self.get_logger().debug(
            f'Cmd_vel: vx={vx:.2f}, vy={vy:.2f}, vz={vz:.2f}, yaw={yaw_rate:.2f} | '
            f'Thrusters: surge_p={surge_port:.2f}, surge_s={surge_starboard:.2f}, '
            f'sway={sway:.2f}, heave={heave:.2f}'
        )


def main(args=None):
    rclpy.init(args=args)
    node = CmdVelToThrusters()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()