"""Vote margins of the 100-tree forest (thesis 3.6.5, report 30): how many predictions one self-calibration can change.

One self-calibration replaces SC_N_UPD = 20 of the 100 trees, so every class count moves by at most 20 and a window
whose margin m = votes(top) - votes(runner-up) is > 40 keeps its prediction (with the lowest-class tie rule: a
margin of exactly 40 can flip only by a tie, so m <= 40 is the bound used). From the recorded firmware v2 votes
(build/decision/votes_v2.npz, 20 subjects x 3 seeds x 11 blocks, shifts 0 / 0.5 / 1) per model (self-calibrated,
fixed one-shot) and shift: share of windows with m <= 40 (the most one update can change), m <= 20, and the same
share among correctly and wrongly classified windows.
Writes results/vote_margin.csv. Usage (in the container): python src/vote_margin.py
"""
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    d = np.load(os.path.join(ROOT, 'build', 'decision', 'votes_v2.npz'))
    rows = []
    for key in ['votes_sc', 'votes_os']:
        for sh in np.unique(d['shift']):
            sel = d['shift'] == sh
            v = d[key][sel].astype(int)
            y = d['y'][sel]
            s = np.sort(v, 1)
            m = s[:, -1] - s[:, -2]
            top = v.argmax(1)
            ok = top == y
            rows.append(dict(model=key[6:], shift=float(sh), windows=int(sel.sum()), total_votes=int(v[0].sum()),
                             accuracy=round(100 * ok.mean(), 2),
                             margin_le40=round(100 * (m <= 40).mean(), 2), margin_le20=round(100 * (m <= 20).mean(), 2),
                             margin_le40_correct=round(100 * (m[ok] <= 40).mean(), 2),
                             margin_le40_wrong=round(100 * (m[~ok] <= 40).mean(), 2),
                             median_margin=float(np.median(m))))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(ROOT, 'results', 'vote_margin.csv'), index=False)
    print(df.to_string(index=False))


if __name__ == '__main__':
    main()
