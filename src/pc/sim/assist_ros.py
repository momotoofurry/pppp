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
  python3 src/pc/sim/assist_ros.py keys [--modes 1] [--assist blend|takeover] [--level 0.6]
      --modes 1 (default, 35.63): mode 1 = free (W/S/A/D up/down/left/right in the plane in front of the shelves),
      mode 2 = W in / S out; switches by itself (stop in front of an object / a shelf -> 2, back at the plane -> 1),
      E switches by hand, H (mode 1 only) back to the start. --modes 0: the 35.62 behaviour.
      35.67: --rule mix (default) / lead; the mode shows as a coloured badge and gripper ball in RViz (blue = mode 1,
      orange = mode 2, grey = assist off) and every mode change rings the terminal bell.
                                                   w up, s down, a left, d right, space = rest (relax), q quit
  blend (default, 35.58): you steer all the time; the arm adds depth toward the likely object; once aligned and sure,
  keep the SAME key to go in, the opposite key backs out, another key steers again; at the object press space and
  wait 1 s to grasp; then move freely (w lifts). takeover (35.57): after a short push the system drives.
  python3 src/pc/sim/assist_ros.py scene           shelves + objects + numbers, until Ctrl-C
  python3 src/pc/sim/assist_ros.py home            the arm folded back to Kinova's home pose (poses_sim.json 'home'),
                                                   gripper open
  python3 src/pc/sim/assist_ros.py start           to the task start pose in front of the shelves, gripper open
                                                   (keys / demo go there by themselves first)
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
import modes as M  # noqa: E402

JOINTS = [f'joint_{i}' for i in range(1, 8)]
RD = np.array([[0, 0, 1], [-1, 0, 0], [0, -1, 0]], float)      # tool z forward (+x); tool x (the 2F-85 finger axis) horizontal, so the fingers close sideways on an upright object (35.64)
OBJECTS = np.array([[0.75, 0.25, 0.10], [0.70, -0.25, 0.30], [0.77, 0.0, 0.10]])
# shelf tops (centre): one under each object + two empty ones to put things down (35.59)
SHELVES = np.vstack([OBJECTS - [0, 0, 0.05], [[0.72, -0.25, 0.05], [0.72, 0.25, 0.25]]])
SEEDS = ([0, 15, 180, 230, 0, 55, 90], [0, 30, 0, 110, 0, 40, 90], [0, 40, 180, 250, 0, -60, 90],
         [30, 70, 280, 120, 0, -100, 70], [30, 70, 280, 120, 0, -100, 160], [0, 40, 180, 250, 0, -60, 180])
# start point of the demo (35.61): at (0.50, 0, 0.30) the horizontal tool needs the elbow 0.5 deg from its limit; here the
# best posture keeps every limited joint >= 17 deg from its limit
X0 = np.array([0.58, 0.0, 0.35])


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
            if goal == i and code in ('go', 'grasp', 'lift', 'carry', 'place', 'pick', 'place_in', 'out', 'lower'):
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
            end = obj[goal] if code in ('go', 'grasp', 'pick') else (obj[goal] + A.PRE if code == 'lead' else x)
            a_.points = [Point(x=float(x[0]), y=float(x[1]), z=float(x[2])),
                         Point(x=float(end[0]), y=float(end[1]), z=float(end[2]))]
            a_.scale.x, a_.scale.y, a_.scale.z = 0.008, 0.02, 0.03
            col = (0.1, 0.9, 0.2) if code in ('go', 'grasp', 'lift', 'pick') else (1.0, 0.85, 0.1)
            a_.color.r, a_.color.g, a_.color.b, a_.color.a = map(float, col + (0.9,))
            if code not in ('go', 'grasp', 'pick', 'lead'):
                a_.action = Marker.DELETE
            t_.pose.position.x, t_.pose.position.y, t_.pose.position.z = map(float, obj[goal] + [0, 0, 0.16])
            t_.pose.orientation.w = 1.0
            t_.scale.z = 0.06
            t_.color.r = t_.color.g = t_.color.b = t_.color.a = 1.0
            t_.text = txt
        arr.markers += [a_, t_]
        if isinstance(sa, M.ModeAssist):
            arr.markers += mode_markers(sa, code, x)
        self.mk.publish(arr)
        return code, goal


# mode colours (35.67): the user must always see which mode is active (JACO users forget it: Herlant et al. 2016)
MODE_RGB = {1: (0.15, 0.55, 1.0), 2: (1.0, 0.55, 0.1), 'off': (0.6, 0.6, 0.6)}
MODE_NAME = {1: 'MODE 1  up / down / left / right', 2: 'MODE 2  W in / S out'}


def mode_markers(sa, code, x):
    """a badge above the scene and a ball on the gripper, coloured by the mode (grey while the assist is off)"""
    col = MODE_RGB['off'] if code == 'off' else MODE_RGB[sa.m]
    b = Marker()
    b.header.frame_id = 'base_link'
    b.ns, b.id, b.type, b.action = 'mode', 0, Marker.TEXT_VIEW_FACING, Marker.ADD
    b.pose.position.x, b.pose.position.y, b.pose.position.z = 0.55, 0.0, 0.62
    b.pose.orientation.w = 1.0
    b.scale.z = 0.07
    b.color.r, b.color.g, b.color.b, b.color.a = map(float, col + (1.0,))
    b.text = MODE_NAME[sa.m] + ('  (assist off)' if code == 'off' else '')
    g = Marker()
    g.header.frame_id = 'base_link'
    g.ns, g.id, g.type, g.action = 'mode', 1, Marker.SPHERE, Marker.ADD
    g.pose.position.x, g.pose.position.y, g.pose.position.z = map(float, x)
    g.pose.orientation.w = 1.0
    g.scale.x = g.scale.y = g.scale.z = 0.035
    g.color.r, g.color.g, g.color.b, g.color.a = map(float, col + (0.8,))
    return [b, g]


KEY = {'up': 'W', 'down': 'S', 'left': 'A', 'right': 'D'}
HINT_ZH = {'free': '自由控制：移到某個物體前方附近，系統才會開始幫忙',
           'carry': '夾著物體 {g}：自由移動；移到空架子前方停下就會鎖定放置位置',
           'inside_carry': '夾著物體 {g}，還在架子裡：先按 S 退出（W 可稍微抬高）',
           'inside': '在架子裡：先按 S 退出',
           'place_lock': '已鎖定放置位置：按 W 放進去，S 退出並取消',
           'place': '到了：按空白鍵放鬆 1 秒放下物體 {g}，之後按 S 退出',
           'lead': '系統猜是物體 {g}：移到它前面停下（空白鍵）就會鎖定',
           'go': '已鎖定物體 {g}：按 W 接近，S 退出並取消，A／D 取消並往那邊走',
           'grasp': '到了物體 {g}：按空白鍵放鬆 1 秒就夾',
           'lift': '夾到物體 {g}：按 W 抬起來'}


def hint(sa, obj, P, x):
    """-> (code, English text for RViz, goal index) for the current assist phase"""
    if isinstance(sa, M.ModeAssist):
        code, en, zh, g = sa.describe(x)
        sa.hint_zh = zh
        return code, en, g
    if sa.state == 'place':
        if sa.place_ok(x):
            return 'place', 'SPACE 1s: put down', sa.goal
        return 'place_lock', 'W: in / S: cancel', sa.goal
    if sa.state == 'grasped':
        if sa.keep:
            if sa.inside(x):
                return 'inside_carry', 'S: back out', sa.goal
            return 'carry', 'carry', sa.goal
        return 'lift', 'W: lift', sa.goal
    if sa.state == 'steer' and sa.inside(x):
        return 'inside', 'S: back out', None
    if sa.state in ('final', 'approach'):
        g = sa.goal
        if np.linalg.norm(obj[g] - x) < 1.5 * A.GRASP_TOL:
            return 'grasp', 'SPACE 1s: grasp', g
        if sa.mode == 'blend':
            return 'go', 'W: in / S: cancel', g
        k = KEY.get(sa.lock_cmd, '?')
        o = KEY.get(A.OPPOSITE.get(sa.lock_cmd, ''), '?')
        return 'go', f'{k}: in / {o}: back', g
    g = int(np.argmax(P))
    if P[g] >= A.P_ON and sa.state == 'steer' and sa.zone(g, x) > 0:
        return 'lead', f'{g}?', g
    return ('free', '', None) if sa.state == 'steer' else ('none', '', None)


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
    command and it stays until another key: w a s d = direction (held), space = relax (stop), h = back to the start
    pose without quitting (returns 'home' once), q = quit"""
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
                if c in (b'h', b'H'):
                    state['home'], state['cmd'] = True, 'rest'
                    continue
                if c in (b'e', b'E'):
                    state['toggle'], state['cmd'] = True, 'rest'
                    continue
                if c in keys and keys[c] != state['cmd']:
                    state['cmd'] = keys[c]
                    print(f'\r  command: {state["cmd"]:6s}', flush=True)
        if state.pop('toggle', False):
            return 'toggle'
        return 'home' if state.pop('home', False) else state['cmd']
    return poll, lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['demo', 'keys', 'scene', 'home', 'start'])
    ap.add_argument('--target', type=int, default=0)
    ap.add_argument('--error', type=float, default=0.12)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--assist', choices=['blend', 'takeover'], default='blend')
    ap.add_argument('--level', type=float, default=0.6)
    ap.add_argument('--modes', type=int, default=1, help='keys: 1 = two-mode control (35.63), 0 = 35.62')
    ap.add_argument('--rule', default='mix', choices=['mix', 'lead'],
                    help='mode-1 steering: mix (35.67, weighted over the candidates, exits on mismatch) or lead (35.63)')
    ap.add_argument('--zone', type=float, default=0.12, help='m; assist only this close (y-z) to an object; 0 = off')
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
        n.markers(OBJECTS, idle.probs() * 0, idle, -1, X0)   # objects + numbers at the start positions, once
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
    if a.mode == 'home':
        import json
        home = np.radians(json.load(open(os.path.join(HERE, 'poses_sim.json'), encoding='utf-8'))['home'])
        print('moving to the home pose', np.round(np.degrees(home)).tolist(), 'deg (4 s)')
        n.gripper(0.0)
        n.send(home, 4.0)
        t1 = time.time()
        while time.time() - t1 < 4.5:
            rclpy.spin_once(n, timeout_sec=0.05)
        print('at home, joints', np.round(np.degrees(n.joints()), 1).tolist(), 'deg; tool',
              np.round(kin.fk(n.joints())[:3, 3], 3).tolist(), ', gripper open')
        rclpy.shutdown()
        return
    sols = [kin.solve(np.radians(s), X0, RD, iters=1500, posture=True) for s in SEEDS]
    good = [qq for qq in sols if np.linalg.norm(kin.fk(qq)[:3, 3] - X0) < 0.002]
    q = max(good, key=kin.margin) if good else min(sols, key=lambda qq: np.linalg.norm(kin.fk(qq)[:3, 3] - X0))
    q_rest = q.copy()                                   # the posture task pulls back toward the start posture
    err0 = np.linalg.norm(kin.fk(q)[:3, 3] - X0)
    print(f'start pose solved: tool error {1000 * err0:.1f} mm, joints >= {np.degrees(kin.margin(q)):.0f} deg from their '
          f'limits; moving there (4 s)')
    n.gripper(0.0)
    n.send(q, 4.0)
    t1 = time.time()
    while time.time() - t1 < 4.5:
        rclpy.spin_once(n, timeout_sec=0.05)
    if a.mode == 'start':
        print('at the start pose, tool', np.round(kin.fk(n.joints())[:3, 3], 3).tolist(), ', gripper open')
        rclpy.shutdown()
        return
    if a.mode == 'keys' and a.modes:
        sa = M.ModeAssist(OBJECTS, SHELVES, level=a.level, zone=(a.zone if a.zone > 0 else None), rule=a.rule)
    else:
        sa = A.Assist(OBJECTS, mode=a.assist, level=a.level, keep=(a.mode == 'keys'), shelves=SHELVES,
                      zone=(a.zone if a.zone > 0 else None))
    rng = np.random.default_rng(a.seed)
    dec = S.Decoder(S.SET5, a.error, rng)
    poll, restore = keyreader() if a.mode == 'keys' else (None, None)
    if a.limit is None:
        a.limit = 300.0 if a.mode == 'keys' else 60.0
    if a.mode == 'keys':
        print('ready. Click this terminal first (not the RViz window), then: w up, s down, a left, d right,')
        print('space = relax (stop), h = back to the start (keeps control), q = quit. A key keeps moving until another key. Seen from behind the arm: '
              'object 0 left-low, 1 right-high, 2 middle-low.', flush=True)
        if isinstance(sa, M.ModeAssist):
            print('two modes: MODE 1 = free (W/S/A/D up/down/left/right in front of the shelves); stop in front of an '
                  'object or a shelf -> MODE 2 = W in / S out (A/D do nothing inside a shelf); back out with S -> MODE 1. '
                  'At an object / a spot on a shelf: space 1 s = grasp / put down. E = switch mode by hand, '
                  'H = back to the start (mode 1 only).', flush=True)
        elif a.assist == 'blend':
            print(f'blend mode, level {a.level}: you steer; stop (space) in front of an object to lock it (green); '
                  'then W approaches, S backs out and cancels; at the object press space and wait 1 s to grasp; '
                  'then move freely.', flush=True)
    last_state = None
    last_hint = None
    last_mode = 1
    hist = [X0.copy()] * (S.REACT + 1)
    held, gripped = 'rest', False
    log = open(a.log, 'w', encoding='utf-8')
    log.write('t,wanted,command,state,goal,p0,p1,p2,x,y,z\n')
    try:
        for k in range(int(a.limit / A.DT)):
            tk = time.time()
            x = kin.fk(q)[:3, 3]
            if a.mode == 'demo':
                if a.assist == 'blend':
                    want, held = S.user_blend(sa, OBJECTS, a.target, hist[-1 - S.REACT], held, dec.est)
                else:
                    want, held = S.user_assist(sa, OBJECTS, a.target, hist[-1 - S.REACT], held)
                cmd = dec(want)
            else:
                want = cmd = poll()
            if cmd == 'toggle':                         # e: switch the mode by hand
                print('  >> ' + sa.toggle(x), flush=True)
                continue
            if cmd == 'home' and isinstance(sa, M.ModeAssist) and sa.m != 1:
                print('  >> H 只能在模式 1 用：先按 S 退回前方平面', flush=True)
                continue
            if cmd == 'home':                           # h: back to the start pose, control continues
                print('  >> 回到起點（3 秒），之後繼續控制' + ('；物體還夾著' if sa.grip else ''), flush=True)
                n.send(q_rest, 3.0)
                t2 = time.time()
                while time.time() - t2 < 3.2:
                    rclpy.spin_once(n, timeout_sec=0.05)
                q = q_rest.copy()
                if isinstance(sa, M.ModeAssist):
                    sa.base.s[:] = 0.0
                    sa.rest_n = 0
                else:
                    if sa.state == 'final':
                        sa.state, sa.goal = 'steer', None
                    sa.s[:] = 0.0
                    sa.final_block, sa.approach, sa.rest_n = None, None, 0
                hist = [kin.fk(q)[:3, 3]] * (S.REACT + 1)
                continue
            v = sa.step(cmd if cmd != 'rest' else None, x)
            if bool(sa.grip) != gripped:
                n.gripper(float(sa.grip))
                gripped = bool(sa.grip)
            q = kin.ik_step(q, v, RD, A.DT, posture=True, q_rest=q_rest)
            n.send(q, A.DT * 1.5)
            P = sa.probs()
            code, hg = n.markers(sa.obj, P, sa, a.target if a.mode == 'demo' else -1, kin.fk(q)[:3, 3])
            hist.append(kin.fk(q)[:3, 3])
            log.write(f'{k * A.DT:.1f},{want},{cmd},{sa.state},{sa.goal},{P[0]:.3f},{P[1]:.3f},{P[2]:.3f},'
                      f'{x[0]:.4f},{x[1]:.4f},{x[2]:.4f}\n')
            log.flush()
            if a.mode == 'keys' and isinstance(sa, M.ModeAssist):
                if (code, hg, sa.hint_zh) != last_hint:
                    last_hint = (code, hg, sa.hint_zh)
                    print('  >> ' + sa.hint_zh, flush=True)
            elif a.mode == 'keys' and (code, hg) != last_hint:
                last_hint = (code, hg)
                if code in HINT_ZH:
                    k = KEY.get(sa.lock_cmd, '?')
                    o = KEY.get(A.OPPOSITE.get(sa.lock_cmd, ''), '?')
                    print('  >> ' + HINT_ZH[code].format(g=hg, k=k, o=o), flush=True)
            if a.mode == 'keys' and isinstance(sa, M.ModeAssist) and sa.m != last_mode:
                last_mode = sa.m
                print('\a' + ('  ===== 模式 2：W 前進、S 後退 =====' if sa.m == 2 else '  ===== 模式 1：上下左右 ====='),
                      flush=True)
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
