"""35.92 unit check of assist_ros.rebase: the sent continuous-joint targets stay within half a turn of the measured
angles, also when the hardware reports wrapped angles while the model counts past +-pi; the limited joints are never
changed; the commanded pose (fk) is the same. Run with ROS sourced:
  source /opt/ros/humble/setup.bash; python3 src/pc/s7_test/rebase_test.py"""
import os
import sys

import numpy as np

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
sys.path.insert(0, os.path.join(R, 'pc', 'sim'))
sys.path.insert(0, os.path.join(R, 'assist'))
import assist_ros as AR  # noqa: E402
import kin  # noqa: E402

rng = np.random.default_rng(0)
bad = 0
worst = 0.0
for _ in range(2000):
    q = rng.uniform(-9, 9, 7)                              # model angles, continuous joints counted past +-pi
    for i in (1, 3, 5):
        q[i] = rng.uniform(-2.0, 2.0)
    meas = q + rng.normal(0, 0.02, 7)                      # the arm follows within ~1 deg
    wrapped = meas.copy()
    for i in AR.CONT:
        wrapped[i] = kin.wrap(meas[i])                     # a driver that reports wrapped angles
    for m_ in (meas, wrapped):
        r = AR.rebase(q, m_)
        d = np.abs(r - m_)
        worst = max(worst, d[list(AR.CONT)].max())
        bad += d[list(AR.CONT)].max() > np.pi + 1e-9
        bad += not np.allclose(r[[1, 3, 5]], q[[1, 3, 5]])
        bad += not np.allclose(kin.fk(r)[:3, 3], kin.fk(q)[:3, 3], atol=1e-9)
print(f'2000 random poses x 2 drivers: largest continuous-joint step {np.degrees(worst):.1f} deg; failures {bad}')
ok = bad == 0 and worst < np.radians(10)
print('ALL OK' if ok else 'FAILED')
sys.exit(not ok)
