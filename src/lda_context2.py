"""How good does the task's feedback have to be? Robustness of the labels from the interaction (report 35.16).
PC only, exploratory; continues lda_context.py with less optimistic assumptions.

Stream, model and scoring as lda_context.py (day-1 calibration, day-1 z-score for good, trials in recorded order,
classify a trial, then maybe learn from it; sums fade by 0.97 per learned trial; the first two trials of every
gesture of a block are not scored). What the task can tell is now limited:
  Rest      a trial of Rest gives no feedback when it is classified as Rest (nothing happens). When a gesture is
            classified as Rest nothing happens either (a miss): no label.
  cover c   only a share c of the remaining trials gives any outcome at all
  reveal r  a wrong command (including a false command during Rest) reveals the intended gesture with
            probability r (the user undoes it and the right one follows); otherwise the trial is dropped.
            A right command is always confirmed (label = the command).
  noise e   a label that is given is replaced by a random other gesture with probability e (the task failed for
            another reason, or the outcome was attributed to the wrong trial)
  delay D   the label arrives D trials later (the robot has to finish the movement); the model learns then
  ctx m     the task context names m gestures that make sense now (the intended one + m - 1 others, drawn per
            trial); the classifier chooses among these only. m = 6: no context.
  cue1      one cued pass at the start of every block (first trial of each gesture, labelled, 60 windows) in
            addition to the interaction
Conditions vary one factor at a time around the ideal case (c 1, r 1, e 0, D 0, m 6), plus three combined
'realistic' settings. 3 random seeds. Reference rows `fixed` and `cued_T2` come from results/lda_context.csv.
Writes results/lda_context2.csv, lda_context2_summary.csv.
Usage (container; Kyranou at /data): python src/lda_context2.py [--jobs 19]
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
W, REST, DECAY = LS.ANCHOR_WIN, 5, 0.97
BASE = dict(c=1.0, r=1.0, e=0.0, D=0, m=6, cue=0)
CONDS = {'ideal': {}}
for _r in (0.0, 0.25, 0.5, 0.75):
    CONDS[f'r{_r:g}'] = dict(r=_r)
for _c in (0.5, 0.25):
    CONDS[f'c{_c:g}'] = dict(c=_c)
for _e in (0.1, 0.2, 0.3):
    CONDS[f'e{_e:g}'] = dict(e=_e)
for _d in (3, 10):
    CONDS[f'D{_d}'] = dict(D=_d)
CONDS.update({'m3': dict(m=3), 'm3_r0': dict(m=3, r=0.0), 'm3_r0.5': dict(m=3, r=0.5),
              'cue1_r0': dict(cue=1, r=0.0), 'cue1_r0.5': dict(cue=1, r=0.5),
              'real': dict(c=0.5, r=0.5, e=0.1, D=3), 'real_m3': dict(c=0.5, r=0.5, e=0.1, D=3, m=3),
              'real_cue1': dict(c=0.5, r=0.5, e=0.1, D=3, cue=1),
              'real_m3_cue1': dict(c=0.5, r=0.5, e=0.1, D=3, m=3, cue=1)})
SEEDS = (0, 1, 2)


def learn(mdl, Z, lab):
    mdl.G *= DECAY
    mdl.s *= DECAY
    mdl.n *= DECAY
    mdl.add(Z, np.full(len(Z), lab))
    mdl.fit()


def run(name, Xc_raw, yc, blocks, score_from, cue_blocks, rng):
    p = dict(BASE, **CONDS[name])
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    mdl = LA.OasLDA()
    mdl.add((Xc_raw - mu) / sd, yc)
    mdl.fit()
    queue, rows = [], []
    for b, (X, y) in enumerate(blocks):
        y = np.asarray(y).astype(np.int64)
        Z = (np.asarray(X, dtype=np.float64) - mu) / sd
        a, scored = LG.split(y, [0], 2) if b in score_from else (np.zeros(0, int), np.arange(len(y)))
        smask = np.zeros(len(y), bool)
        smask[scored] = True
        cued = set()
        if p['cue'] and b in cue_blocks:
            a1, _ = LG.split(y, [0], 1)
            for i in sorted(set(a1 // W * W)):
                learn(mdl, Z[i:i + W], int(y[i]))
                cued.add(int(i))
        ok = np.zeros(len(y), bool)
        right = labelled = wrong_lab = 0
        starts = list(range(0, len(y), W))
        for i in starts:
            while queue and queue[0][0] <= 0:                  # labels whose delay is over
                _, Zq, lq = queue.pop(0)
                learn(mdl, Zq, lq)
            queue = [(d - 1, z, l) for d, z, l in queue]
            sl = slice(i, i + W)
            t = int(y[i])
            s = mdl.scores(Z[sl])
            if p['m'] < LS.K:
                allow = np.concatenate([[t], rng.choice([k for k in range(LS.K) if k != t], p['m'] - 1, replace=False)])
                mask = np.full(LS.K, -np.inf)
                mask[allow] = 0.0
                s = s + mask
            pr = np.argmax(s, axis=1)
            ok[sl] = pr == t
            cmd = int(np.argmax(np.bincount(pr, minlength=LS.K)))
            right += cmd == t
            if i in cued or cmd == REST:                       # nothing happened: no outcome
                continue
            if rng.random() >= p['c']:
                continue
            lab = cmd if cmd == t else (t if rng.random() < p['r'] else None)
            if lab is None:
                continue
            if rng.random() < p['e']:
                lab = int(rng.choice([k for k in range(LS.K) if k != lab]))
            labelled += 1
            wrong_lab += lab != t
            if p['D']:
                queue.append((p['D'], Z[sl], lab))
            else:
                learn(mdl, Z[sl], lab)
        rows.append(dict(block=b, acc=ok[smask].mean(), n=int(smask.sum()), cmd_right=right / len(starts),
                         labelled=labelled / len(starts), wrong_labels=wrong_lab))
    return rows


def job_dev(subject, shift):
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    out = []
    for name in CONDS:
        for seed in SEEDS:
            rng = np.random.default_rng(seed * 100003 + subject)
            out += [dict(data='dev', comp=f'shift{shift:g}', subject=subject, seed=seed, cond=name, **r)
                    for r in run(name, Xc_raw, yc, blocks, range(len(blocks)), range(len(blocks)), rng)]
    return out


def job_ext(data, p):
    import external_check as EC
    import leaf_external as LE
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), LS.PREC), None)
    d1 = [EC.Session(data, p, 1, b) for b in (1, 2)]
    d2 = [EC.Session(data, p, 2, b) for b in (1, 2)]
    f, Xc, yc, _ = LE.calibrate(d1[0], p, 0, P.load_pretrain(S.DATASETS['arm_position'][0]))
    if f is None:
        return []
    tests = {'A1': EC.stream(d2, 5, EC.ROW1, 0), 'A2_row2': EC.stream(d1[1:], 5, EC.ROW2, 0)}
    out = []
    for comp, blocks in tests.items():
        for name in CONDS:
            for seed in SEEDS:
                rng = np.random.default_rng(seed * 100003 + p)
                out += [dict(data='ext', comp=comp, subject=p, seed=seed, cond=name, **r)
                        for r in run(name, Xc, yc, blocks, [0], [0], rng)]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--data', default='/data')
    args = ap.parse_args()
    import check_features_c as FC
    import lda_context2 as M
    FC.lib()
    pd.set_option('display.width', 250)
    tasks = [delayed(M.job_dev)(s, sh) for sh in (0.0, 0.5) for s in range(20)]
    tasks += [delayed(M.job_ext)(args.data, p) for p in range(1, 9)]
    res = Parallel(n_jobs=args.jobs, verbose=5)(tasks)
    df = pd.DataFrame([r for rs in res for r in rs])
    df.to_csv(os.path.join(OUT, 'lda_context2.csv'), index=False, float_format='%.4f')
    ref = pd.read_csv(os.path.join(OUT, 'lda_context.csv'))
    ref = ref[ref.cond.isin(['fixed', 'cued_T2'])].copy()
    ref['comp'] = np.where(ref.data == 'dev', 'shift' + ref['shift'].map('{:g}'.format), ref.comp)
    a = pd.concat([df, ref], ignore_index=True)
    a = a[(a.data == 'ext') | (a.block >= 1)].assign(ok=lambda x: x.acc * x.n)
    ps = (a.groupby(['comp', 'cond', 'subject'])[['ok', 'n']].sum().assign(acc=lambda g: g.ok / g.n * 100).acc
          .unstack('cond'))
    lab = df[(df.data == 'ext') | (df.block >= 1)].groupby(['comp', 'cond']).labelled.mean().unstack('cond') * 100
    rows = []
    for comp, g in ps.groupby(level='comp'):
        for c in ['fixed', 'cued_T2'] + list(CONDS):
            d = g[c] - g['cued_T2']
            m, lo, hi = LS.ci(d) if np.any(d != 0) else (0.0, 0.0, 0.0)
            rows.append(dict(comp=comp, cond=c, acc=g[c].mean(), vs_cued=m, lo=lo, hi=hi,
                             worst_vs_fixed=(g[c] - g['fixed']).min(),
                             trials_labelled_pct=lab.loc[comp, c] if c in lab.columns else np.nan))
    sm = pd.DataFrame(rows)
    sm.to_csv(os.path.join(OUT, 'lda_context2_summary.csv'), index=False, float_format='%.4g')
    print(sm.pivot(index='cond', columns='comp', values='acc').loc[['fixed', 'cued_T2'] + list(CONDS)].round(1).to_string())
    print(sm.pivot(index='cond', columns='comp', values='vs_cued').loc[list(CONDS)].round(1).to_string())
    print(sm.pivot(index='cond', columns='comp', values='trials_labelled_pct').loc[list(CONDS)].round(0).to_string())


if __name__ == '__main__':
    main()
