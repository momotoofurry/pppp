# report 35.85 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
#!/bin/bash
source /opt/ros/humble/setup.bash
cd /home/momo1234/model-leaf/src/pc/sim
python3 - <<'PY'
import numpy as np
import assist_ros as AR
W, dt = AR.WORKSPACE, 0.1
cases = [
    ('inside, moving freely', [0.6, 0.0, 0.3], [0.0, 0.05, -0.05], [0.0, 0.05, -0.05]),
    ('at the table: down blocked, sideways kept', [0.6, 0.0, 0.065], [0.0, 0.05, -0.08], [0.0, 0.05, 0.0]),
    ('at the table: up still allowed', [0.6, 0.0, 0.065], [0.0, 0.0, 0.08], [0.0, 0.0, 0.08]),
    ('left edge: further left blocked', [0.6, 0.375, 0.3], [0.0, 0.08, 0.0], [0.0, 0.0, 0.0]),
    ('too high: up blocked', [0.6, 0.0, 0.575], [0.0, 0.0, 0.08], [0.0, 0.0, 0.0]),
    ('too far: forward blocked, back allowed', [0.915, 0.0, 0.3], [0.08, 0.0, 0.0], [0.0, 0.0, 0.0]),
    ('too far but backing out', [0.915, 0.0, 0.3], [-0.08, 0.0, 0.0], [-0.08, 0.0, 0.0]),
]
ok = True
for name, x, v, want in cases:
    got, hit = AR.guard(v, x, dt)
    good = np.allclose(got, want)
    ok &= good
    print(f'{"ok " if good else "BAD"} {name}: v {v} -> {got.tolist()} (hit {hit})')
# a long push down from the start point never goes below the table limit
x = np.array([0.58, 0.0, 0.35]); lowest = x[2]
for _ in range(200):
    v, _ = AR.guard([0.0, 0.0, -0.08], x, dt)
    x = x + v * dt
    lowest = min(lowest, x[2])
print(f'20 s of "down" from z 0.35: lowest z {lowest:.3f} m (limit {W[2, 0]})')
ok &= lowest >= W[2, 0] - 1e-9
print('ALL OK' if ok else 'FAILED')
PY
