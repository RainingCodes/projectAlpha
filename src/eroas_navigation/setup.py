from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'eroas_navigation'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.rviz')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='foc',
    maintainer_email='gomsoonhyung@gmail.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'eroas_node = eroas_navigation.eroas_node:main',
            'cmd_vel_to_thrusters = eroas_navigation.cmd_vel_to_thrusters:main',
            'waypoint_navigator = eroas_navigation.waypoint_navigator:main',
            'fls_viewer = eroas_navigation.fls_viewer:main',
            'fls_recorder = eroas_navigation.fls_recorder:main',
            'path_publisher = eroas_navigation.path_publisher:main'
        ],
    },
)
