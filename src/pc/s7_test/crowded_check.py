# report 35.87 (2026-11-24): feasibility of the crowded scene with the random decoder.
"""Is the crowded scene (35.87) feasible? modes_sim.trial with the random decoder (e 0 and 0.1), 3-object vs crowded."""
import sys
import numpy as np
sys.path.insert(0, '/work/src/assist')
import modes_sim as MS
OBJ3, SH3 = MS.OBJ.copy(), MS.SHELVES.copy()
lower = [(0.72, y, 0.05) for y in (-0.25, 0.0, 0.25)]
upper = [(0.72, y, 0.25) for y in (-0.25, 0.0, 0.25)]
OBJC = np.array([(x + dx, y + dy, z + 0.05) for (x, y, z) in lower for dx, dy in ((0.0, -0.04), (0.0, 0.04))])
SHC = np.array(lower + upper)
for name, O, Sh in (('3 objects (35.63)', OBJ3, SH3), ('crowded 6 objects', OBJC, SHC)):
    MS.OBJ, MS.SHELVES = O, Sh
    for e in (0.0, 0.1):
        rng = np.random.default_rng(1)
        res = [MS.trial(e, rng) for _ in range(100)]
        ok = np.mean([r[0] for r in res]); tm = np.median([r[1] for r in res if r[0]])
        wl = np.mean([r[4] for r in res]); col = np.mean([r[2].n for r in res])
        print(f'{name:<20} e {e:.1f}: success {100 * ok:5.1f} %, time {tm:5.1f} s, wrong locks {wl:.2f}, collision steps {col:.2f}')
