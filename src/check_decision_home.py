"""pilot-freeze-5 check: Lateral = home in decision.c (dc_class_command) against the Python re-implementation.

Uses the recorded votes of eval_decision.py (build/decision/votes.npz: 20 subjects x 3 seeds x 11 blocks, the
self-calibrated and the fixed one-shot model) and the same per-trial reset. For three (tau, k) settings: the C
dc_replay() commands must equal replay_python() window by window (CLASS_CMD now has Lateral = 5); and per command
code the number of commands sent, with Lateral trials counted separately (before freeze-5 they sent nothing).
Writes results/decision_home_check.csv. Usage (in the container): PYTHONPATH=src python src/check_decision_home.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_oneshot_c as C  # noqa: E402
import eval_decision as E  # noqa: E402

assert list(E.CLASS_CMD) == [1, 5, 2, 3, 4, 0]


def main():
    lib = C.build()
    d = np.load(E.VOTES)
    seg = d['seed'].astype(np.int64) * 1000000 + d['trial']
    seg = np.unique(seg, return_inverse=True)[1].astype(np.int32)
    rows = []
    for key in ['votes_sc', 'votes_os']:
        for tau, k in [(0.0, 1), (0.6, 3), (0.8, 5)]:
            c, _, _ = E.replay(lib, d[key], seg, tau, k)
            py = E.replay_python(d[key], seg, tau, k)
            r = dict(model=key[6:], tau=tau, k=k, windows=len(c), identical=bool(np.array_equal(c, py)))
            for code, name in [(1, 'pose_A'), (2, 'grip'), (3, 'pose_B'), (4, 'release'), (5, 'home')]:
                r[f'n_{name}'] = int((c == code).sum())
            lat = d['y'] == 1
            r['home_in_lateral_trials'] = int(((c == 5) & lat).sum())
            r['lateral_trials'] = int(len(np.unique(seg[lat])))
            rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(E.OUT, 'decision_home_check.csv'), index=False)
    print(df.to_string(index=False))
    assert df.identical.all()


if __name__ == '__main__':
    main()
