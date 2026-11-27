import sys
sys.path.insert(0, '/work/src/assist')
import numpy as np
import assist_sim as S
for cond in ('direct', 'assist'):
    rng = np.random.default_rng(7)
    shown = 0
    for i in range(60):
        log = []
        r, t = S.trial(cond, 0.0, rng, log)
        if r != 'success' and shown < 2:
            shown += 1
            print('=====', cond, r)
            for row in log[:4] + log[-6:]:
                print(row)
