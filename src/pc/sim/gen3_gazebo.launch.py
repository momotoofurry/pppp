"""Gen3 7-DoF + Robotiq 2F-85 in Gazebo Classic (gazebo11 + gazebo_ros2_control), with the assist demo's shelves and
objects as physical models (report 35.64). Built from kortex_bringup/kortex_sim_control.launch.py, without the two
ros_gz_bridge nodes that file always starts (they belong to Ignition and are not installed here).

The kortex description with sim_gazebo:=true still gives the gripper the real robotiq_driver hardware plugin (Gazebo
Classic then rejects the gripper controller). The generated description is patched: the gripper's ros2_control block
uses gazebo_ros2_control/GazeboSystem, and its mimic joints are declared there (mimic / multiplier params) so that
Gazebo drives the linkage from robotiq_85_left_knuckle_joint.

  ros2 launch src/pc/sim/gen3_gazebo.launch.py [gui:=true]       (run through src/pc/sim/gen3_gazebo.sh)
"""
import os
import re
import subprocess

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction, RegisterEventHandler
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

HERE = os.path.dirname(os.path.abspath(__file__))
MIMIC = [('robotiq_85_right_knuckle_joint', -1), ('robotiq_85_left_inner_knuckle_joint', 1),
         ('robotiq_85_right_inner_knuckle_joint', -1), ('robotiq_85_left_finger_tip_joint', -1),
         ('robotiq_85_right_finger_tip_joint', 1)]


def description():
    share = FindPackageShare('kortex_description').find('kortex_description')
    controllers = os.path.join(share, 'arms/gen3/7dof/config/ros2_controllers.yaml')
    urdf = subprocess.run(['xacro', os.path.join(share, 'robots', 'kinova.urdf.xacro'), 'robot_ip:=xxx.yyy.zzz.www',
                           'name:=gen3', 'arm:=gen3', 'dof:=7', 'vision:=false', 'prefix:=', 'sim_gazebo:=true',
                           'sim_ignition:=false', 'gripper:=robotiq_2f_85', f'simulation_controllers:={controllers}'],
                          check=True, capture_output=True, text=True).stdout
    mimic = ''.join(f'''
    <joint name="{j}"><param name="mimic">robotiq_85_left_knuckle_joint</param><param name="multiplier">{m}</param>
      <command_interface name="position"/><state_interface name="position"/><state_interface name="velocity"/></joint>'''
                    for j, m in MIMIC)
    block = f'''<ros2_control name="RobotiqGripperGazebo" type="system">
    <hardware><plugin>gazebo_ros2_control/GazeboSystem</plugin></hardware>
    <joint name="robotiq_85_left_knuckle_joint">
      <command_interface name="position"/>
      <state_interface name="position"><param name="initial_value">0.0</param></state_interface>
      <state_interface name="velocity"/>
    </joint>{mimic}
  </ros2_control>'''
    new, n = re.subn(r'<ros2_control name="RobotiqGripperHardwareInterface".*?</ros2_control>', block, urdf, flags=re.S)
    assert n == 1, 'gripper ros2_control block not found'
    return new


def setup(context, *args, **kwargs):
    desc = description()
    rsp = Node(package='robot_state_publisher', executable='robot_state_publisher', output='both',
               parameters=[{'robot_description': desc, 'use_sim_time': True}])
    return [rsp]


def generate_launch_description():
    gui = LaunchConfiguration('gui')
    world = os.path.join(HERE, 'assist_world.world')
    gzserver = ExecuteProcess(cmd=['gzserver', '-s', 'libgazebo_ros_init.so', '-s', 'libgazebo_ros_factory.so', world],
                              output='screen')
    gzclient = ExecuteProcess(cmd=['gzclient'], output='screen', condition=IfCondition(gui))
    spawn = Node(package='gazebo_ros', executable='spawn_entity.py', output='screen',
                 arguments=['-entity', 'gen3', '-topic', 'robot_description'])
    jsb = Node(package='controller_manager', executable='spawner',
               arguments=['joint_state_broadcaster', '--controller-manager', '/controller_manager'])
    traj = Node(package='controller_manager', executable='spawner',
                arguments=['joint_trajectory_controller', '-c', '/controller_manager'])
    hand = Node(package='controller_manager', executable='spawner',
                arguments=['robotiq_gripper_controller', '-c', '/controller_manager'])
    attach = ExecuteProcess(cmd=['python3', os.path.join(HERE, 'gz_attach.py')], output='screen',
                            condition=IfCondition(LaunchConfiguration('attach')))
    return LaunchDescription([
        DeclareLaunchArgument('gui', default_value='true'),
        DeclareLaunchArgument('attach', default_value='true'),     # simulated grasp (gz_attach.py)
        OpaqueFunction(function=setup), gzserver, gzclient, spawn,
        RegisterEventHandler(OnProcessExit(target_action=spawn, on_exit=[jsb])),
        RegisterEventHandler(OnProcessExit(target_action=jsb, on_exit=[traj, hand, attach])),
    ])
