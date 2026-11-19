"""Simulated grasp for Gazebo Classic (report 35.64): Gazebo cannot hold an object reliably with the 2F-85, whose
linkage is driven by position commands (the closing fingers push the object away). This node stands in for the grasp
physics, the same idea as a grasp-fix plugin:

- attach: the gripper starts closing (left knuckle > ATTACH rad) while an object's centre is within REACH of the
  tool point (kin.fk, the point between the finger pads) -> that object is carried at the offset it had at that moment,
  upright, velocity zero, re-set every 10 ms through /gazebo/set_entity_state;
- detach: the gripper opens again (knuckle < DETACH rad) -> the object is left to the physics (it must then stand on
  its own on whatever is under it).

What this checks: carrying, put-down position and height, whether the put-down object stands, other objects left
alone. What it does not check: whether a real grip would hold (that needs the real arm).

  python3 src/pc/sim/gz_attach.py            (started by gen3_gazebo.launch.py)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'assist'))
import numpy as np
import rclpy
from gazebo_msgs.msg import EntityState
from gazebo_msgs.srv import GetEntityState, SetEntityState
from sensor_msgs.msg import JointState

import kin

N_OBJ = 3
ATTACH, DETACH = 0.05, 0.03            # rad, left knuckle (0 = open, 0.8 = closed)
REACH = 0.03                           # m, object centre to tool point when the gripper starts closing
SETTLE = 0.5                           # s the object is still held where it was put after the gripper has opened


class Attach:
    def __init__(self):
        self.n = rclpy.create_node('gz_attach')
        self.q = None
        self.knuckle = 0.0
        self.held = None                # (object index, offset from the tool point)
        self.pos = [None] * N_OBJ
        self.watch = None
        self.release = None             # (where the object was put down, time) while the fingers clear it
        self.n.create_subscription(JointState, '/joint_states', self.on_js, 10)
        self.get = self.n.create_client(GetEntityState, '/gazebo/get_entity_state')
        self.set = self.n.create_client(SetEntityState, '/gazebo/set_entity_state')
        self.get.wait_for_service()
        self.set.wait_for_service()
        self.n.create_timer(0.01, self.tick)
        self.n.create_timer(0.1, self.poll)
        self.n.get_logger().info('simulated grasp ready')

    def on_js(self, m):
        d = dict(zip(m.name, m.position))
        if all(f'joint_{i}' in d for i in range(1, 8)):
            self.q = np.array([d[f'joint_{i}'] for i in range(1, 8)])
        self.knuckle = d.get('robotiq_85_left_knuckle_joint', self.knuckle)

    def poll(self):                     # object positions, only needed while nothing is held
        if self.held is not None:
            return
        for i in range(N_OBJ):
            r = GetEntityState.Request()
            r.name = f'object_{i}'
            f = self.get.call_async(r)
            f.add_done_callback(lambda f, i=i: self.got(i, f))

    def got(self, i, f):
        res = f.result()
        if res is not None and res.success:
            p = res.state.pose.position
            self.pos[i] = np.array([p.x, p.y, p.z])
            if self.watch is not None and self.watch[0] == i:      # first 2 s after a release: where it goes
                dt = (self.n.get_clock().now().nanoseconds - self.watch[1]) / 1e9
                if dt < 2.0:
                    self.n.get_logger().info(f'  object_{i} {dt:.1f} s after release: {np.round(self.pos[i], 3).tolist()}')

    def tick(self):
        if self.q is None:
            return
        tool = kin.fk(self.q)[:3, 3]
        if self.held is None:
            if self.knuckle > ATTACH:
                near = [(np.linalg.norm(p - tool), i) for i, p in enumerate(self.pos) if p is not None]
                if near and min(near)[0] < REACH:
                    i = min(near)[1]
                    self.held = (i, self.pos[i] - tool)
                    self.n.get_logger().info(f'attached object_{i} (centre {1000 * min(near)[0]:.0f} mm from the tool)')
            return
        i, off = self.held
        now = self.n.get_clock().now().nanoseconds
        if self.release is None and self.knuckle < DETACH:
            # the closed fingers went through the held object (position-driven linkage); hold it still where it was put
            # for SETTLE s more while the fingers clear it, otherwise the contact solver can throw it on release
            self.release = (tool + off, now)
            self.n.get_logger().info(f'released object_{i} at {np.round(tool + off, 3).tolist()}')
        if self.release is not None:
            if (now - self.release[1]) / 1e9 > SETTLE:
                self.held, self.release = None, None
                self.watch = (i, now)
                return
            p = self.release[0]
        else:
            p = tool + off
        s = EntityState()
        s.name = f'object_{i}'
        s.reference_frame = 'world'
        s.pose.position.x, s.pose.position.y, s.pose.position.z = map(float, p)
        s.pose.orientation.w = 1.0
        r = SetEntityState.Request()
        r.state = s
        self.set.call_async(r)


def main():
    rclpy.init()
    a = Attach()
    rclpy.spin(a.n)


if __name__ == '__main__':
    main()
