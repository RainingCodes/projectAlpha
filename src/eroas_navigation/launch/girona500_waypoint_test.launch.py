from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    # Get package directories
    pkg_stonefish_ros2 = get_package_share_directory('stonefish_ros2')
    pkg_eroas_navigation = get_package_share_directory('eroas_navigation')

    # Simulation parameters
    simulation_data = os.path.join(pkg_stonefish_ros2, 'data')
    scenario_desc = os.path.join(pkg_stonefish_ros2, 'scenarios', 'waypoint_test.scn')

    # Launch arguments
    simulation_data_arg = DeclareLaunchArgument(
        'simulation_data',
        default_value=simulation_data
    )

    scenario_desc_arg = DeclareLaunchArgument(
        'scenario_desc',
        default_value=scenario_desc
    )

    simulation_rate_arg = DeclareLaunchArgument(
        'simulation_rate',
        default_value='100.0'
    )

    window_res_x_arg = DeclareLaunchArgument(
        'window_res_x',
        default_value='1280'
    )

    window_res_y_arg = DeclareLaunchArgument(
        'window_res_y',
        default_value='1000'
    )

    rendering_quality_arg = DeclareLaunchArgument(
        'rendering_quality',
        default_value='high'
    )

    # Waypoint arguments (square pattern)
    waypoint_x_arg = DeclareLaunchArgument(
        'waypoint_x',
        default_value='[0.0, 10.0, 10.0, 0.0]',
        description='X coordinates of waypoints (North in NED)'
    )

    waypoint_y_arg = DeclareLaunchArgument(
        'waypoint_y',
        default_value='[0.0, 0.0, 10.0, 10.0]',
        description='Y coordinates of waypoints (East in NED)'
    )

    waypoint_z_arg = DeclareLaunchArgument(
        'waypoint_z',
        default_value='[3.0, 3.0, 3.0, 3.0]',
        description='Z coordinates of waypoints (Down in NED, positive = deeper)'
    )

    waypoint_tolerance_arg = DeclareLaunchArgument(
        'waypoint_tolerance',
        default_value='1.5',
        description='Distance tolerance for waypoint arrival (meters)'
    )

    auto_start_arg = DeclareLaunchArgument(
        'auto_start',
        default_value='true',
        description='Start navigation immediately (false = wait for service call)'
    )

    # Stonefish simulator node
    stonefish_simulator_node = Node(
        package='stonefish_ros2',
        executable='stonefish_simulator',
        namespace='stonefish_ros2',
        name='stonefish_simulator',
        arguments=[
            LaunchConfiguration('simulation_data'),
            LaunchConfiguration('scenario_desc'),
            LaunchConfiguration('simulation_rate'),
            LaunchConfiguration('window_res_x'),
            LaunchConfiguration('window_res_y'),
            LaunchConfiguration('rendering_quality')
        ],
        output='screen',
    )

    # Velocity to thruster converter
    cmd_vel_to_thrusters_node = Node(
        package='eroas_navigation',
        executable='cmd_vel_to_thrusters',
        name='cmd_vel_to_thrusters',
        parameters=[
            {'namespace': 'GIRONA500'},
            {'surge_scale': 1.0},
            {'sway_scale': 1.0},
            {'heave_scale': 3.0},
            {'yaw_scale': 0.5}
        ],
        output='screen',
    )

    # Waypoint Navigator Node
    waypoint_navigator_node = Node(
        package='eroas_navigation',
        executable='waypoint_navigator',
        name='waypoint_navigator',
        parameters=[
            {'namespace': 'GIRONA500'},
            {'control_frequency': 10.0},
            {'waypoint_x': LaunchConfiguration('waypoint_x')},
            {'waypoint_y': LaunchConfiguration('waypoint_y')},
            {'waypoint_z': LaunchConfiguration('waypoint_z')},
            {'waypoint_tolerance': LaunchConfiguration('waypoint_tolerance')},
            {'auto_start': LaunchConfiguration('auto_start')}
        ],
        output='screen',
    )

    # Odometry to TF bridge
    odom_to_tf_node = Node(
        package='stonefish_ros2',
        executable='odom_to_tf.py',
        name='odom_to_tf',
        output='screen',
    )

    # Robot state publisher
    urdf_file = os.path.join(pkg_stonefish_ros2, 'urdf', 'girona500.urdf')
    with open(urdf_file, 'r') as f:
        robot_desc = f.read()

    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        namespace='GIRONA500',
        name='robot_state_publisher',
        output='screen',
        parameters=[{
            'robot_description': robot_desc,
            'frame_prefix': 'GIRONA500/'
        }]
    )

    # Static TF publishers
    static_tf_world_ned = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='static_tf_world_ned',
        arguments=['0', '0', '0', '0', '0', '0', 'world_ned', 'GIRONA500/world_ned']
    )

    static_tf_vehicle_baselink = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='static_tf_vehicle_baselink',
        arguments=['0', '0', '0', '0', '0', '0', 'GIRONA500/Vehicle', 'GIRONA500/base_link']
    )

    # Sensor monitor node
    sensor_monitor_node = Node(
        package='stonefish_ros2',
        executable='sensor_monitor.py',
        name='sensor_monitor',
        output='screen',
        prefix='xterm -e',
    )

    # Path publisher for rviz trajectory display
    path_publisher_node = Node(
        package='eroas_navigation',
        executable='path_publisher',
        name='path_publisher',
        parameters=[
            {'namespace': 'GIRONA500'}
        ],
        output='screen',
    )

    # RViz visualization node with waypoint-specific config
    rviz_config_file = os.path.join(pkg_eroas_navigation, 'config', 'waypoint_navigation.rviz')
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        arguments=['-d', rviz_config_file],
        output='screen',
    )

    return LaunchDescription([
        simulation_data_arg,
        scenario_desc_arg,
        simulation_rate_arg,
        window_res_x_arg,
        window_res_y_arg,
        rendering_quality_arg,
        waypoint_x_arg,
        waypoint_y_arg,
        waypoint_z_arg,
        waypoint_tolerance_arg,
        auto_start_arg,
        static_tf_world_ned,
        static_tf_vehicle_baselink,
        robot_state_publisher_node,
        odom_to_tf_node,
        stonefish_simulator_node,
        cmd_vel_to_thrusters_node,
        waypoint_navigator_node,
        sensor_monitor_node,
        path_publisher_node,
        rviz_node,
    ])