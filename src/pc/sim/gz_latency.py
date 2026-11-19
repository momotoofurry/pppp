"""PC-side latency in Gazebo (report 35.69): key -> the simulated arm starts moving, space (relax) -> it stops.
Runs assist_ros.py keys in a pseudo-terminal with the given extra options and watches /joint_states (wall clock).
Mode 1, free space: W up 1.2 s, space, wait, S down 1.2 s, space, wait; N repeats.

usage: python3 src/pc/sim/gz_latency.py [--n 5] [-- extra assist_ros options]
"""
import os
import pty
import select
import sys
import time

import numpy as np
import rclpy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'assist'))
import kin  # noqa: E402
from sensor_msgs.msg import JointState

args = sys.argv[1:]
N = 5
if '--n' in args:
    i = args.index('--n')
    N = int(args[i + 1])
    args = args[:i] + args[i + 2:]
extra = args[args.index('--') + 1:] if '--' in args else []

rclpy.init()
node = rclpy.create_node('gz_latency')
hist = []                                     # (wall time, tool position from the joints; the posture task moves joints
#                                               without moving the tool, so motion is judged on the tool)
node.create_subscription(JointState, '/joint_states', lambda m: hist.append(
    (time.time(), kin.fk(np.array([dict(zip(m.name, m.position)).get(f'joint_{i}', 0.0) for i in range(1, 8)]))[:3, 3])), 50)

pid, fd = pty.fork()
if pid == 0:
    os.execvp('python3', ['python3', 'src/pc/sim/assist_ros.py', 'keys', '--log', '/tmp/gz_latency.csv'] + extra)
out = b''


def pump(sec):
    global out
    t = time.time()
    while time.time() - t < sec:
        rclpy.spin_once(node, timeout_sec=0.005)
        r, _, _ = select.select([fd], [], [], 0)
        if r:
            try:
                out += os.read(fd, 4096)
            except OSError:
                return


def moving_after(t0, thr=0.001):
    """first wall time after t0 at which the tool moved more than thr (m) from its position at t0"""
    base = next((q for t, q in reversed(hist) if t <= t0), None)
    for t, q in hist:
        if t > t0 and base is not None and np.abs(q - base).max() > thr:
            return t
    return None


def still_after(t0, thr=0.0005, span=0.1):
    """first wall time after t0 from which the tool moves less than thr (m) over span"""
    pts = [(t, q) for t, q in hist if t > t0]
    for i, (t, q) in enumerate(pts):
        later = [q2 for t2, q2 in pts[i:] if t2 <= t + span]
        if pts[-1][0] >= t + span and np.abs(np.array(later) - q).max() < thr:
            return t
    return None


t = time.time()
while b'ready' not in out and time.time() - t < 60:
    pump(0.1)
pump(5.0)                                       # the move to the start pose
starts, stops, cvs = [], [], []
for r in range(N):
    for k in (b'w', b's'):
        t0 = time.time()
        os.write(fd, k)
        pump(1.2)
        t1 = time.time()
        os.write(fd, b' ')
        pump(1.5)
        a = moving_after(t0)
        b = still_after(t1)
        # smoothness while moving: tool speed over 50 ms bins from 0.3 s after the key to the relax
        seg = [(t, q) for t, q in hist if t0 + 0.3 <= t <= t1]
        if len(seg) > 10:
            tt = np.array([t for t, _ in seg])
            qq = np.array([q for _, q in seg])
            edges = np.arange(tt[0], tt[-1], 0.05)
            sp = []
            for e0, e1 in zip(edges[:-1], edges[1:]):
                i0, i1 = np.searchsorted(tt, e0), np.searchsorted(tt, e1)
                if i1 > i0:
                    sp.append(np.linalg.norm(qq[i1 - 1] - qq[i0]) / max(tt[i1 - 1] - tt[i0], 1e-3))
            sp = np.array(sp)
            if len(sp) > 3 and sp.mean() > 0:
                cvs.append(sp.std() / sp.mean())
        if a:
            starts.append(1000 * (a - t0))
        if b:
            stops.append(1000 * (b - t1))
os.write(fd, b'q')
pump(2.0)
print(f'options {extra}: key -> tool moving  median {np.median(starts):.0f} ms (n {len(starts)}, range {min(starts):.0f}-{max(starts):.0f}); '
      f'relax -> tool still  median {np.median(stops):.0f} ms (n {len(stops)}, range {min(stops):.0f}-{max(stops):.0f}); '
      f'speed variation while moving (std / mean of 50 ms tool speed) median {np.median(cvs):.2f}')
rclpy.shutdown()
