"""writes src/pc/sim/assist_world.world: the assist demo's scene (assist_ros.py OBJECTS / SHELVES) as Gazebo Classic
models. Shelves: static boards 20 x 16 x 2 cm (tops at the SHELVES heights). Objects: cylinders r 3 cm, h 10 cm,
0.1 kg, high friction and soft contacts so the 2F-85 can hold them. The robot is spawned at the world origin."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'assist'))
import scenes as SC  # noqa: E402  (35.101: python3 make_world.py <out> [3obj | crowded | layout.json])

_o, _s = SC.load(sys.argv[2] if len(sys.argv) > 2 else '3obj')
OBJ = [tuple(map(float, p)) for p in _o]
SHELVES = [tuple(map(float, p)) for p in _s]


def shelf(i, x, y, top):
    return f'''
    <model name="shelf_{i}"><static>true</static>
      <pose>{x} {y} {top - 0.01} 0 0 0</pose>
      <link name="board">
        <collision name="c"><geometry><box><size>0.20 0.16 0.02</size></box></geometry>
          <surface><friction><ode><mu>1.0</mu><mu2>1.0</mu2></ode></friction></surface></collision>
        <visual name="v"><geometry><box><size>0.20 0.16 0.02</size></box></geometry>
          <material><ambient>0.55 0.42 0.30 1</ambient><diffuse>0.55 0.42 0.30 1</diffuse></material></visual>
      </link>
    </model>'''


def obj(i, x, y, z):
    m, r, h = 0.1, 0.03, 0.10
    ixx = m * (3 * r * r + h * h) / 12
    izz = m * r * r / 2
    return f'''
    <model name="object_{i}">
      <pose>{x} {y} {z + 0.001} 0 0 0</pose>
      <link name="body">
        <inertial><mass>{m}</mass><inertia><ixx>{ixx:.6g}</ixx><iyy>{ixx:.6g}</iyy><izz>{izz:.6g}</izz>
          <ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>
        <collision name="c"><geometry><cylinder><radius>{r}</radius><length>{h}</length></cylinder></geometry>
          <surface><friction><ode><mu>2.0</mu><mu2>2.0</mu2></ode></friction>
            <contact><ode><kp>1e5</kp><kd>10</kd><min_depth>0.001</min_depth><max_vel>0.1</max_vel></ode></contact>
          </surface></collision>
        <visual name="v"><geometry><cylinder><radius>{r}</radius><length>{h}</length></cylinder></geometry>
          <material><ambient>0.75 0.75 0.78 1</ambient><diffuse>0.75 0.75 0.78 1</diffuse></material></visual>
      </link>
    </model>'''


models = ''.join(shelf(i, *s) for i, s in enumerate(SHELVES)) + ''.join(obj(i, *o) for i, o in enumerate(OBJ))
world = f'''<?xml version="1.0"?>
<sdf version="1.6">
  <world name="assist">
    <physics type="ode"><max_step_size>0.001</max_step_size><real_time_update_rate>1000</real_time_update_rate></physics>
    <include><uri>model://ground_plane</uri></include>
    <include><uri>model://sun</uri></include>
    <plugin name="gazebo_ros_state" filename="libgazebo_ros_state.so">
      <ros><namespace>/gazebo</namespace></ros><update_rate>10.0</update_rate>
    </plugin>{models}
  </world>
</sdf>
'''
open(sys.argv[1], 'w', encoding='utf-8').write(world)
print('written', sys.argv[1])
