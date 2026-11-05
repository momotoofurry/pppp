"""ROS 2 relay for kinova_bridge.py --ros: discrete robot actions -> the simulated Gen3 in RViz (gen3_sim.sh).

Runs in WSL (ROS 2 Humble, rclpy). Windows -> WSL UDP on localhost is not forwarded, TCP is, so kinova_bridge.py
(Windows: UDP from TrignoBridge, keys, robot.csv, the one-action-at-a-time rule) talks to this relay over TCP.
One JSON object per line, both ways:
  -> {"id": 3, "kind": "joints", "target": [7 joint angles, deg, Kortex convention], "speed": 10}
  -> {"id": 4, "kind": "gripper", "target": 0.8}          (0 = open .. 1 = closed)
  -> {"id": 5, "kind": "estop"}                            (cancels the running goal)
  <- {"id": 3, "event": "end" | "abort", "note": "..."}
Joint moves: one-point FollowJointTrajectory goal, duration = largest joint change / speed (the same per-joint speed
limit as the real robot path); angles are taken mod 360 to the nearest equivalent of the current one, so a
continuous joint never turns the long way. Gripper: GripperCommand, position = target * 0.8 rad (2F-85 knuckle).
Usage (WSL, after gen3_sim.sh is up): python3 src/pc/sim/ros_relay.py [--port 50557]
"""
import argparse
import json
import math
import socket
import threading

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from builtin_interfaces.msg import Duration
from control_msgs.action import FollowJointTrajectory, GripperCommand
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectoryPoint

JOINTS = [f'joint_{i}' for i in range(1, 8)]
GRIP_MAX = 0.8


class Relay(Node):
    def __init__(self):
        super().__init__('emg_ros_relay')
        self.arm = ActionClient(self, FollowJointTrajectory, '/joint_trajectory_controller/follow_joint_trajectory')
        self.grip = ActionClient(self, GripperCommand, '/robotiq_gripper_controller/gripper_cmd')
        self.q = {}
        self.create_subscription(JointState, '/joint_states', self._js, 10)
        self.goal = None
        self.lock = threading.Lock()

    def _js(self, m):
        self.q.update(dict(zip(m.name, m.position)))

    def joints(self, target_deg, speed, reply):
        if not all(j in self.q for j in JOINTS):
            return reply('abort', 'no /joint_states yet')
        cur = [self.q[j] for j in JOINTS]
        tgt = []
        for c, d in zip(cur, target_deg):
            t = math.radians(d)
            t = c + math.remainder(t - c, 2 * math.pi)          # nearest equivalent angle
            tgt.append(t)
        dmax = max(abs(t - c) for t, c in zip(tgt, cur))
        dur = max(0.5, math.degrees(dmax) / max(speed, 1e-3))
        g = FollowJointTrajectory.Goal()
        g.trajectory.joint_names = JOINTS
        p = JointTrajectoryPoint(positions=tgt, velocities=[0.0] * 7)
        p.time_from_start = Duration(sec=int(dur), nanosec=int((dur % 1) * 1e9))
        g.trajectory.points = [p]
        self._send(self.arm, g, reply, f'{dur:.1f} s')

    def gripper(self, target, reply):
        g = GripperCommand.Goal()
        g.command.position = float(min(max(target, 0.0), 1.0)) * GRIP_MAX
        g.command.max_effort = 100.0
        self._send(self.grip, g, reply, '')

    def _send(self, client, goal, reply, note):
        if not client.wait_for_server(timeout_sec=2.0):
            return reply('abort', 'action server not available (is gen3_sim.sh running?)')
        fut = client.send_goal_async(goal)

        def accepted(f):
            h = f.result()
            if not h.accepted:
                return reply('abort', 'goal rejected')
            with self.lock:
                self.goal = h
            h.get_result_async().add_done_callback(lambda r: done(r.result()))

        def done(res):
            with self.lock:
                self.goal = None
            st = res.status                                   # 4 = SUCCEEDED, 5 = CANCELED, 6 = ABORTED
            code = getattr(res.result, 'error_code', 0)
            reply('end' if st == 4 and code == 0 else 'abort', f'{note} status {st} code {code}'.strip())
        fut.add_done_callback(accepted)

    def estop(self):
        with self.lock:
            h = self.goal
        if h is not None:
            h.cancel_goal_async()


def serve(node, port):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', port))
    srv.listen(1)
    print(f'relay listening on 127.0.0.1:{port}')
    while rclpy.ok():
        conn, _ = srv.accept()
        print('kinova_bridge connected')
        wlock = threading.Lock()
        f = conn.makefile('r', encoding='utf-8')
        for line in f:
            try:
                m = json.loads(line)
            except ValueError:
                continue
            mid = m.get('id')

            def reply(event, note, mid=mid):
                with wlock:
                    try:
                        conn.sendall((json.dumps({'id': mid, 'event': event, 'note': note}) + '\n').encode())
                    except OSError:
                        pass
                print(f'  {mid}: {event} {note}')
            k = m.get('kind')
            if k == 'joints':
                node.joints(m['target'], float(m.get('speed', 10.0)), reply)
            elif k == 'gripper':
                node.gripper(float(m['target']), reply)
            elif k == 'estop':
                node.estop()
        print('kinova_bridge disconnected')
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=50557)
    args = ap.parse_args()
    rclpy.init()
    node = Relay()
    threading.Thread(target=rclpy.spin, args=(node,), daemon=True).start()
    try:
        serve(node, args.port)
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.shutdown()


if __name__ == '__main__':
    main()
