"""The proved properties of decision.c (thesis 3.8, report 29) checked on the C implementation with recorded votes.

dc_replay() (the firmware's dc_step, PC build) on build/decision/votes_v2.npz (firmware v2 votes, 20 subjects x 3
seeds x 11 blocks x 3 shifts, self-calibrated and one-shot model), the state reset at every trial as in
eval_decision.py, for every tau x k of decision_v2.py. Per window t (within one reset segment):
  P1  a command at t  =>  windows t-k+1..t exist in the segment, all accepted, all with the same top class
  P2  two commands of the same class at t1 < t2  =>  some class h != that class is established in (t1, t2)
  P3  two consecutive establishments at t1 < t2  =>  t2 - t1 >= k (so commands are >= k windows apart)
  P4  no command at a rejected window, never a command for Rest
Counts every violation (expected 0) and the smallest observed spacing between commands.
Writes results/decision_props.csv. Usage (in the container): PYTHONPATH=src python src/check_decision_props.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_oneshot_c as C  # noqa: E402
import eval_decision as E  # noqa: E402

TAUS = [0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.95]
KS = [1, 2, 3, 4, 5]


def check(votes, seg, tau, k, lib):
    cmd, acc, est = E.replay(lib, votes, seg, tau, k)
    top = votes.argmax(1)                          # ties -> lowest class, as dc_step
    p1 = p2 = p3 = p4 = 0
    gaps = []
    starts = np.r_[0, np.flatnonzero(np.diff(seg)) + 1, len(seg)]
    for a, b in zip(starts[:-1], starts[1:]):
        last_est, last_cmd_t = {}, None
        prev_est_t = None
        ests = []
        for t in range(a, b):
            if est[t] >= 0:
                if prev_est_t is not None and t - prev_est_t < k:
                    p3 += 1
                prev_est_t = t
                ests.append((t, est[t]))
            if cmd[t] != 0:
                if t - k + 1 < a or not (acc[t - k + 1:t + 1].all() and (top[t - k + 1:t + 1] == top[t]).all()):
                    p1 += 1
                if not acc[t] or top[t] == 5:
                    p4 += 1
                c = int(cmd[t])
                if c in last_est:
                    t1 = last_est[c]
                    if not any(t1 < s < t and h != top[t] for s, h in ests):
                        p2 += 1
                last_est[c] = t
                if last_cmd_t is not None:
                    gaps.append(t - last_cmd_t)
                last_cmd_t = t
    return dict(commands=int((cmd != 0).sum()), P1_violations=p1, P2_violations=p2, P3_violations=p3,
                P4_violations=p4, min_gap_windows=int(min(gaps)) if gaps else None)


def main():
    lib = C.build()
    path = os.path.join(os.path.dirname(E.VOTES), 'votes_v2.npz')
    d = np.load(path)
    seg = (d['subject'].astype(np.int64) * 100 + d['seed']) * 100 + d['shift']
    seg = seg * 1000000 + d['trial']
    seg = np.unique(seg, return_inverse=True)[1].astype(np.int32)
    order = np.argsort(seg, kind='stable')         # each segment contiguous
    rows = []
    for key in ['votes_sc', 'votes_os']:
        v = np.ascontiguousarray(d[key][order])
        s = np.ascontiguousarray(seg[order])
        for tau in TAUS:
            for k in KS:
                rows.append(dict(model=key[6:], tau=tau, k=k, windows=len(s), **check(v, s, tau, k, lib)))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(E.OUT, 'decision_props.csv'), index=False)
    print(df.to_string(index=False))
    print('total violations:', int(df[[c for c in df if c.endswith('violations')]].to_numpy().sum()),
          '; settings:', len(df), '; windows checked per setting:', len(seg))


if __name__ == '__main__':
    main()
