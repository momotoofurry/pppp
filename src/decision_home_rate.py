"""How well each gesture produces its own command at the firmware setting (tau 0.6, k 3), Lateral = home included.

Offline, recorded votes only (no new data, nothing chosen): build/decision/votes_v2.npz (decision_v2.py: firmware v2,
no t-SNE, 20 subjects x 3 seeds x 11 blocks, shift 0) if present, else votes.npz. Per trial (1 s = 10 windows, the
state reset per trial as in eval_decision.py) the first command: per gesture the share of trials whose first command
is that gesture's command ('correct'), a wrong command, or none. This is a per-trial offline proxy, not the closed-
loop task (PROTOCOL.md 5: 5 s limit, continuous stream).
Writes results/decision_home_rate.csv. Usage (in the container): PYTHONPATH=src python src/decision_home_rate.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_oneshot_c as C  # noqa: E402
import eval_decision as E  # noqa: E402

GEST = ['Power', 'Lateral', 'Tripod', 'Pointer', 'Open', 'Rest']


def main():
    lib = C.build()
    path = os.path.join(os.path.dirname(E.VOTES), 'votes_v2.npz')
    if not os.path.exists(path):
        path = E.VOTES
    d = np.load(path)
    print(path, sorted(d.keys()))
    keys = [k for k in d.keys() if k.startswith('votes')]
    seg_key = 'trial'
    extra = [k for k in ('seed', 'shift', 'subject') if k in d]
    seg = d[seg_key].astype(np.int64)
    mult = 1000000
    for k in extra:
        seg = seg + d[k].astype(np.int64) * mult
        mult *= 100
    seg = np.unique(seg, return_inverse=True)[1].astype(np.int32)
    rows = []
    for key in keys:
        if 'shift' in d:
            sel = d['shift'] == 0
        else:
            sel = np.ones(len(seg), bool)
        v, y, s = d[key][sel], d['y'][sel], seg[sel]
        s = np.unique(s, return_inverse=True)[1].astype(np.int32)
        cmd, _, _ = E.replay(lib, np.ascontiguousarray(v), s, 0.6, 3)
        first = {}
        for i in np.flatnonzero(cmd):
            first.setdefault(s[i], cmd[i])
        lab = pd.Series(y).groupby(s).first()
        for g, name in enumerate(GEST):
            tr = lab.index[lab.values == g]
            fc = np.array([first.get(t, 0) for t in tr])
            want = E.CLASS_CMD[g]
            rows.append(dict(votes=key, gesture=name, command=['none', 'pose_A', 'grip', 'pose_B', 'release', 'home'][want],
                             trials=len(tr), correct=round(100 * float((fc == want).mean()), 1) if want else None,
                             wrong=round(100 * float(((fc != want) & (fc != 0)).mean()), 1),
                             no_command=round(100 * float((fc == 0).mean()), 1)))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(E.OUT, 'decision_home_rate.csv'), index=False)
    print(df.to_string(index=False))


if __name__ == '__main__':
    main()
