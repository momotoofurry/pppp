"""Numbers behind the parameter derivations of thesis 3.11 (report 30). Recorded votes / closed forms only, nothing chosen.

1. Decision k (window agreement) on Rest trials (stand-in for non-control movement), firmware v2 votes, shift 0,
   tau 0.6: q_c = share of Rest windows accepted with top = command class c. If windows were independent, a wrong
   command needs k accepted windows of one class in a row, so its rate is about 600 * sum_c q_c^k per minute
   ("independent model"); against the observed command rate in Rest trials from the C dc_replay (state reset per
   1 s trial, as eval_decision.py; rate per minute of Rest windows). Shows how much faster than independent the
   real (overlapping, correlated) windows are, and the decision-rule latency (k - 1) * 100 ms.
2. Closed forms: z-score rate a = 0.3 (day-1 weight 0.7^n, half-life, steady-state variance factor a / (2 - a));
   tree replacement 20 of the 50 appended trees per update (expected original share 0.6^u, half-life); class-mean
   standard error 1 / sqrt(n) at SC_MIN_CLASS 10 and at the balanced buffer 375 / 6; Q5.10 range +-32 standard
   deviations: Chebyshev bound P(|z| >= 32) <= 1 / 32^2.
Writes results/param_math_decision.csv and results/param_math_closed.csv.
Usage (in the container): PYTHONPATH=src python src/param_math.py
"""
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_oneshot_c as C  # noqa: E402
import eval_decision as E  # noqa: E402

CMD_CLASSES = [0, 1, 2, 3, 4]          # Power, Lateral, Tripod, Pointer, Open (Rest = 5 sends nothing)


def decision():
    lib = C.build()
    d = np.load(os.path.join(os.path.dirname(E.VOTES), 'votes_v2.npz'))
    sel = d['shift'] == 0
    seg = ((d['subject'].astype(np.int64) * 100 + d['seed']) * 1000000 + d['trial'])[sel]
    order = np.argsort(seg, kind='stable')
    seg = np.unique(seg[order], return_inverse=True)[1].astype(np.int32)
    rows = []
    for key in ['votes_sc', 'votes_os']:
        v = np.ascontiguousarray(d[key][sel][order])
        y = d['y'][sel][order]
        rest = y == 5
        top = v.argmax(1)
        acc = v.max(1) * 1000 >= 600 * v.sum(1)
        q = {c: float((rest & acc & (top == c)).sum() / rest.sum()) for c in CMD_CLASSES}
        rest_min = rest.sum() / 600.0
        for k in [1, 2, 3, 4, 5]:
            cmd, _, _ = E.replay(lib, v, seg, 0.6, k)
            obs = float(((cmd != 0) & rest).sum() / rest_min)
            ind = 600.0 * sum(qc ** k for qc in q.values())
            rows.append(dict(model=key[6:], tau=0.6, k=k, latency_rule_ms=(k - 1) * 100,
                             q_total=round(sum(q.values()), 4), independent_per_min=round(ind, 3),
                             observed_rest_per_min=round(obs, 3),
                             observed_over_independent=round(obs / ind, 1) if ind > 0 else None))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(E.OUT, 'param_math_decision.csv'), index=False)
    print(df.to_string(index=False))


def closed():
    a = 0.3
    rows = [
        dict(item='z-score day-1 weight after 5 blocks (0.7^5)', value=round((1 - a) ** 5, 4)),
        dict(item='z-score day-1 weight after 10 blocks', value=round((1 - a) ** 10, 4)),
        dict(item='z-score half-life (blocks)', value=round(math.log(0.5) / math.log(1 - a), 2)),
        dict(item='z-score half-life (s, block = 300 windows = 30 s)', value=round(30 * math.log(0.5) / math.log(1 - a), 1)),
        dict(item='z-score steady-state variance factor a/(2-a)', value=round(a / (2 - a), 4)),
        dict(item='z-score effective blocks (2-a)/a', value=round((2 - a) / a, 2)),
        dict(item='appended trees still original after 1 update (0.6)', value=0.6),
        dict(item='appended trees still original after 5 updates (0.6^5)', value=round(0.6 ** 5, 4)),
        dict(item='tree half-life (updates)', value=round(math.log(0.5) / math.log(0.6), 2)),
        dict(item='votes one update can move per class', value=20),
        dict(item='votes never changed by self-calibration (pretrained)', value=50),
        dict(item='class-mean standard error at 10 rows (sigma units)', value=round(1 / math.sqrt(10), 3)),
        dict(item='class-mean standard error at 375/6 rows', value=round(1 / math.sqrt(375 / 6), 3)),
        dict(item='Chebyshev bound P(|z| >= 32)', value=round(1 / 32 ** 2, 6)),
        dict(item='Q5.10 resolution (sigma units)', value=2 ** -10),
        dict(item='buffer bytes 375 x 80 x 2', value=375 * 80 * 2),
        dict(item='nodes per new tree <= 2*32-1', value=63),
        dict(item='nodes per depth-10 tree <= 2^11-1', value=2 ** 11 - 1),
    ]
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(E.OUT, 'param_math_closed.csv'), index=False)
    print(df.to_string(index=False))


if __name__ == '__main__':
    closed()
    decision()
