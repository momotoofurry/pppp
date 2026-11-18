"""Assist demo on the simulated Gen3 in RViz (report 35.57): wrist-direction commands + assist.py drive the arm.

Runs in WSL after src/pc/sim/gen3_sim.sh is up (ROS 2 Humble, mock hardware). Every 100 ms: the command (simulated
user through the board-like decoder, or keys) -> assist.step -> tool velocity -> kin.ik_step -> one-point
JointTrajectory on /joint_trajectory_controller/joint_trajectory; the gripper closes through GripperCommand when the
assist grasps. A CSV log (t, wanted, command, state, goal, P, tool x y z) goes to --log.
Markers: the 'scene' mode keeps publishing the shelves, the objects (grey) and their numbers on /assist_scene; demo /
keys publish the objects coloured by the assist on /assist_objects (orange = the demo's target, green = locked goal,
more opaque = higher P). src/pc/sim/assist.rviz (= kortex_description's view_robot.rviz + these two MarkerArray
displays) shows both: rviz2 -d src/pc/sim/assist.rviz

  python3 src/pc/sim/assist_ros.py demo [--target 0] [--error 0.12] [--seed 1] [--log assist_ros.csv]
  python3 src/pc/sim/assist_ros.py keys            w up, s down, a left, d right, space = rest (relax), q quit
  python3 src/pc/sim/assist_ros.py scene           shelves + objects + numbers, until Ctrl-C
"""
import argparse
import os
import select
import sys
import termios
import time
import tty

import numpy as np
import rclpy
from builtin_interfaces.msg import Duration
from control_msgs.action import GripperCommand
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from visualization_msgs.msg import Marker, MarkerArray

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'assist'))
import assist as A  # noqa: E402
import assist_sim as S  # noqa: E402
import kin  # noqa: E402

JOINTS = [f'joint_{i}' for i in range(1, 8)]
RD = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)      # tool z forward (+x), horizontal approach
OBJECTS = np.array([[0.75, 0.25, 0.10], [0.70, -0.25, 0.30], [0.77, 0.0, 0.10]])
SEEDS = ([0, 15, 180, 230, 0, 55, 90], [0, 30, 0, 110, 0, 40, 90], [0, 40, 180, 250, 0, -60, 90])


class Demo(Node):
    def __init__(self):
        super().__init__('assist_demo')
        self.q = {}
        self.create_subscription(JointState, '/joint_states', lambda m: self.q.update(dict(zip(m.name, m.position))), 10)
        self.traj = self.create_publisher(JointTrajectory, '/joint_trajectory_controller/joint_trajectory', 10)
        self.mk = self.create_publisher(MarkerArray, '/assist_objects', 10)
        self.sc = self.create_publisher(MarkerArray, '/assist_scene', 10)
        self.grip = ActionClient(self, GripperCommand, '/robotiq_gripper_controller/gripper_cmd')

    def joints(self):
        return np.array([self.q[j] for j in JOINTS])

    def send(self, q, dur):
        m = JointTrajectory()
        m.joint_names = JOINTS
        p = JointTrajectoryPoint(positions=[float(v) for v in q], velocities=[0.0] * 7)
        p.time_from_start = Duration(sec=int(dur), nanosec=int((dur % 1) * 1e9))
        m.points = [p]
        self.traj.publish(m)

    def gripper(self, closed):
        if self.grip.wait_for_server(timeout_sec=2.0):
            g = GripperCommand.Goal()
            g.command.position = 0.8 * float(closed)
            g.command.max_effort = 100.0
            self.grip.send_goal_async(g)

    def markers(self, obj, P, goal, tgt):
        arr = MarkerArray()
        for i, o in enumerate(obj):
            m = Marker()
            m.header.frame_id = 'base_link'
            m.ns, m.id, m.type, m.action = 'objects', i, Marker.CYLINDER, Marker.ADD
            m.pose.position.x, m.pose.position.y, m.pose.position.z = map(float, o)
            m.pose.orientation.w = 1.0
            m.scale.x = m.scale.y = 0.066
            m.scale.z = 0.106
            locked = goal == i
            m.color.r, m.color.g, m.color.b = (0.1, 0.7, 0.3) if locked else (0.9, 0.5, 0.1) if i == tgt else (0.6, 0.6, 0.6)
            m.color.a = 0.4 + 0.6 * float(P[i])
            arr.markers.append(m)
        self.mk.publish(arr)


def scene_markers(obj):
    arr = MarkerArray()

    def mk(i, kind, pos, scale, rgba, text=''):
        m = Marker()
        m.header.frame_id = 'base_link'
        m.ns, m.id, m.type, m.action = 'scene', i, kind, Marker.ADD
        m.pose.position.x, m.pose.position.y, m.pose.position.z = map(float, pos)
        m.pose.orientation.w = 1.0
        m.scale.x, m.scale.y, m.scale.z = map(float, scale)
        m.color.r, m.color.g, m.color.b, m.color.a = map(float, rgba)
        m.text = text
        arr.markers.append(m)
    for i, o in enumerate(obj):
        mk(10 + i, Marker.CUBE, (o[0], o[1], o[2] - 0.06), (0.20, 0.16, 0.02), (0.55, 0.42, 0.30, 1.0))   # shelf
        mk(20 + i, Marker.CYLINDER, o, (0.06, 0.06, 0.10), (0.75, 0.75, 0.78, 1.0))                     # object
        mk(30 + i, Marker.TEXT_VIEW_FACING, (o[0], o[1], o[2] + 0.10), (0, 0, 0.05), (1, 1, 1, 1.0), str(i))
    return arr


def keyreader():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    state = {'cmd': 'rest'}
    keys = {'w': 'up', 's': 'down', 'a': 'left', 'd': 'right', ' ': 'rest'}

    def poll():
        while select.select([sys.stdin], [], [], 0)[0]:
            c = sys.stdin.read(1)
            if c == 'q':
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                raise KeyboardInterrupt
            state['cmd'] = keys.get(c, state['cmd'])
        return state['cmd']
    return poll, lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['demo', 'keys', 'scene'])
    ap.add_argument('--target', type=int, default=0)
    ap.add_argument('--error', type=float, default=0.12)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--log', default='assist_ros.csv')
    ap.add_argument('--limit', type=float, default=60.0)
    a = ap.parse_args()
    rclpy.init()
    n = Demo()
    if a.mode == 'scene':
        print('publishing the scene on /assist_scene (Ctrl-C to stop)')
        try:
            while True:
                n.sc.publish(scene_markers(OBJECTS))
                t1 = time.time()
                while time.time() - t1 < 0.5:
                    rclpy.spin_once(n, timeout_sec=0.05)
        except KeyboardInterrupt:
            pass
        rclpy.shutdown()
        return
    t0 = time.time()
    while not all(j in n.q for j in JOINTS) and time.time() - t0 < 10:
        rclpy.spin_once(n, timeout_sec=0.1)
    sols = [kin.solve(np.radians(s), S.X0, RD, iters=1200) for s in SEEDS]
    q = min(sols, key=lambda qq: np.linalg.norm(kin.fk(qq)[:3, 3] - S.X0))
    err0 = np.linalg.norm(kin.fk(q)[:3, 3] - S.X0)
    print(f'start pose solved: tool error {1000 * err0:.1f} mm; moving there (4 s)')
    n.gripper(0.0)
    n.send(q, 4.0)
    t1 = time.time()
    while time.time() - t1 < 4.5:
        rclpy.spin_once(n, timeout_sec=0.05)
    sa = A.Assist(OBJECTS)
    rng = np.random.default_rng(a.seed)
    dec = S.Decoder(S.SET5, a.error, rng)
    poll, restore = keyreader() if a.mode == 'keys' else (None, None)
    hist = [S.X0.copy()] * (S.REACT + 1)
    held, gripped = 'rest', False
    log = open(a.log, 'w', encoding='utf-8')
    log.write('t,wanted,command,state,goal,p0,p1,p2,x,y,z\n')
    try:
        for k in range(int(a.limit / A.DT)):
            tk = time.time()
            x = kin.fk(q)[:3, 3]
            if a.mode == 'demo':
                want, held = S.user_assist(sa, OBJECTS, a.target, hist[-1 - S.REACT], held)
                cmd = dec(want)
            else:
                want = cmd = poll()
            v = sa.step(cmd if cmd != 'rest' else None, x)
            if sa.grip and not gripped:
                n.gripper(1.0)
                gripped = True
            q = kin.ik_step(q, v, RD, A.DT)
            n.send(q, A.DT * 1.5)
            P = sa.probs()
            n.markers(OBJECTS, P, sa.goal, a.target if a.mode == 'demo' else -1)
            hist.append(kin.fk(q)[:3, 3])
            log.write(f'{k * A.DT:.1f},{want},{cmd},{sa.state},{sa.goal},{P[0]:.3f},{P[1]:.3f},{P[2]:.3f},'
                      f'{x[0]:.4f},{x[1]:.4f},{x[2]:.4f}\n')
            if sa.state == 'done':
                print(f'done at {k * A.DT:.1f} s: grasped object {sa.goal} (target {a.target})')
                break
            while time.time() - tk < A.DT:
                rclpy.spin_once(n, timeout_sec=0.01)
        else:
            print('time limit reached, state', sa.state)
    except KeyboardInterrupt:
        pass
    finally:
        if restore:
            restore()
        log.close()
    t2 = time.time()
    while time.time() - t2 < 1.0:
        rclpy.spin_once(n, timeout_sec=0.05)
    qs = n.joints()
    print('commanded vs simulator joints, max diff deg:', round(float(np.degrees(np.abs(qs - q)).max()), 2))
    print('tool now (fk of simulator joints):', np.round(kin.fk(qs)[:3, 3], 3).tolist())
    rclpy.shutdown()


if __name__ == '__main__':
    main()
