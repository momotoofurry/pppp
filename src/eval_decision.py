"""Majority smoothing + low-confidence rejection (src/c/decision.c), replayed on the 20 recorded subjects.

1. Votes: for every subject x seed the on-device firmware is run as in check_oneshot_c.py (one-shot calibration
   on the "MCU", then the 11 test blocks streamed through sc_push_votes / sc_end_block) and the votes of the 100
   trees are recorded for every 100 ms window, for the self-calibrated model and for the fixed one-shot model
   (sc_votes_oneshot). Saved to build/decision/votes.npz.
2. Sweep: tau (rejection threshold on the top-vote share) x k (windows that must agree) through the C
   dc_replay(); the state is reset at the start of every trial (the data set holds 1 s per trial: windows
   9..18 of a 2 s recording, so trials are not one continuous stream). Per setting:
     rejected        share of windows below tau
     acc_accepted    accuracy of the top class on the accepted windows
     correct_trial   share of command-gesture trials (Power, Tripod, Pointer, Open) whose first command is
                     the right one
     wrong_per_min   commands that do not match the trial's gesture (any command in a Rest / Lateral trial)
                     per minute of windows (10 windows = 1 s)
     latency_ms      mean time from the trial's first window to its first correct command (correct trials)
   The C decision module is checked against a Python re-implementation on all windows for three settings.
Writes results/decision_sweep.csv, results/decision_check.csv, results/decision_tradeoff.png (English labels: the
image has no CJK font).
The threshold has to be chosen on day-1 data of each user; this only gives the tool and the curves.
Usage (in the container): PYTHONPATH=src python src/eval_decision.py [--seeds 0 1 2]
"""
import argparse
import ctypes
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_oneshot_c as C  # noqa: E402
import pipeline as P  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
VOTES = os.path.join(P.ROOT, 'build', 'decision', 'votes.npz')
TREES = 100
CLASS_CMD = np.array([1, 0, 2, 3, 4, 0])          # decision.c dc_class_command: Power Lateral Tripod Pointer Open Rest
TAUS = [0.0] + [round(t, 2) for t in np.arange(0.30, 0.951, 0.05)]
KS = [1, 2, 3, 4, 5]


def record(subject, seed):
    lib = C.build()
    flash, m, st, _, _keep = C.calibrate(lib, subject, seed)
    out = {k: [] for k in ['votes_sc', 'votes_os', 'y', 'trial']}
    for b in range(P.N_BLOCKS):
        X, y = P.load_folder('arm_position', subject, f'testing_block{b}')
        X = np.ascontiguousarray(X.astype(np.float32))
        vs = np.zeros((len(X), 6), dtype=np.uint16)
        vo = np.zeros((len(X), 6), dtype=np.uint16)
        q = np.zeros(80, dtype=np.int16)
        for i in range(len(X)):
            lib.os_normalize(flash.ctypes.data, X[i].ctypes.data, q.ctypes.data)
            lib.sc_votes_oneshot(q.ctypes.data, vo[i].ctypes.data)
            lib.sc_push_votes(q.ctypes.data, vs[i].ctypes.data)
        lib.sc_end_block(ctypes.byref(C.ScStats()))
        out['votes_sc'].append(vs)
        out['votes_os'].append(vo)
        out['y'].append(y.astype(np.int8))
        out['trial'].append((subject * 10000 + b * 100 + np.arange(len(X)) // 10).astype(np.int32))   # 11 blocks
    return seed, subject, {k: np.concatenate(v) for k, v in out.items()}


def replay(lib, votes, seg, tau, k):
    n = len(votes)
    cmd, acc, est = (np.zeros(n, dtype=np.int8) for _ in range(3))
    v = np.ascontiguousarray(votes, dtype=np.uint16)
    s = np.ascontiguousarray(seg, dtype=np.int32)
    lib.dc_replay(v.ctypes.data, s.ctypes.data, n, TREES, int(round(tau * 1000)), k, cmd.ctypes.data,
                  acc.ctypes.data, est.ctypes.data)
    return cmd, acc.astype(bool), est


def replay_python(votes, seg, tau, k):
    """Reference implementation of decision.c for the check."""
    tp = int(round(tau * 1000))
    cmd = np.zeros(len(votes), dtype=np.int8)
    last, run, latched = -1, 0, -1
    for i, v in enumerate(votes):
        if i > 0 and seg[i] != seg[i - 1]:
            last, run, latched = -1, 0, -1
        top = int(np.argmax(v))
        if int(v[top]) * 1000 < tp * TREES:
            last, run = -1, 0
            continue
        if top == last:
            run = min(run + 1, k)
        else:
            last, run = top, 1
        if run < k or top == latched:
            continue
        latched = top
        cmd[i] = CLASS_CMD[top]
    return cmd


def metrics(votes, y, seg, cmd, acc):
    top = np.argmax(votes, axis=1)
    want = CLASS_CMD[y]
    sent = cmd != 0
    wrong = sent & (cmd != want)
    df = pd.DataFrame(dict(seg=seg, y=y, want=want, cmd=cmd, pos=np.arange(len(seg))))
    first = df[df.cmd != 0].groupby('seg').first()
    trials = df.groupby('seg').agg(want=('want', 'first'), start=('pos', 'first'))
    trials = trials.join(first[['cmd', 'pos']], how='left')
    cmd_trials = trials[trials.want != 0]
    ok = cmd_trials[cmd_trials.cmd == cmd_trials.want]
    return dict(rejected=1 - acc.mean(), acc_accepted=(top[acc] == y[acc]).mean() if acc.any() else np.nan,
                correct_trial=len(ok) / len(cmd_trials), wrong_per_min=wrong.sum() / (len(seg) * 0.1 / 60),
                commands_per_min=sent.sum() / (len(seg) * 0.1 / 60),
                latency_ms=((ok.pos - ok.start + 1) * 100).mean() if len(ok) else np.nan)


def plot(sw, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    ink, muted, grid = '#2b2b29', '#6b6a63', '#e6e5df'
    cols = {'selfcal': '#2a78d6', 'oneshot': '#eb6834'}
    names = {'selfcal': 'after self-calibration', 'oneshot': 'fixed one-shot'}
    kcols = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4']
    marks = ['o', 's', '^', 'D', 'v']
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.6), facecolor='#fcfcfb')
    a = ax[0]
    for model, marker in [('selfcal', 'o'), ('oneshot', 's')]:
        d = sw[(sw.model == model) & (sw.k == 1)].sort_values('tau')
        a.plot(d.rejected * 100, d.acc_accepted * 100, color=cols[model], lw=2, marker=marker, ms=8,
               markeredgecolor='#fcfcfb', label=names[model])
        for _, r in d[d.tau.isin([0.5, 0.7, 0.9])].iterrows():
            a.annotate(f'τ={r.tau:.1f}', (r.rejected * 100, r.acc_accepted * 100), textcoords='offset points',
                       xytext=(8, -14) if model == 'oneshot' else (-34, 8), fontsize=9, color=muted)
    a.set_xlabel('rejected windows (%)', color=ink)
    a.set_ylabel('accuracy of accepted windows (%)', color=ink)
    a.set_title('Low-confidence rejection (k = 1)', color=ink, fontsize=12, loc='left')
    a.legend(frameon=False, loc='lower right')
    a = ax[1]
    d0 = sw[sw.model == 'selfcal']
    for i, k in enumerate(KS):
        d = d0[d0.k == k].sort_values('tau')
        a.plot(d.wrong_per_min, d.correct_trial * 100, color=kcols[i], lw=2, marker=marks[i], ms=8,
               markeredgecolor='#fcfcfb', label=f'k = {k}')
    a.set_xscale('symlog', linthresh=0.1)
    a.set_xlim(left=0)
    a.set_xlabel('wrong commands per minute (symlog)', color=ink)
    a.set_ylabel('command trials with the right first command (%)', color=ink)
    a.set_title('After self-calibration: k and tau (tau grows right to left)', color=ink, fontsize=12, loc='left')
    a.legend(frameon=False, loc='lower right', ncol=2)
    for a in ax:
        a.set_facecolor('#fcfcfb')
        a.grid(color=grid, lw=0.8)
        a.tick_params(colors=muted)
        for sp in ['top', 'right']:
            a.spines[sp].set_visible(False)
        for sp in ['left', 'bottom']:
            a.spines[sp].set_color(grid)
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    args = ap.parse_args()
    lib = C.build()
    import eval_decision as M
    res = Parallel(n_jobs=20, verbose=5)(delayed(M.record)(s, sd) for sd in args.seeds for s in range(20))
    res.sort(key=lambda r: (r[0], r[1]))
    data = {k: np.concatenate([r[2][k] for r in res]) for k in ['votes_sc', 'votes_os', 'y', 'trial']}
    data['seed'] = np.concatenate([np.full(len(r[2]['y']), r[0], dtype=np.int16) for r in res])
    os.makedirs(os.path.dirname(VOTES), exist_ok=True)
    np.savez_compressed(VOTES, **data)
    seg = data['seed'].astype(np.int64) * 1000000 + data['trial']      # trial id unique over seeds
    seg = np.unique(seg, return_inverse=True)[1].astype(np.int32)
    lens = np.bincount(seg)
    assert (lens == 10).all(), 'every trial id must cover exactly its own 10 windows'
    checks = []
    for tau, k in [(0.0, 1), (0.6, 3), (0.8, 5)]:
        c, _, _ = replay(lib, data['votes_sc'], seg, tau, k)
        checks.append(dict(tau=tau, k=k, windows=len(c), identical=bool(np.array_equal(
            c, replay_python(data['votes_sc'], seg, tau, k)))))
    pd.DataFrame(checks).to_csv(os.path.join(OUT, 'decision_check.csv'), index=False)
    print(pd.DataFrame(checks).to_string(index=False))
    rows = []
    for model, key in [('selfcal', 'votes_sc'), ('oneshot', 'votes_os')]:
        for tau in TAUS:
            for k in KS:
                c, acc, _ = replay(lib, data[key], seg, tau, k)
                rows.append(dict(model=model, tau=tau, k=k, **metrics(data[key], data['y'], seg, c, acc)))
    sw = pd.DataFrame(rows)
    sw['windows'] = len(seg)
    sw['minutes'] = len(seg) * 0.1 / 60
    sw.to_csv(os.path.join(OUT, 'decision_sweep.csv'), index=False, float_format='%.5g')
    plot(sw, os.path.join(OUT, 'decision_tradeoff.png'))
    pd.set_option('display.width', 200)
    show = sw[(sw.k.isin([1, 3, 5])) & (sw.tau.isin([0.0, 0.5, 0.6, 0.7, 0.8, 0.9]))]
    print(show.round(4).to_string(index=False))


if __name__ == '__main__':
    main()
