from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    pkg_stonefish_ros2 = get_package_share_directory('stonefish_ros2')
    pkg_eroas_navigation = get_package_share_directory('eroas_navigation')

    simulation_data = os.path.join(pkg_stonefish_ros2, 'data')
    scenario_desc = os.path.join(pkg_stonefish_ros2, 'scenarios', 'eroas_canyon_test.scn')

    # Launch arguments
    simulation_data_arg = DeclareLaunchArgument('simulation_data', default_value=simulation_data)
    scenario_desc_arg = DeclareLaunchArgument('scenario_desc', default_value=scenario_desc)
    simulation_rate_arg = DeclareLaunchArgument('simulation_rate', default_value='100.0')
    window_res_x_arg = DeclareLaunchArgument('window_res_x', default_value='1280')
    window_res_y_arg = DeclareLaunchArgument('window_res_y', default_value='1000')
    rendering_quality_arg = DeclareLaunchArgument('rendering_quality', default_value='high')

    # Goal position arguments (end of canyon)
    goal_x_arg = DeclareLaunchArgument('goal_x', default_value='25.0')
    goal_y_arg = DeclareLaunchArgument('goal_y', default_value='0.0')
    goal_z_arg = DeclareLaunchArgument('goal_z', default_value='3.0')

    # Manual start mode for screen recording
    auto_start_arg = DeclareLaunchArgument(
        'auto_start',
        default_value='false',
        description='Start navigation immediately (false = manual start via service)'
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

    # FLS to PointCloud converter
    fls_to_pointcloud_node = Node(
        package='eroas_navigation',
        executable='fls_to_pointcloud',
        name='fls_to_pointcloud',
        parameters=[
            {'namespace': 'GIRONA500'},
            {'num_beams': 512},
            {'num_bins': 128},
            {'horizontal_fov': 90.0},
            {'vertical_fov': 20.0},
            {'range_min': 1.0},
            {'range_max': 20.0},
            {'intensity_threshold': 15.0}
        ],
        output='screen',
    )

    # EROAS navigation node
    eroas_node = Node(
        package='eroas_navigation',
        executable='eroas_node',
        name='eroas_node',
        parameters=[
            {'namespace': 'GIRONA500'},
            {'control_frequency': 15.0},  # Match FLS rate
            {'goal_x': LaunchConfiguration('goal_x')},
            {'goal_y': LaunchConfiguration('goal_y')},
            {'goal_z': LaunchConfiguration('goal_z')},
            {'goal_tolerance': 2.0},
            {'auto_start': LaunchConfiguration('auto_start')}
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

    # FLS Viewer
    fls_viewer_node = Node(
        package='eroas_navigation',
        executable='fls_viewer',
        name='fls_viewer',
        parameters=[
            {'namespace': 'GIRONA500'},
            {'window_name': 'FLS - EROAS Canyon Test'},
            {'horizontal_fov': 90.0},
            {'range_min': 1.0},
            {'range_max': 20.0},
            {'display_size': 400},
            {'window_x': -1},
            {'window_y': -1}
        ],
        output='screen',
    )

    # Sensor monitor
    sensor_monitor_node = Node(
        package='stonefish_ros2',
        executable='sensor_monitor.py',
        name='sensor_monitor',
        output='screen',
        prefix='xterm -e',
    )

    # RViz
    rviz_config_file = os.path.join(pkg_eroas_navigation, 'config', 'eroas_navigation.rviz')
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
        goal_x_arg,
        goal_y_arg,
        goal_z_arg,
        auto_start_arg,
        static_tf_world_ned,
        static_tf_vehicle_baselink,
        robot_state_publisher_node,
        odom_to_tf_node,
        stonefish_simulator_node,
        fls_to_pointcloud_node,
        eroas_node,
        cmd_vel_to_thrusters_node,
        sensor_monitor_node,
        fls_viewer_node,
        rviz_node,
    ])
