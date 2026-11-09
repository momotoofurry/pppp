"""Proposed robot gesture map (PC-side remap, firmware unchanged): command-level offline replay.

Map (2026-11-09 proposal, not in PROTOCOL): Power = grip, Open = open, Lateral = home (discrete; freeze-5 rule tau 0.6,
k 3, send once per hold); Pointer = down, Tripod = up (hold-to-move: the arm moves on every window whose accepted run
of that class is >= k; a rejected window or another class stops it). Recorded votes only (nothing chosen):
build/decision/votes_v2.npz (20 subjects x 3 seeds x 11 blocks, shift 0), self-calibrated (sc) and one-shot (os).
Each 1 s trial (10 windows) holds one gesture; no transitions, so this is an offline proxy, not the closed-loop task.
Writes results/decision_robot_map_discrete.csv and results/decision_robot_map_hold.csv.
Usage (in the container): PYTHONPATH=src python src/decision_robot_map.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_oneshot_c as C  # noqa: E402
import eval_decision as E  # noqa: E402

GEST = ['Power', 'Lateral', 'Tripod', 'Pointer', 'Open', 'Rest']
NEW = {'Power': 'grip', 'Lateral': 'home', 'Tripod': 'up(hold)', 'Pointer': 'down(hold)', 'Open': 'open', 'Rest': 'none'}
TAU, K, WIN_S = 0.6, 3, 0.1
P, T, O = GEST.index('Pointer'), GEST.index('Tripod'), GEST.index('Open')


def segments(d):
    seg = d['trial'].astype(np.int64)
    mult = 1000000
    for k in ('seed', 'shift', 'subject'):
        if k in d:
            seg = seg + d[k].astype(np.int64) * mult
            mult *= 100
    return seg


def hold_runs(votes, seg):
    """Per window: the class whose accepted consecutive run is >= K, else -1. A rejected window or a new trial resets."""
    n = len(votes)
    out = np.full(n, -1, np.int8)
    top = np.argmax(votes, axis=1)
    ok = votes[np.arange(n), top].astype(np.int64) * 1000 >= int(round(TAU * 1000)) * E.TREES
    last, run = -1, 0
    for i in range(n):
        if i > 0 and seg[i] != seg[i - 1]:
            last, run = -1, 0
        if not ok[i]:
            last, run = -1, 0
            continue
        run = run + 1 if top[i] == last else 1
        last = top[i]
        if run >= K:
            out[i] = top[i]
    return out


def main():
    lib = C.build()
    path = os.path.join(os.path.dirname(E.VOTES), 'votes_v2.npz')
    d = np.load(path)
    sel = d['shift'] == 0 if 'shift' in d else np.ones(len(d['y']), bool)
    seg = np.unique(segments(d)[sel], return_inverse=True)[1].astype(np.int32)
    y = d['y'][sel].astype(int)
    cmd2cls = {int(E.CLASS_CMD[g]): g for g in range(6) if E.CLASS_CMD[g] != 0}
    lab = pd.Series(y).groupby(seg).first()
    disc, hold = [], []
    for key in ('votes_os', 'votes_sc'):
        v = np.ascontiguousarray(d[key][sel])
        cmd, _, _ = E.replay(lib, v, seg, TAU, K)
        first, open_any = {}, np.zeros(seg.max() + 1, bool)
        for i in np.flatnonzero(cmd):
            c = cmd2cls[int(cmd[i])]
            first.setdefault(seg[i], c)
            open_any[seg[i]] |= c == O
        for g, name in enumerate(GEST):
            tr = lab.index[lab.values == g]
            fc = np.array([first.get(t, -1) for t in tr])
            row = dict(votes=key, true=name, new_meaning=NEW[name], trials=len(tr),
                       none=round(100 * float((fc == -1).mean()), 1),
                       open_sent_any=round(100 * float(open_any[tr].mean()), 1))
            for h, hn in enumerate(GEST[:-1]):
                row['first_' + hn] = round(100 * float((fc == h).mean()), 1)
            disc.append(row)
        hr = hold_runs(v, seg)
        for g, name in enumerate(GEST):
            m = y == g
            minutes = m.sum() * WIN_S / 60
            hold.append(dict(votes=key, true=name, windows=int(m.sum()),
                             down_pct=round(100 * float((hr[m] == P).mean()), 2),
                             up_pct=round(100 * float((hr[m] == T).mean()), 2),
                             down_s_per_min=round(float((hr[m] == P).sum()) * WIN_S / minutes, 2),
                             up_s_per_min=round(float((hr[m] == T).sum()) * WIN_S / minutes, 2)))
    a, b = pd.DataFrame(disc), pd.DataFrame(hold)
    a.to_csv(os.path.join(E.OUT, 'decision_robot_map_discrete.csv'), index=False)
    b.to_csv(os.path.join(E.OUT, 'decision_robot_map_hold.csv'), index=False)
    print(path, 'trials', seg.max() + 1)
    print(a.to_string(index=False))
    print(b.to_string(index=False))


if __name__ == '__main__':
    main()
