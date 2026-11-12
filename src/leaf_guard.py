"""Protection for the anchor counters (report 35.8): can the worst case right after learning the start-up sequence be
avoided without giving up the gain? Exploratory PC prototype; the C module leafcal.c is not changed.

Report 35.7: with the leafcal.c rule (prior r = 0.5 anchor windows) a few subjects lose up to 16 points in the block
the anchor comes from, and a stronger prior only helps by giving up most of the gain. Mechanisms tried here (all
use only the labelled start-up sequence itself, all are a few lines on top of lc_votes / lc_learn):
  T1_r<r>        current rule: every window of the anchor is learned (= LAonly_r<r>_za of leaf_sweep.py)
  E_r<r>         error-driven, batch: learn only the anchor windows that the model before this anchor classifies wrong
  Es_r<r>        error-driven, sequential (as the device would run it): windows in recorded order; lc_votes, and
                 lc_learn only if wrong with the counters learned so far
  Ms_r<r>        as Es, but also learn when right with a top vote share below 0.6 (the decision threshold tau)
  G80_r<r>       per gesture: learn its windows only if the model before this anchor gets < 80 % of them right
  T2_r<r>        a longer sequence: the first TWO trials of every gesture (twice the user's time)
  T2Es_r<r>      T2 with the sequential error-driven rule
  T1b_r<r>       diagnostic: the second trial of every gesture instead of the first (is the first trial atypical?)
All conditions also move the z-score towards the anchor's class-balanced statistics (all anchor windows) and update
it after each block as leaf_sweep.run_anchor. Scoring: the first two trials of every gesture of a block are never
scored (in every condition, F included), so all conditions are scored on the same windows.
Data: development (arm_position 20 x 3 seeds, shifts 0 / 0.5, streams base / rest2; one anchor per block, as
leaf_sweep.py) and Kyranou 2025 (8 x 3 seeds, A1 / A2_row1 / A2_row2; one anchor at the start of the stream; only a
consistency check). Thresholds (0.6, 80 %) were fixed before running, not tuned.
--check: T1_r0.5 with leaf_sweep's scoring (first trial removed only) must equal LAonly_r0.5_za in leaf_sweep.csv.
Writes results/leaf_guard.csv, leaf_guard_summary.csv, leaf_guard_external.csv.
Usage (container; Kyranou at /data): python src/leaf_guard.py [--check] [--jobs 19]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leaf_sweep as LS  # noqa: E402
import pipeline as P  # noqa: E402
import selfcal_sweep as S  # noqa: E402
import zscore_sweep as ZW  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
TAU = 0.6
G_ACC = 0.8
CONDS = ['F', 'T1_r0.5', 'T1_r1.5', 'E_r0.5', 'Es_r0.5', 'Es_r1.5', 'Ms_r0.5', 'G80_r0.5', 'T2_r0.5', 'T2Es_r0.5',
         'T1b_r0.5']


def trials(y, c):
    """window indices of the trials of class c in recorded order (10 consecutive windows each)"""
    idx = np.flatnonzero(y == c)
    out, cur = [], [idx[0]]
    for i in idx[1:]:
        if i == cur[-1] + 1 and len(cur) < LS.ANCHOR_WIN:
            cur.append(i)
        else:
            out.append(cur)
            cur = [i]
    out.append(cur)
    assert all(len(t) == LS.ANCHOR_WIN for t in out), [len(t) for t in out]
    return out


def split(y, which, n_out):
    """anchor indices (trials `which` of every gesture, recorded order) and scored indices (all but the first n_out
    trials of every gesture)"""
    a, drop = [], []
    for c in range(LS.K):
        tr = trials(y, c)
        a += [i for k in which for i in tr[k]]
        drop += [i for k in range(n_out) for i in tr[k]]
    return np.sort(np.array(a)), np.setdiff1d(np.arange(len(y)), drop)


def run_guard(cond, mdl, Xc_raw, blocks):
    """blocks: (Xa, ya, Xu, yu) with the anchor already chosen for this condition"""
    rule, r = cond.split('_r')[0], float(cond.split('_r')[1])
    rule = {'T1': 'all', 'T2': 'all', 'T1b': 'all', 'T2Es': 'Es'}.get(rule, rule)
    mu, var = Xc_raw.mean(0), Xc_raw.var(0)
    thr = LS.thr_q(mdl)
    lab0 = P.leaf_labels(mdl)
    off = np.concatenate([[0], np.cumsum([len(x) for x in lab0])])[:-1]
    base = np.concatenate(lab0)
    lab = base.copy()
    cnt = np.zeros((len(base), LS.K))

    def route(X):
        return np.stack(LS.leaves(mdl, thr, (X - mu) / np.sqrt(var)), axis=1) + off

    def votes(G):
        v = np.zeros((len(G), LS.K), dtype=np.int64)
        np.add.at(v, (np.arange(len(G))[:, None], lab[G]), 1)
        return v

    def relabel(g):
        score = cnt[g].copy()
        score[np.arange(len(g)), base[g]] += r
        lab[g] = np.argmax(score, axis=1)

    rows = []
    for b, (Xa, ya, Xu, yu) in enumerate(blocks):
        learned = 0
        if len(ya):
            st = ZW.balanced_stats(Xa, ya)
            mu = (1 - LS.A_Z) * mu + LS.A_Z * st[0]
            var = (1 - LS.A_Z) * var + LS.A_Z * st[1]
            Ga = route(Xa)
            if rule in ('all', 'E', 'G80'):
                v = votes(Ga)
                pa = np.argmax(v, axis=1)
                if rule == 'all':
                    m = np.ones(len(ya), bool)
                elif rule == 'E':
                    m = pa != ya
                else:
                    m = np.zeros(len(ya), bool)
                    for c in range(LS.K):
                        mc = ya == c
                        if mc.any() and np.mean(pa[mc] == c) < G_ACC:
                            m |= mc
                np.add.at(cnt, (Ga[m], ya[m][:, None]), 1.0)
                relabel(np.unique(Ga[m]))
                learned = int(m.sum())
            else:                                                    # sequential: Es, Ms
                for g, c in zip(Ga, ya):
                    v = np.bincount(lab[g], minlength=LS.K)
                    p = int(np.argmax(v))
                    if p != c or (rule == 'Ms' and v[p] < TAU * len(g)):
                        np.add.at(cnt, (g, c), 1.0)
                        relabel(g)
                        learned += 1
        G = route(Xu)
        pred = np.argmax(votes(G), axis=1)
        rows.append(dict(block=b, acc=np.mean(pred == yu), n=len(yu), learned=learned,
                         flipped=int(np.sum(lab != base))))
        if LS.guard_ok(pred):
            st = ZW.balanced_stats(Xu, pred)
            if st is not None:
                mu = (1 - LS.A_Z) * mu + LS.A_Z * st[0]
                var = (1 - LS.A_Z) * var + LS.A_Z * st[1]
    return rows


def anchor_of(cond):
    return [0, 1] if cond.startswith('T2') else [1] if cond.startswith('T1b') else [0]


def blocks_for(blocks, cond, n_out, anchor_blocks, rest2=False):
    out = []
    for b, (X, y) in enumerate(blocks):
        X, y = np.asarray(X, dtype=np.float64), np.asarray(y).astype(np.int64)
        a, u = split(y, anchor_of(cond), n_out)
        if b not in anchor_blocks:
            a = np.zeros(0, dtype=np.int64)
            if b > 0:
                u = np.arange(len(y))
        if rest2 and b > 0:
            u = u[np.isin(y[u], LS.REST2)]
        out.append((X[a], y[a], X[u], y[u]))
    return out


def run_cond(cond, mdl, Xc_raw, blk):
    if cond == 'F':
        return LS.run_static('F', mdl, Xc_raw, blk)
    return run_guard(cond, mdl, Xc_raw, blk)


def job_dev(subject, seed, shift, n_out, conds):
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), LS.PREC), None)
    np.random.seed(seed * 1000 + subject)
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    mdl = LS.one_shot((Xc_raw - mu) / sd, yc, P.load_pretrain(S.DATASETS['arm_position'][0]))
    out = []
    for stream in ('base', 'rest2'):
        for cond in conds:
            blk = blocks_for(blocks, cond, n_out, range(len(blocks)), stream == 'rest2')
            out += [dict(data='dev', subject=subject, seed=seed, shift=shift, stream=stream, cond=cond, **r)
                    for r in run_cond(cond, mdl, Xc_raw, blk)]
    return out


def job_ext(data, p, seed, conds):
    import external_check as EC
    import leaf_external as LE
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), LS.PREC), None)
    d1 = [EC.Session(data, p, 1, b) for b in (1, 2)]
    d2 = [EC.Session(data, p, 2, b) for b in (1, 2)]
    pre = P.load_pretrain(S.DATASETS['arm_position'][0])
    mdl, Xc, yc, _ = LE.calibrate(d1[0], p, seed, pre)
    if mdl is None:
        return []
    tests = {'A1': EC.stream(d2, 5, EC.ROW1, 0), 'A2_row1': EC.stream(d1[1:], 5, EC.ROW1, 0),
             'A2_row2': EC.stream(d1[1:], 5, EC.ROW2, 0)}
    out = []
    for comp, blocks in tests.items():
        for cond in conds:
            blk = blocks_for(blocks, cond, 2, [0])
            out += [dict(data='ext', subject=p, seed=seed, comp=comp, cond=cond, **r)
                    for r in run_cond(cond, mdl, Xc, blk)]
    return out


def summarize(df):
    rows = []
    cell = df.groupby(['shift', 'stream', 'cond', 'subject', 'block']).acc.mean().unstack('cond') * 100
    for (sh, st), g in cell.groupby(level=[0, 1]):
        later = g[g.index.get_level_values('block') >= 1].groupby(level='subject').mean()
        b0 = g[g.index.get_level_values('block') == 0].groupby(level='subject').mean()
        for c in [x for x in CONDS if x in g]:
            d, d0 = later[c] - later.F, b0[c] - b0.F
            m, lo, hi = LS.ci(d) if np.any(d != 0) else (0.0, 0.0, 0.0)
            m0, lo0, hi0 = LS.ci(d0) if np.any(d0 != 0) else (0.0, 0.0, 0.0)
            rows.append(dict(shift=sh, stream=st, cond=c, acc=later[c].mean(), vsF=m, vsF_lo=lo, vsF_hi=hi,
                             worst=d.min(), block0_vsF=m0, block0_lo=lo0, block0_hi=hi0, block0_worst=d0.min(),
                             harm_cells_pct=float(np.mean((g[c] - g.F) < -5) * 100)))
    return pd.DataFrame(rows)


def summarize_ext(df):
    df = df.assign(ok=df.acc * df.n)
    acc = (df.groupby(['comp', 'cond', 'subject', 'seed'])[['ok', 'n']].sum().assign(acc=lambda g: g.ok / g.n * 100)
           .groupby(['comp', 'cond', 'subject']).acc.mean().unstack('cond'))
    rows = []
    for comp, g in acc.groupby(level='comp'):
        for c in [x for x in CONDS if x in g]:
            d = g[c] - g.F
            m, lo, hi = LS.ci(d) if np.any(d != 0) else (0.0, 0.0, 0.0)
            rows.append(dict(comp=comp, cond=c, acc=g[c].mean(), vsF=m, vsF_lo=lo, vsF_hi=hi, worst=d.min(),
                             worse=int((d < 0).sum())))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--data', default='/data')
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()
    import check_features_c as FC
    import leaf_guard as M
    FC.lib()
    pd.set_option('display.width', 250)
    if args.check:
        res = Parallel(n_jobs=args.jobs)(delayed(M.job_dev)(s, 0, 0.0, 1, ['T1_r0.5']) for s in range(20))
        mine = pd.DataFrame([r for rs in res for r in rs])
        ref = pd.read_csv(os.path.join(OUT, 'leaf_sweep.csv'))
        ref = ref[(ref.cond == 'LAonly_r0.5_za') & (ref.seed == 0) & (ref['shift'] == 0)]
        m = mine.merge(ref, on=['subject', 'stream', 'block'], suffixes=('', '_ref'))
        print(f'check: {len(m)} blocks, max |acc - leaf_sweep| = {np.max(np.abs(m.acc - m.acc_ref)):.2e}')
        return
    tasks = [delayed(M.job_dev)(s, seed, sh, 2, CONDS) for sh in (0.0, 0.5) for seed in (0, 1, 2) for s in range(20)]
    tasks += [delayed(M.job_ext)(args.data, p, seed, CONDS) for p in range(1, 9) for seed in (0, 1, 2)]
    res = Parallel(n_jobs=args.jobs, verbose=5)(tasks)
    df = pd.DataFrame([r for rs in res for r in rs])
    df.to_csv(os.path.join(OUT, 'leaf_guard.csv'), index=False, float_format='%.4f')
    sm = summarize(df[df.data == 'dev'])
    sm.to_csv(os.path.join(OUT, 'leaf_guard_summary.csv'), index=False, float_format='%.4g')
    ex = summarize_ext(df[df.data == 'ext'])
    ex.to_csv(os.path.join(OUT, 'leaf_guard_external.csv'), index=False, float_format='%.4g')
    print(sm.round(2).to_string(index=False))
    print(ex.round(2).to_string(index=False))
    ln = df[df.data == 'dev'].groupby('cond').learned.mean()
    print('anchor windows learned per block (dev mean):', ln.round(1).to_dict())


if __name__ == '__main__':
    main()
