"""Settings of the LDA main line (report 35.11): which start-up sequence, which z-score, and can it reject?
PC only; the model is the MCU form (lda_anchor.OasLDA = src/c/ldacal.c).

Scoring as leaf_guard.py: the first two trials of every gesture of a block are never scored, in any condition, so
all conditions (and the forest conditions taken from results/leaf_guard.csv) are scored on the same windows.
Conditions  <labels>_<anchor>[_<z>]
  labels  r    a new LDA from the current start-up sequence only (ld_reset)
          cum  day-1 calibration + every start-up sequence so far (the sums keep accumulating)
  anchor  T1   first trial of each gesture          T1b  second trial only (first pass = warm-up, not learned)
          T2   first and second trial
  z       (none)  rows z-scored with the current anchor's statistics (as R / LDAr)
          zu      the same, then moved towards the class-balanced statistics of every block's own predictions
                  (no labels, a = 0.3, the firmware's rule with the cls5 guard) for the following block
          zd      day-1 statistics moved towards the anchor's (a = 0.3), as the leaf counters
Rejection (dev base, seed 0, and Kyranou A1): for cum_T1b the LDA posterior of the predicted class (softmax of the
discriminant values) is thresholded; for the fixed one-shot forest F the vote share (the firmware's tau rule).
Per threshold: share of windows accepted and accuracy of the accepted ones, for the 5 active gestures and for Rest.
Writes results/lda_main.csv, lda_main_summary.csv, lda_main_external.csv, lda_main_reject.csv.
Usage (container; Kyranou at /data): python src/lda_main.py [--jobs 19]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lda_anchor as LA  # noqa: E402
import leaf_guard as LG  # noqa: E402
import leaf_sweep as LS  # noqa: E402
import pipeline as P  # noqa: E402
import selfcal_sweep as S  # noqa: E402
import zscore_sweep as ZW  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
CONDS = ['r_T1', 'r_T1b', 'r_T2', 'cum_T1', 'cum_T1b', 'cum_T2', 'cum_T1b_zu', 'cum_T1b_zd', 'cum_T2_zu']
REF = ['F', 'T1_r0.5', 'T1b_r0.5', 'T2_r0.5']
TAUS = np.round(np.concatenate([np.arange(0, 0.9, 0.1), np.arange(0.9, 0.995, 0.01), [0.995, 0.999]]), 3)
REJ = 'cum_T1b'


def run(cond, Xc_raw, yc, blocks, want_post=False):
    """blocks: (Xa, ya, Xu, yu) with the anchor of this condition. Returns rows and, per block, (posterior, pred)"""
    part = cond.split('_')
    labels, z = part[0], (part[2] if len(part) > 2 else '')
    mu0, var0 = Xc_raw.mean(0), Xc_raw.var(0)
    mu, var = mu0.copy(), var0.copy()
    mdl = LA.OasLDA()
    if labels == 'cum':
        mdl.add((Xc_raw - mu0) / np.sqrt(var0), yc)
    rows, post = [], []
    for b, (Xa, ya, Xu, yu) in enumerate(blocks):
        if len(ya):
            if z == 'zd':
                st = ZW.balanced_stats(Xa, ya)
                mu, var = (1 - LS.A_Z) * mu + LS.A_Z * st[0], (1 - LS.A_Z) * var + LS.A_Z * st[1]
            else:
                mu, var = Xa.mean(0), Xa.var(0)
            if labels == 'r':
                mdl = LA.OasLDA()
            mdl.add((Xa - mu) / np.sqrt(var), ya)
            mdl.fit()
        sc = mdl.scores((Xu - mu) / np.sqrt(var))
        pred = np.argmax(sc, axis=1)
        rows.append(dict(block=b, acc=np.mean(pred == yu), n=len(yu)))
        if want_post:
            e = np.exp(sc - sc.max(1, keepdims=True))
            post.append((e.max(1) / e.sum(1), pred))
        if z == 'zu' and LS.guard_ok(pred):
            st = ZW.balanced_stats(Xu, pred)
            if st is not None:
                mu, var = (1 - LS.A_Z) * mu + LS.A_Z * st[0], (1 - LS.A_Z) * var + LS.A_Z * st[1]
    return rows, post


def reject_rows(conf, pred, y, tag):
    out = []
    for grp, m in (('active', y != LS.REST2[0]), ('rest', y == LS.REST2[0])):
        for t in TAUS:
            a = m & (conf >= t)
            out.append(dict(**tag, group=grp, tau=t, n=int(m.sum()), accepted=int(a.sum()),
                            correct=int(np.sum(pred[a] == y[a]))))
    return out


def forest_conf(mdl, Xc_raw, blk):
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    thr, lab0 = LS.thr_q(mdl), P.leaf_labels(mdl)
    conf, pred = [], []
    for _, _, Xu, _ in blk:
        p, v = LS.vote(LS.leaves(mdl, thr, (Xu - mu) / sd), lab0)
        conf.append(v.max(1) / v.sum(1))
        pred.append(p)
    return conf, pred


def job_dev(subject, shift):
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), LS.PREC), None)
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    out, rej = [], []
    for stream in ('base', 'rest2'):
        for cond in CONDS:
            blk = LG.blocks_for(blocks, cond.split('_')[1], 2, range(len(blocks)), stream == 'rest2')
            rows, post = run(cond, Xc_raw, yc, blk, cond == REJ and stream == 'base')
            out += [dict(data='dev', subject=subject, seed=0, shift=shift, stream=stream, cond=cond, **r) for r in rows]
            if post:
                tag = dict(data='dev', comp=f'shift{shift:g}', subject=subject, model='LDA cum_T1b')
                conf = np.concatenate([c for c, _ in post[1:]])
                pred = np.concatenate([p for _, p in post[1:]])
                y = np.concatenate([b[3] for b in blk[1:]])
                rej += reject_rows(conf, pred, y, tag)
                np.random.seed(subject)                                   # seed 0 of leaf_sweep: seed * 1000 + subject
                mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
                f = LS.one_shot((Xc_raw - mu) / sd, yc, P.load_pretrain(S.DATASETS['arm_position'][0]))
                fc, fp = forest_conf(f, Xc_raw, blk)
                rej += reject_rows(np.concatenate(fc[1:]), np.concatenate(fp[1:]), y, dict(tag, model='RF fixed'))
    return out, rej


def job_ext(data, p, seed):
    import external_check as EC
    import leaf_external as LE
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), LS.PREC), None)
    d1 = [EC.Session(data, p, 1, b) for b in (1, 2)]
    d2 = [EC.Session(data, p, 2, b) for b in (1, 2)]
    f, Xc, yc, _ = LE.calibrate(d1[0], p, seed, P.load_pretrain(S.DATASETS['arm_position'][0]))
    if f is None:
        return [], []
    tests = {'A1': EC.stream(d2, 5, EC.ROW1, 0), 'A2_row1': EC.stream(d1[1:], 5, EC.ROW1, 0),
             'A2_row2': EC.stream(d1[1:], 5, EC.ROW2, 0)}
    out, rej = [], []
    for comp, blocks in tests.items():
        for cond in CONDS:
            blk = LG.blocks_for(blocks, cond.split('_')[1], 2, [0])
            rows, post = run(cond, Xc, yc, blk, cond == REJ and comp == 'A1' and seed == 0)
            out += [dict(data='ext', subject=p, seed=seed, comp=comp, cond=cond, **r) for r in rows]
            if post:
                tag = dict(data='ext', comp=comp, subject=p, model='LDA cum_T1b')
                y = np.concatenate([b[3] for b in blk])
                rej += reject_rows(np.concatenate([c for c, _ in post]), np.concatenate([q for _, q in post]), y, tag)
                fc, fp = forest_conf(f, Xc, blk)
                rej += reject_rows(np.concatenate(fc), np.concatenate(fp), y, dict(tag, model='RF fixed'))
    return out, rej


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--data', default='/data')
    args = ap.parse_args()
    import check_features_c as FC
    import lda_main as M
    FC.lib()
    pd.set_option('display.width', 250)
    tasks = [delayed(M.job_dev)(s, sh) for sh in (0.0, 0.5) for s in range(20)]
    tasks += [delayed(M.job_ext)(args.data, p, seed) for p in range(1, 9) for seed in (0, 1, 2)]
    res = Parallel(n_jobs=args.jobs, verbose=5)(tasks)
    df = pd.DataFrame([r for rs, _ in res for r in rs])
    rej = pd.DataFrame([r for _, rs in res for r in rs])
    df.to_csv(os.path.join(OUT, 'lda_main.csv'), index=False, float_format='%.4f')
    g = pd.read_csv(os.path.join(OUT, 'leaf_guard.csv'))
    g = g[g.cond.isin(REF)]
    LG.CONDS = REF + CONDS
    dev = pd.concat([pd.concat([df[df.data == 'dev'].assign(seed=k) for k in (0, 1, 2)]), g[g.data == 'dev']],
                    ignore_index=True)
    sm = LG.summarize(dev)
    sm.to_csv(os.path.join(OUT, 'lda_main_summary.csv'), index=False, float_format='%.4g')
    print(sm.round(2).to_string(index=False))
    ex = LG.summarize_ext(pd.concat([df[df.data == 'ext'], g[g.data == 'ext']], ignore_index=True))
    ex.to_csv(os.path.join(OUT, 'lda_main_external.csv'), index=False, float_format='%.4g')
    print(ex.round(2).to_string(index=False))
    r = rej.groupby(['data', 'comp', 'model', 'group', 'tau'])[['n', 'accepted', 'correct']].sum().reset_index()
    r['coverage'] = r.accepted / r.n * 100
    r['acc_accepted'] = r.correct / r.accepted.clip(lower=1) * 100
    r.to_csv(os.path.join(OUT, 'lda_main_reject.csv'), index=False, float_format='%.4g')
    show = r[r.tau.isin([0.0, 0.5, 0.6, 0.7, 0.9, 0.95, 0.99, 0.999])]
    print(show.pivot_table(index=['data', 'comp', 'group', 'tau'], columns='model', values=['coverage', 'acc_accepted'])
          .round(1).to_string())


if __name__ == '__main__':
    main()
