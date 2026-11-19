"""How fast can the arm start and STOP? Ozdemir 2022, 40 people, 4 sensors on targeted muscles (report 35.69).

35.54 swept the board's decision (window, step, k agreeing windows, margin m) for the start. Stopping took longer
(S5: 513 ms from the end of the contraction to Rest), and on the arm a late stop means overshoot (8 cm/s x 0.5 s =
4 cm). Stopping early is safe (the arm only pauses), starting wrong is not, so the stop can use its own, faster rules:

  k_rest   Rest is established after k_rest agreeing Rest windows (other classes still need k)
  gate     amplitude gate on the raw EMG: causal 20 Hz high-pass, RMS over the last G ms per channel, normalised
           pooled over the channels with the cued passes: a = sum_c (rms_c - rest_c) / sum_c (gesture_c - rest_c)
           (rest_c = median of the cued Rest windows, gesture_c = median over the cued gesture windows). The arm
           stops as soon as a < c_off (checked every 25 ms). After a closing, the gate reopens at a >= c_on = 2 c_off
           (hysteresis). After a dip shorter than RESUME (0.3 s) the decision's current command resumes (a short dip
           while holding); after a longer one the arm moves again only when a command is established after the
           reopening. Cheap on the MCU: one running sum of squares per channel.

Same data, features (the board's features.c), model, decision, onset / offset and test stream as latency_sweep.py
--oz (cycles 1-2 cued, cycles 4-5 replayed as one stream).
Metrics per participant (median over participants):
  first_ok, start_ms   as 35.54, with the gate: the first command counts once the gate is open
  stop_ms              offset -> the arm stops (Rest established, or the gate closes)
  cut_tr               stops while the user still holds the gesture (from the first move after onset + 0.3 s to
                       offset - 0.1 s), per trial; long_tr: those longer than RESUME (the arm then waits for a new
                       command); pause_pct: % of that holding time the arm stood still (the cost of a fast stop)
  false_min            commands per minute during rest that would move the arm (with the gate: only while it is open)
Caveat: the offset (ground truth) also comes from a 50 ms RMS threshold (zero-phase, 20 % of rest-to-peak, on the
strongest channel), so the gate's stop latency is partly measured against a similar signal; k_rest is not.

usage: python src/latency_stop.py --oz /oz [--subjects 1-40] [--jobs 8] [--out results/latency]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
import scipy.io as sio
from joblib import Parallel, delayed
from scipy.signal import butter, sosfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import latency_sweep as L  # noqa: E402
import selftest9_analysis as S9  # noqa: E402

FS, REST, OZ, CYCLE0 = L.FS, L.REST, L.OZ, L.CYCLE0
SETS = L.SETS
# start settings: the board now, and 35.54's fastest settings at the same accuracy
STARTS = [(400, 200, 3, 0.0), (200, 100, 4, 1.0), (200, 100, 4, 0.5), (200, 100, 3, 0.5)]
KR = [1, 2, None]                       # None = same as k
GATES = [None] + [(g, c) for g in (50, 100) for c in (0.03, 0.05, 0.1, 0.2)]
GSTEP = 0.025
RESUME = 0.3                            # s: a gate dip shorter than this resumes the decision's command


def replay2(pred, margin, k, m, k_rest):
    """decision.c with all-or-nothing votes, Rest established after k_rest agreeing windows"""
    n = len(pred)
    est = np.full(n, -1, np.int8)
    last, run, latched = -1, 0, -1
    for i in range(n):
        if margin[i] < m:
            last, run = -1, 0
            continue
        t = pred[i]
        if t == last:
            run += 1
        else:
            last, run = t, 1
        need = k_rest if t == REST else k
        if run < need or t == latched:
            continue
        latched = t
        est[i] = t
    return est


def gate_level(X, g_ms):
    """causal 20 Hz high-pass, RMS over the last g_ms per channel, sampled every GSTEP s -> (times, (n, 4))"""
    sos = butter(4, 20, 'highpass', fs=FS, output='sos')
    y = sosfilt(sos, X, axis=0)
    k = int(g_ms / 1000 * FS)
    c = np.cumsum(np.vstack([np.zeros((1, y.shape[1])), y ** 2]), axis=0)
    idx = np.arange(k, len(y) + 1, int(GSTEP * FS))
    rms = np.sqrt((c[idx] - c[idx - k]) / k)
    return idx / FS, rms


def arm_state(est, te, gt, ga, c_off):
    """per gate time: is the arm moving, and with which class. A command moves the arm from its window end until Rest
    is established or the gate closes; after a gate closing it moves again only when a new (or the same) command is
    established while the gate is open."""
    cmd_t = te[est >= 0]
    cmd_c = est[est >= 0]
    j = 0
    cur = REST
    moving = np.zeros(len(gt), bool)
    cls = np.full(len(gt), REST, np.int16)
    c_on = 2 * c_off
    open_ = False
    last_cmd = REST
    new_cmd = None
    closed_at = -1e9
    for i, t in enumerate(gt):
        while j < len(cmd_t) and cmd_t[j] <= t:
            last_cmd = cmd_c[j]
            if ga is None:
                cur = cmd_c[j]
            else:
                new_cmd = cmd_c[j]                              # applied below only while the gate is open
            j += 1
        if ga is not None:
            if open_ and ga[i] < c_off:
                open_ = False
                cur, closed_at = REST, t
            elif not open_ and ga[i] >= c_on:
                open_ = True
                if last_cmd != REST and t - closed_at <= RESUME:
                    cur = last_cmd                              # a brief dip while holding: carry on
            if not open_:
                cur = REST
            elif new_cmd is not None:
                cur = new_cmd
            new_cmd = None
        moving[i] = cur != REST
        cls[i] = cur
    return moving, cls


def subject(path, subj):
    m = sio.loadmat(path)
    X = np.asarray(m['data'], dtype=np.float64)
    if X.shape[0] == 4:
        X = X.T
    env = L.envelope(X)
    X8 = X[:, [0, 1, 2, 3, 0, 1, 2, 3]] * 1e-3
    tr = []
    for cyc in (3, 4):
        for og in range(10):
            t = CYCLE0[cyc] + 10 * og
            tr.append((og, t, L.onset(env, int(t * FS)) if og != 0 else None))
    a_s, b_s = CYCLE0[3] - 2.0, CYCLE0[4] + 100.0
    # gate calibration on the cued passes (cycles 1-2): rest = the Rest gesture, gesture = all other gestures
    lv = {}
    for g in (50, 100):
        gt, rms = gate_level(X, g)
        rest_w, ges_w = [], []
        for og in OZ:
            for cyc in (0, 1):
                t = CYCLE0[cyc] + 10 * og
                w = (gt >= t + 1.0) & (gt <= t + 4.2)
                (rest_w if og == 0 else ges_w).append(rms[w])
        r0 = np.median(np.vstack(rest_w), 0)
        g0 = np.median(np.vstack(ges_w), 0)
        a = (rms - r0).sum(1) / max(float((g0 - r0).sum()), 1e-12)     # pooled over the channels
        lv[g] = (gt, a)
    rows = []
    for win, step, k, mth in STARTS:
        F = L.features(X8, win, step)
        st = np.arange(len(F)) * step / FS
        te = st + win / FS
        cal_r, cal_l = [], []
        for og, c in OZ.items():
            for cyc in (0, 1):
                t = CYCLE0[cyc] + 10 * og
                w = np.flatnonzero((st >= t + 1.0) & (te <= t + 4.2))
                cal_r.append(w)
                cal_l.append(np.full(len(w), c))
        cal_r, cal_l = np.concatenate(cal_r), np.concatenate(cal_l)
        sw = np.flatnonzero((st >= a_s) & (te <= b_s))
        for sname, cls in SETS.items():
            mdl = S9.Model(F, cal_r, cal_l, cls)
            sc = mdl.scores(F[sw])
            o = np.sort(sc, 1)
            margin = o[:, -1] - o[:, -2]
            pred = np.array(cls)[np.argmax(sc, 1)]
            trials, busy = [], []
            for og, t, r in tr:
                c = OZ.get(og)
                if og == 0:
                    continue
                if r is None:
                    busy.append((t - 1.0, t + 9.0))
                    continue
                on, off = r[0] / FS, (r[1] / FS if r[1] is not None else t + 6.5)
                busy.append((on - 0.5, off + 1.5))
                if c is not None and c in cls:
                    trials.append((c, on, off))
            rest_iv, cur = [], a_s + 1.0
            for a, b in sorted(busy):
                if a > cur:
                    rest_iv.append((cur, a))
                cur = max(cur, b)
            if b_s - 0.5 > cur:
                rest_iv.append((cur, b_s - 0.5))
            for kr in KR:
                est = replay2(pred, margin, k, mth, k if kr is None else kr)
                for gate in GATES:
                    if gate is None:
                        gt = np.arange(a_s, b_s, GSTEP)
                        ga, c_off = None, 0
                    else:
                        gt_all, a_all = lv[gate[0]]
                        sel = (gt_all >= a_s) & (gt_all < b_s)
                        gt, ga, c_off = gt_all[sel], a_all[sel], gate[1]
                    moving, mcls = arm_state(est, te[sw], gt, ga, c_off)
                    first_ok = miss = 0
                    start, stop, cuts, longc, hold_n, hold_stop = [], [], 0, 0, 0, 0
                    for c, on, off in trials:
                        sel = (gt >= on - 0.2) & (gt <= off + 1.0)
                        mv = moving[sel] & (mcls[sel] != REST)
                        if not mv.any():
                            miss += 1
                            continue
                        i0 = np.flatnonzero(mv)[0]
                        if mcls[sel][i0] == c:
                            first_ok += 1
                            start.append((gt[sel][i0] - on) * 1000)
                        after = (gt > off) & ~moving
                        if after.any():
                            stop.append((gt[after][0] - off) * 1000)
                        hold = (gt >= on + 0.3) & (gt <= off - 0.1)
                        h = moving[hold]
                        if len(h) > 1 and h.any():
                            h = h[np.flatnonzero(h)[0]:]               # from the first move in the hold on
                            cuts += int(((h[:-1]) & (~h[1:])).sum())
                            hold_n += len(h)
                            hold_stop += int((~h).sum())
                            # pauses longer than RESUME (the arm stays stopped until a new command)
                            run = 0
                            for v in h:
                                run = run + 1 if not v else 0
                                if run == int(round(RESUME / GSTEP)) + 1:
                                    longc += 1
                    nt = len(trials)
                    rest_s = sum(b - a for a, b in rest_iv)
                    fals = 0
                    for a, b in rest_iv:
                        w = (gt >= a) & (gt < b)
                        mvr = moving[w]
                        fals += int(((~mvr[:-1]) & mvr[1:]).sum()) if len(mvr) > 1 else 0
                    md = lambda v: float(np.median(v)) if len(v) else np.nan  # noqa: E731
                    rows.append(dict(subject=subj, set=sname, win_ms=win / 2, step_ms=step / 2, k=k, m=mth,
                                     k_rest=k if kr is None else kr,
                                     gate='none' if gate is None else f'{gate[0]}ms c{gate[1]}',
                                     first_ok=100 * first_ok / nt, start_ms=md(start), stop_ms=md(stop),
                                     cut_tr=cuts / nt, long_tr=longc / nt,
                                     pause_pct=100 * hold_stop / max(hold_n, 1), false_min=60 * fals / rest_s))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--oz', required=True)
    ap.add_argument('--subjects', default='1-40')
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--out')
    a = ap.parse_args()
    lo, hi = (a.subjects.split('-') + [None])[:2]
    subs = list(range(int(lo), int(hi or lo) + 1))
    paths = [(os.path.join(a.oz, f'{s}_raw.mat'), s) for s in subs]
    paths = [(p_, s) for p_, s in paths if os.path.exists(p_)]
    for win, step, _, _ in STARTS:
        L.fe_build(win, step)                     # compile once before the workers start
    res = Parallel(n_jobs=a.jobs)(delayed(subject)(p_, s) for p_, s in paths)
    df = pd.DataFrame([r for rows in res for r in rows])
    key = ['set', 'win_ms', 'step_ms', 'k', 'm', 'k_rest', 'gate']
    s = df.groupby(key)[['first_ok', 'start_ms', 'stop_ms', 'cut_tr', 'long_tr', 'pause_pct', 'false_min']].median().reset_index()
    lines = []

    def p(x=''):
        print(x, flush=True)
        lines.append(x)

    p(f'Ozdemir 2022, {len(paths)} participants; median over participants. Start settings x stop rules.')
    for sname in SETS:
        p(f'\n===== {sname}')
        p('  win step k   m  k_rest  gate        | first_ok  start_ms  stop_ms  cut/tr  long/tr  pause%  false/min')
        d = s[s.set == sname].sort_values(['win_ms', 'step_ms', 'k', 'm', 'k_rest', 'gate'])
        for r in d.itertuples():
            p(f'  {r.win_ms:3.0f} {r.step_ms:4.0f} {r.k} {r.m:3.1f}  {r.k_rest:5d}   {r.gate:11s} | {r.first_ok:8.1f} '
              f'{r.start_ms:9.0f} {r.stop_ms:8.0f} {r.cut_tr:7.2f} {r.long_tr:8.2f} {r.pause_pct:7.1f} {r.false_min:10.2f}')
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        df.to_csv(os.path.join(a.out, 'latency_stop_rows.csv'), index=False)
        open(os.path.join(a.out, 'latency_stop.txt'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
