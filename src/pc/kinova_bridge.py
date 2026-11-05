"""Kinova Gen3 bridge for the study (PROTOCOL.md 5, 8, 11): board commands -> discrete robot actions -> robot.csv.

TrignoBridge.exe run --udp 50555,50556 forwards every board COMMAND / STATUS (only after a good start-up alignment,
the alignment gate) as UDP "<unix_ms>,<mcu.csv line>" to TaskScreen (50555) and to this script (50556).
Command -> action (one at a time; a command that arrives while the robot moves is logged as 'busy' and ignored):
  grip    gripper to --grip-close (0..1)          release  gripper to --grip-open
  pose_A  joint angles of pose_A in --poses       pose_B   pose_B          home  home (if the firmware sends it)
Joint moves use a per-joint speed limit (--speed deg/s, low by default). Keys while running (console window):
  e = emergency stop (Base.ApplyEmergencyStop; also stops the bridge from moving again until 'c'),
  c = clear faults and accept commands again, q = quit.
robot.csv (one row per event, Unix ms, the same clock as the other files): received, start, end / abort, busy,
estop, clear. End-to-end latency = robot start - the EMG window time (from mcu.csv by window number).

Modes:
  --sim                    no robot, actions take --sim-s seconds (tests on any PC; this is what was tested)
  --ros [127.0.0.1:50557]  simulated Gen3 + Robotiq 2F-85 in RViz (ROS 2 mock hardware in WSL): first
                           bash src/pc/sim/gen3_sim.sh and python3 src/pc/sim/ros_relay.py in WSL; poses in degrees
                           (Kortex convention), e.g. src/pc/sim/poses_sim.json. Same busy / e-stop / robot.csv logic.
  --ip 192.168.1.10        real robot through the Kortex API (pip package kortex_api, from Kinova); user name and
                           password from --user / the environment variable KINOVA_PASSWORD (never in a file).
                           NOT tested yet: no robot here. Check on the lab robot with the arm in a free space first.
  teach --ip ... --name pose_A [--poses poses.json]
                           store the robot's current joint angles under a name (move the arm by hand / web app).
Usage: python kinova_bridge.py run (--sim | --ip IP) [--udp 50556] [--out robot.csv] [--poses poses.json]
"""
import argparse
import json
import os
import socket
import sys
import threading
import time

try:
    import msvcrt                               # Windows console keys
except ImportError:                             # pragma: no cover
    msvcrt = None

COMMANDS = ('grip', 'release', 'pose_A', 'pose_B', 'home')


def unix_ms():
    return time.time() * 1000.0


class Log:
    def __init__(self, path):
        exists = os.path.exists(path)
        self.f = open(path, 'a', encoding='utf-8')
        if not exists:
            self.f.write('unix_ms,event,command,window,board_ms,action,note\n')
        self.lock = threading.Lock()

    def __call__(self, event, command='', window='', board_ms='', action='', note=''):
        with self.lock:
            self.f.write(f'{unix_ms():.1f},{event},{command},{window},{board_ms},{action},{str(note).replace(",", " ")}\n')
            self.f.flush()


class SimRobot:
    def __init__(self, seconds):
        self.seconds = seconds

    def run(self, kind, target, done):
        def go():
            time.sleep(self.seconds)
            done('end', '')
        threading.Thread(target=go, daemon=True).start()

    def estop(self):
        pass

    def clear(self):
        pass

    def close(self):
        pass


class RosRobot:
    """the simulated Gen3 in RViz: actions go over TCP to src/pc/sim/ros_relay.py (WSL, ROS 2) - see gen3_sim.sh"""

    def __init__(self, addr, speed):
        host, port = addr.rsplit(':', 1)
        self.sock = socket.create_connection((host, int(port)), timeout=5)
        self.sock.settimeout(None)
        self.speed = speed
        self.n, self.pending, self.lock = 0, {}, threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.sock.makefile('r', encoding='utf-8'):
            m = json.loads(line)
            with self.lock:
                done = self.pending.pop(m.get('id'), None)
            if done:
                done(m['event'], m.get('note', ''))

    def _send(self, msg, done=None):
        with self.lock:
            self.n += 1
            msg['id'] = self.n
            if done:
                self.pending[self.n] = done
        self.sock.sendall((json.dumps(msg) + '\n').encode())

    def run(self, kind, target, done):
        if kind == 'gripper':
            self._send({'kind': 'gripper', 'target': float(target)}, done)
        else:
            self._send({'kind': 'joints', 'target': [float(v) for v in target], 'speed': self.speed}, done)

    def estop(self):
        self._send({'kind': 'estop'})

    def clear(self):
        pass

    def close(self):
        self.sock.close()


class KortexRobot:                              # untested without the robot
    def __init__(self, ip, user, password, speed):
        from kortex_api.TCPTransport import TCPTransport
        from kortex_api.RouterClient import RouterClient
        from kortex_api.SessionManager import SessionManager
        from kortex_api.autogen.client_stubs.BaseClientRpc import BaseClient
        from kortex_api.autogen.messages import Base_pb2, Session_pb2
        self.B = Base_pb2
        self.speed = speed
        self.transport = TCPTransport()
        self.router = RouterClient(self.transport, lambda e: print('kortex error', e))
        self.transport.connect(ip, 10000)
        info = Session_pb2.CreateSessionInfo()
        info.username, info.password = user, password
        info.session_inactivity_timeout, info.connection_inactivity_timeout = 60000, 2000
        self.session = SessionManager(self.router)
        self.session.CreateSession(info)
        self.base = BaseClient(self.router)
        mode = Base_pb2.ServoingModeInformation()
        mode.servoing_mode = Base_pb2.SINGLE_LEVEL_SERVOING
        self.base.SetServoingMode(mode)
        self.done = None
        self.base.OnNotificationActionTopic(self._note, Base_pb2.NotificationOptions())

    def _note(self, n):
        if self.done is None:
            return
        if n.action_event == self.B.ACTION_END:
            d, self.done = self.done, None
            d('end', '')
        elif n.action_event == self.B.ACTION_ABORT:
            d, self.done = self.done, None
            d('abort', str(n.abort_details))

    def joints(self):
        return [j.value for j in self.base.GetMeasuredJointAngles().joint_angles]

    def run(self, kind, target, done):
        B = self.B
        if kind == 'gripper':
            cmd = B.GripperCommand()
            cmd.mode = B.GRIPPER_POSITION
            f = cmd.gripper.finger.add()
            f.finger_identifier, f.value = 1, float(target)
            self.base.SendGripperCommand(cmd)
            threading.Timer(1.5, lambda: done('end', 'gripper: fixed 1.5 s')).start()
            return
        a = B.Action()
        a.name = 'emg_' + kind
        for i, v in enumerate(target):
            j = a.reach_joint_angles.joint_angles.joint_angles.add()
            j.joint_identifier, j.value = i, float(v)
        a.reach_joint_angles.constraint.type = B.JOINT_CONSTRAINT_SPEED
        a.reach_joint_angles.constraint.value = self.speed
        self.done = done
        self.base.ExecuteAction(a)

    def estop(self):
        self.base.ApplyEmergencyStop()

    def clear(self):
        self.base.ClearFaults()

    def close(self):
        self.session.CloseSession()
        self.transport.disconnect()


def robot_from(args):
    if args.sim:
        return SimRobot(args.sim_s)
    if args.ros:
        return RosRobot(args.ros, args.speed)
    pw = os.environ.get('KINOVA_PASSWORD')
    if pw is None:
        sys.exit('set KINOVA_PASSWORD in this console first (the password is not taken from a file)')
    return KortexRobot(args.ip, args.user, pw, args.speed)


def run(args):
    poses = json.load(open(args.poses)) if os.path.exists(args.poses) else {}
    log = Log(args.out)
    robot = robot_from(args)
    state = dict(busy=False, stopped=False, cur='')
    lock = threading.Lock()
    log('session', note=f"mode {'sim' if args.sim else ('ros ' + args.ros) if args.ros else args.ip} poses {sorted(poses)} speed {args.speed}")

    def finished(kind, note):
        with lock:
            log(kind, state['cur'], note=note)
            print(f'  {kind}: {state["cur"]} {note}')
            state['busy'] = False

    def action_for(cmd):
        if cmd == 'grip':
            return 'gripper', args.grip_close
        if cmd == 'release':
            return 'gripper', args.grip_open
        if cmd in poses:
            return 'joints', poses[cmd]
        return None, None

    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(('127.0.0.1', args.udp))
    udp.settimeout(0.2)
    print(f'listening on 127.0.0.1:{args.udp}; keys: e = emergency stop, c = clear, q = quit')
    t_end = time.time() + args.seconds if args.seconds else None
    try:
        while t_end is None or time.time() < t_end:
            if msvcrt and msvcrt.kbhit():
                k = msvcrt.getwch().lower()
                if k == 'e':
                    robot.estop()
                    with lock:
                        state['stopped'], state['busy'] = True, False
                    log('estop')
                    print('EMERGENCY STOP: no more moves until c')
                elif k == 'c':
                    robot.clear()
                    with lock:
                        state['stopped'] = False
                    log('clear')
                    print('faults cleared, commands accepted again')
                elif k == 'q':
                    break
            try:
                b, _ = udp.recvfrom(4096)
            except socket.timeout:
                continue
            f = b.decode('ascii', 'replace').split(',')
            if len(f) < 6 or f[1] != 'command':
                continue
            board_ms, window, cmd = f[0], f[2], f[5]
            kind, target = action_for(cmd)
            with lock:
                log('received', cmd, window, board_ms, kind or '')
                if kind is None:
                    print(f'{cmd}: no action configured (poses file: {args.poses})')
                    continue
                if state['stopped'] or state['busy']:
                    log('busy' if state['busy'] else 'ignored_estop', cmd, window, board_ms)
                    print(f'{cmd}: ignored ({"robot moving" if state["busy"] else "emergency stop"})')
                    continue
                state['busy'], state['cur'] = True, cmd
                log('start', cmd, window, board_ms, kind)
                print(f'{cmd} (window {window}) -> {kind}')
            robot.run(kind, target, finished)
    finally:
        log('session_end')
        robot.close()


def teach(args):
    pw = os.environ.get('KINOVA_PASSWORD')
    if pw is None:
        sys.exit('set KINOVA_PASSWORD in this console first')
    r = KortexRobot(args.ip, args.user, pw, args.speed)
    poses = json.load(open(args.poses)) if os.path.exists(args.poses) else {}
    poses[args.name] = r.joints()
    json.dump(poses, open(args.poses, 'w'), indent=1)
    print(args.name, poses[args.name])
    r.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['run', 'teach'])
    ap.add_argument('--sim', action='store_true')
    ap.add_argument('--sim-s', type=float, default=1.5)
    ap.add_argument('--ip')
    ap.add_argument('--ros', nargs='?', const='127.0.0.1:50557', help='simulated Gen3 in RViz via ros_relay.py')
    ap.add_argument('--user', default='admin')
    ap.add_argument('--udp', type=int, default=50556)
    ap.add_argument('--out', default='robot.csv')
    ap.add_argument('--poses', default='poses.json')
    ap.add_argument('--speed', type=float, default=10.0, help='joint speed limit, deg/s')
    ap.add_argument('--grip-close', type=float, default=0.8)
    ap.add_argument('--grip-open', type=float, default=0.0)
    ap.add_argument('--seconds', type=float, default=0, help='stop after this many seconds (tests)')
    ap.add_argument('--name')
    args = ap.parse_args()
    if not args.sim and not args.ip and not args.ros:
        sys.exit('--sim, --ros or --ip')
    teach(args) if args.mode == 'teach' else run(args)


if __name__ == '__main__':
    main()
