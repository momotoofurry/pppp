"""tool drift while standing still with the posture task: without and with the position hold (35.63)"""
import sys
sys.path.insert(0, '/work/src/assist')
import numpy as np
import kin
RD = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)
q_rest = kin.solve(np.radians([30, 70, 280, 120, 0, -100, 70]), np.array([0.58, 0, 0.35]), RD, iters=1500, posture=True)
q0 = kin.solve(q_rest, np.array([0.75, 0.25, 0.10]), RD, iters=1500)
for hold in (False, True):
    q = q0.copy()
    xc = kin.fk(q)[:3, 3].copy()
    for _ in range(100):                                       # 10 s standing still
        v = np.zeros(3)
        vv = v + 2.0 * (xc - kin.fk(q)[:3, 3]) if hold else v
        q = kin.ik_step(q, vv, RD, 0.1, posture=True, q_rest=q_rest)
    print('position hold' if hold else 'no hold      ', 'drift after 10 s still:', round(1000 * np.linalg.norm(kin.fk(q)[:3, 3] - xc), 2), 'mm')
