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
  python3 src/pc/sim/assist_ros.py keys [--assist blend|takeover] [--level 0.6]
                                                   w up, s down, a left, d right, space = rest (relax), q quit
  blend (default, 35.58): you steer all the time; the arm adds depth toward the likely object; once aligned and sure,
  keep the SAME key to go in, the opposite key backs out, another key steers again; at the object press space and
  wait 1 s to grasp; then move freely (w lifts). takeover (35.57): after a short push the system drives.
  python3 src/pc/sim/assist_ros.py scene           shelves + objects + numbers, until Ctrl-C
  python3 src/pc/sim/assist_ros.py home            back to the start pose, gripper open
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
from geometry_msgs.msg import Point
from visualization_msgs.msg import Marker, MarkerArray

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'assist'))
import assist as A  # noqa: E402
import assist_sim as S  # noqa: E402
import kin  # noqa: E402

JOINTS = [f'joint_{i}' for i in range(1, 8)]
RD = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)      # tool z forward (+x), horizontal approach
OBJECTS = np.array([[0.75, 0.25, 0.10], [0.70, -0.25, 0.30], [0.77, 0.0, 0.10]])
# shelf tops (centre): one under each object + two empty ones to put things down (35.59)
SHELVES = np.vstack([OBJECTS - [0, 0, 0.05], [[0.72, -0.25, 0.05], [0.72, 0.25, 0.25]]])
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

    def markers(self, obj, P, sa, tgt, x):
        """objects coloured by the assist phase + an arrow and a key hint (the hint text is also returned)"""
        arr = MarkerArray()
        code, txt, goal = hint(sa, obj, P, x)
        for i, o in enumerate(obj):
            lb = Marker()
            lb.header.frame_id = 'base_link'
            lb.ns, lb.id, lb.type, lb.action = 'labels', i, Marker.TEXT_VIEW_FACING, Marker.ADD
            lb.pose.position.x, lb.pose.position.y, lb.pose.position.z = map(float, o + [0, 0, 0.09])
            lb.pose.orientation.w = 1.0
            lb.scale.z = 0.05
            lb.color.r = lb.color.g = lb.color.b = lb.color.a = 1.0
            lb.text = str(i)
            arr.markers.append(lb)
            m = Marker()
            m.header.frame_id = 'base_link'
            m.ns, m.id, m.type, m.action = 'objects', i, Marker.CYLINDER, Marker.ADD
            m.pose.position.x, m.pose.position.y, m.pose.position.z = map(float, o)
            m.pose.orientation.w = 1.0
            m.scale.x = m.scale.y = 0.066
            m.scale.z = 0.106
            if goal == i and code in ('go', 'grasp', 'lift', 'carry', 'place'):
                rgba = (0.1, 0.9, 0.2, 1.0)                       # chosen: bright green
            elif goal == i and code == 'lead':
                rgba = (1.0, 0.85, 0.1, 0.5 + 0.5 * float(P[i]))   # the system's current guess: yellow
            elif i == tgt:
                rgba = (0.9, 0.5, 0.1, 0.6)                       # the demo's target: orange
            else:
                rgba = (0.6, 0.6, 0.6, 0.4 + 0.4 * float(P[i]))
            m.color.r, m.color.g, m.color.b, m.color.a = map(float, rgba)
            arr.markers.append(m)
        # arrow from the tool to where the assist is heading, and the key hint above the goal
        a_ = Marker()
        a_.header.frame_id = 'base_link'
        a_.ns, a_.id, a_.type = 'hint', 0, Marker.ARROW
        t_ = Marker()
        t_.header.frame_id = 'base_link'
        t_.ns, t_.id, t_.type = 'hint', 1, Marker.TEXT_VIEW_FACING
        if goal is None or code == 'none':
            a_.action = t_.action = Marker.DELETE
        else:
            a_.action = t_.action = Marker.ADD
            end = obj[goal] if code in ('go', 'grasp') else (obj[goal] + A.PRE if code == 'lead' else x)
            a_.points = [Point(x=float(x[0]), y=float(x[1]), z=float(x[2])),
                         Point(x=float(end[0]), y=float(end[1]), z=float(end[2]))]
            a_.scale.x, a_.scale.y, a_.scale.z = 0.008, 0.02, 0.03
            col = (0.1, 0.9, 0.2) if code in ('go', 'grasp', 'lift') else (1.0, 0.85, 0.1)
            a_.color.r, a_.color.g, a_.color.b, a_.color.a = map(float, col + (0.9,))
            if code in ('lift', 'carry', 'place'):
                a_.action = Marker.DELETE
            t_.pose.position.x, t_.pose.position.y, t_.pose.position.z = map(float, obj[goal] + [0, 0, 0.16])
            t_.pose.orientation.w = 1.0
            t_.scale.z = 0.035
            t_.color.r = t_.color.g = t_.color.b = t_.color.a = 1.0
            t_.text = txt
        arr.markers += [a_, t_]
        self.mk.publish(arr)
        return code, goal


KEY = {'up': 'W', 'down': 'S', 'left': 'A', 'right': 'D'}
HINT_ZH = {'carry': '夾著物體 {g}：自由移動；移到任一個架子上方，放鬆 1 秒就放下',
           'place': '物體 {g} 在架子上方：按空白鍵放鬆 1 秒放下',
           'lead': '系統猜是物體 {g}：繼續對準（黃色箭頭是它想去的地方）',
           'go': '已對準物體 {g}：按住 {k} 伸進去，{o} 退出來，其他鍵重新調整',
           'grasp': '到了物體 {g}：按空白鍵放鬆 1 秒就夾',
           'lift': '夾到物體 {g}：按 W 抬起來'}


def hint(sa, obj, P, x):
    """-> (code, English text for RViz, goal index) for the current assist phase"""
    if sa.state == 'grasped':
        if sa.keep:
            if sa.armed and sa.place_ok(x) is not None:
                return 'place', 'SPACE 1 s = put down', sa.goal
            return 'carry', 'over a shelf: SPACE 1 s = put down', sa.goal
        return 'lift', 'W = lift', sa.goal
    if sa.state in ('final', 'approach'):
        g = sa.goal
        if np.linalg.norm(obj[g] - x) < 1.5 * A.GRASP_TOL:
            return 'grasp', 'SPACE 1 s = grasp', g
        k = KEY.get(sa.lock_cmd, '?')
        o = KEY.get(A.OPPOSITE.get(sa.lock_cmd, ''), '?')
        return 'go', f'hold {k} = go in   {o} = back', g
    g = int(np.argmax(P))
    if P[g] >= A.P_ON and sa.state == 'steer':
        return 'lead', f'object {g}? keep aligning', g
    return 'none', '', None


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
    for i, sh in enumerate(SHELVES):
        mk(10 + i, Marker.CUBE, (sh[0], sh[1], sh[2] - 0.01), (0.20, 0.16, 0.02), (0.55, 0.42, 0.30, 1.0))
    for i in range(20, 33):
        m = Marker()
        m.header.frame_id = 'base_link'
        m.ns, m.id, m.action = 'scene', i, Marker.DELETE      # objects / numbers of older versions: drawn live now
        arr.markers.append(m)
    return arr


def keyreader():
    """raw key bytes from the terminal (os.read on the file descriptor: no Python text buffering). A key sets the
    command and it stays until another key: w a s d = direction (held), space = relax (stop), q = quit"""
    fd = sys.stdin.fileno()
    if not os.isatty(fd):
        raise SystemExit('keys mode needs an interactive terminal (stdin is not a TTY)')
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    state = {'cmd': 'rest'}
    keys = {b'w': 'up', b's': 'down', b'a': 'left', b'd': 'right', b' ': 'rest',
            b'W': 'up', b'S': 'down', b'A': 'left', b'D': 'right'}

    def poll():
        while select.select([fd], [], [], 0)[0]:
            data = os.read(fd, 64)
            if not data:
                break
            for i in range(len(data)):
                c = data[i:i + 1]
                if c in (b'q', b'Q'):
                    raise KeyboardInterrupt
                if c in keys and keys[c] != state['cmd']:
                    state['cmd'] = keys[c]
                    print(f'\r  command: {state["cmd"]:6s}', flush=True)
        return state['cmd']
    return poll, lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['demo', 'keys', 'scene', 'home'])
    ap.add_argument('--target', type=int, default=0)
    ap.add_argument('--error', type=float, default=0.12)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--assist', choices=['blend', 'takeover'], default='blend')
    ap.add_argument('--level', type=float, default=0.6)
    ap.add_argument('--log', default='assist_ros.csv')
    ap.add_argument('--limit', type=float, default=None, help='s (default: demo 60, keys 300)')
    a = ap.parse_args()
    rclpy.init()
    n = Demo()
    if a.mode == 'scene':
        print('publishing the scene on /assist_scene (Ctrl-C to stop)')
        idle = A.Assist(OBJECTS)
        t1 = time.time()
        while time.time() - t1 < 1.0:
            rclpy.spin_once(n, timeout_sec=0.05)
        n.markers(OBJECTS, idle.probs() * 0, idle, -1, S.X0)   # objects + numbers at the start positions, once
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
    if a.mode == 'home':
        print('at the start pose, tool', np.round(kin.fk(n.joints())[:3, 3], 3).tolist(), ', gripper open')
        rclpy.shutdown()
        return
    sa = A.Assist(OBJECTS, mode=a.assist, level=a.level, keep=(a.mode == 'keys'), shelves=SHELVES)
    rng = np.random.default_rng(a.seed)
    dec = S.Decoder(S.SET5, a.error, rng)
    poll, restore = keyreader() if a.mode == 'keys' else (None, None)
    if a.limit is None:
        a.limit = 300.0 if a.mode == 'keys' else 60.0
    if a.mode == 'keys':
        print('ready. Click this terminal first (not the RViz window), then: w up, s down, a left, d right,')
        print('space = relax (stop), q = quit. A key keeps moving until another key. Seen from behind the arm: '
              'object 0 left-low, 1 right-high, 2 middle-low.', flush=True)
        if a.assist == 'blend':
            print(f'blend mode, level {a.level}: you steer; RViz shows the guess in yellow, then green with a hint '
                  'when aligned: keep the same key to go in, the opposite key backs out; at the object press space '
                  'and wait 1 s to grasp; then w lifts.', flush=True)
    last_state = None
    last_hint = None
    hist = [S.X0.copy()] * (S.REACT + 1)
    held, gripped = 'rest', False
    log = open(a.log, 'w', encoding='utf-8')
    log.write('t,wanted,command,state,goal,p0,p1,p2,x,y,z\n')
    try:
        for k in range(int(a.limit / A.DT)):
            tk = time.time()
            x = kin.fk(q)[:3, 3]
            if a.mode == 'demo':
                user = S.user_blend if a.assist == 'blend' else S.user_assist
                want, held = user(sa, OBJECTS, a.target, hist[-1 - S.REACT], held)
                cmd = dec(want)
            else:
                want = cmd = poll()
            v = sa.step(cmd if cmd != 'rest' else None, x)
            if bool(sa.grip) != gripped:
                n.gripper(float(sa.grip))
                gripped = bool(sa.grip)
            q = kin.ik_step(q, v, RD, A.DT)
            n.send(q, A.DT * 1.5)
            P = sa.probs()
            code, hg = n.markers(sa.obj, P, sa, a.target if a.mode == 'demo' else -1, kin.fk(q)[:3, 3])
            hist.append(kin.fk(q)[:3, 3])
            log.write(f'{k * A.DT:.1f},{want},{cmd},{sa.state},{sa.goal},{P[0]:.3f},{P[1]:.3f},{P[2]:.3f},'
                      f'{x[0]:.4f},{x[1]:.4f},{x[2]:.4f}\n')
            log.flush()
            if a.mode == 'keys' and (code, hg) != last_hint:
                last_hint = (code, hg)
                if code in HINT_ZH:
                    k = KEY.get(sa.lock_cmd, '?')
                    o = KEY.get(A.OPPOSITE.get(sa.lock_cmd, ''), '?')
                    print('  >> ' + HINT_ZH[code].format(g=hg, k=k, o=o), flush=True)
            if a.mode == 'keys' and (sa.state, sa.goal) != last_state:
                last_state = (sa.state, sa.goal)
                print(f'\r  assist: {sa.state}' + (f', goal object {sa.goal}' if sa.goal is not None else ''), flush=True)
            if sa.state == 'done':
                print(f'done at {k * A.DT:.1f} s: grasped object {sa.goal}' + (f' (target {a.target})' if a.mode == 'demo' else ''))
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
