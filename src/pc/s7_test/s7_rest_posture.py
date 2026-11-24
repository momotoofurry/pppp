# report 35.85 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
"""Would calibrating Rest in the arm postures help? (report 35.85, offline, the firmware's rule in Python)

Baseline = the board's S7 calibration (cued windows, Rest only in the neutral posture). 'posture Rest' = the same plus
the rest periods of the FIRST task segment T1 (postures A, B, C, A; from 0.5 s after rest_on) as extra Rest windows:
what a Rest cue in each posture during the calibration would add. The z-score, the activity gate threshold (gesture
windows only) and everything else are unchanged.
Evaluated only on data after T1 (held out): the rest periods of T2 and the probes P1, P2 (Rest cues and the 1 s after
every cue) -> commands per minute while resting; the S7 non-Rest cues of P1, P2 -> first command right / wrong / none.
Decision as on the board: gate 0.5 x median gesture activity, k 5, stop k 2, one continuous stream.
usage (container): python s7_rest_posture.py --dir /sd/T00 [--days T00_d1_G T00_d2_G] [--max-rest 0]
  --max-rest N: use at most N extra Rest windows (0 = all of T1's rest periods)
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, '/work/src')
import selftest_analysis as SA  # noqa: E402
import selftest9_analysis as S9  # noqa: E402

CL = S9.SETS['S7']
REST = S9.REST
K, KR = 5, 2


def segments(task):
    """per task row the index of its segment (0 P0, 1 T1, 2 P1, 3 T2, 4 P2)"""
    seg, cur = [], -1
    for r in task.itertuples():
        if r.event == 'seg_start':
            cur += 1
        seg.append(cur)
    return np.array(seg)


def run(name, d, max_rest):
    day = S9.load_day(d, name, 4.0, frozenset(CL))
    F, nw = day['F'], len(day['F'])
    folder = S9.day_folder(d, name)
    _, t0, _ = SA.load_emg(os.path.join(folder, f'{name}_emg.csv'))
    task = pd.read_csv(os.path.join(folder, f'{name}_task.csv'), dtype=str, keep_default_na=False)
    task['t'] = task.unix_ms.astype(float)
    task['seg'] = segments(task)
    act = F[:, 32:40].sum(1)
    gl = np.isin(day['cal_lab'], CL) & (day['cal_lab'] != REST)
    thr = np.median(act[day['cal_rows'][gl]])
    gated = act < 0.5 * thr
    # spans
    t1_rest, ho_rest, ho_cues, on, last_off = [], [], [], {}, None
    for r in task.itertuples():
        if r.event == 'rest_on':
            on[('r', r.step, r.seg)] = r
        elif r.event == 'rest_off' and ('r', r.step, r.seg) in on:
            a = on.pop(('r', r.step, r.seg))
            w = SA.inside(t0, nw, a.t + 500, r.t)
            (t1_rest if r.seg == 1 else ho_rest if r.seg == 3 else []).append(w)
        elif r.segment == 'labelled' and r.event == 'cue_on':
            on[('c', r.step, r.seg)] = r
            if last_off is not None and r.seg in (2, 4):
                ho_rest.append(SA.inside(t0, nw, last_off + 500, r.t))
            last_off = None
        elif r.segment == 'labelled' and r.event == 'cue_off' and ('c', r.step, r.seg) in on:
            a = on.pop(('c', r.step, r.seg))
            g = S9.G[r.target]
            if r.seg in (2, 4):
                if g == REST:
                    ho_rest.append(SA.inside(t0, nw, a.t + 500, r.t))
                elif g in CL:
                    ho_cues.append((SA.inside(t0, nw, a.t, r.t + 500), g))
            last_off = r.t if g != REST else None
        elif r.event == 'seg_end':
            last_off = None
    first_eval = min(int(w[0]) for w in ho_rest + [c[0] for c in ho_cues] if len(w))
    extra = np.concatenate([w for w in t1_rest if len(w)])
    if max_rest:
        extra = extra[np.linspace(0, len(extra) - 1, min(max_rest, len(extra))).astype(int)]
    out = {}
    for label, rows, lab in (('neutral Rest (board)', day['cal_rows'], day['cal_lab']),
                             ('+ posture Rest (T1)', np.r_[day['cal_rows'], extra],
                              np.r_[day['cal_lab'], np.full(len(extra), REST)])):
        # the z-score stays the board's (cued windows only); the extra Rest windows only enter the class sums
        base = S9.Model(F, day['cal_rows'], day['cal_lab'], CL)
        if len(rows) > len(day['cal_rows']):
            Zq = base.z(F[extra])
            idx = base.classes.index(REST)
            base.G = base.G + Zq.T @ Zq
            base.s[idx] += Zq.sum(0)
            base.n[idx] += len(extra)
            base.fit()
        top = base.predict(F)
        top[gated] = REST
        # continuous decision from the first evaluated window (the board's latch), commands and their windows
        cmds, last, runn, lat = [], -1, 0, -1
        for i in range(first_eval, nw):
            p = top[i]
            runn = min(runn + 1, max(K, KR)) if p == last else 1
            last = p
            if runn >= (KR if p == REST else K) and p != lat:
                lat = p
                if p != REST:
                    cmds.append((i, p))
        cw = np.array([w for w, _ in cmds])
        cc = np.array([g for _, g in cmds])
        rest_set = np.zeros(nw, bool)
        for w in ho_rest:
            rest_set[w] = True
        fc = int(rest_set[cw].sum()) if len(cw) else 0
        mins = rest_set.sum() * 0.1 / 60
        ok = wr = no = 0
        for w, g in ho_cues:
            sel = (cw >= w[0]) & (cw <= w[-1])
            if not sel.any():
                no += 1
                continue
            j = np.flatnonzero(sel)[0]
            ok += cc[j] == g
            wr += cc[j] != g
        n = ok + wr + no
        out[label] = (fc / mins, 100 * ok / n, 100 * wr / n, 100 * no / n, len(extra) if 'posture' in label else 0, mins, n)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--days', nargs='+', default=['T00_d1_G', 'T00_d2_G'])
    ap.add_argument('--max-rest', type=int, default=0)
    a = ap.parse_args()
    print('held-out data after T1 (T2 rests, P1 / P2): rest commands / min; S7 cues first command right / wrong / none')
    for name in a.days:
        r = run(name, a.dir, a.max_rest)
        for k, (fpm, ok, wr, no, nx, mins, n) in r.items():
            print(f'  {name[4:6]}  {k:<22} rest {fpm:5.2f} / min ({mins:.2f} min)   cues {n}: right {ok:5.1f} %, '
                  f'wrong {wr:4.1f} %, none {no:4.1f} %' + (f'   extra Rest windows {nx}' if nx else ''))


main()
