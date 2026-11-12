"""Labels from the interaction instead of a cued start-up sequence (report 35.15): a first look, PC only.

Idea for a robot-centred direction: when the gesture drives a robot, the task tells afterwards whether a command
was the intended one (the object was grasped, the user did not undo it). That is a label the user never has to give.
Simulation on recorded data (model = lda_anchor.OasLDA, the MCU form):
  day 1   the labelled calibration (60 windows), as always; features stay in the day-1 z-score for good, so all
          sums live in one coordinate system and the adaptation happens in the classifier
  later   no cued sequence. Trials arrive in recorded order; a trial (10 windows) is classified with the current
          model; its command = the majority class of its windows. Then the model may learn from the trial:
  fixed     never                                                 (the day-1 shrinkage LDA)
  self      label = the command itself, always                    (plain self-training, no outcome signal)
  pos       label = the command, only if it was the intended one  (the task succeeded; failures are discarded)
  all       label = the intended gesture, always                  (failures are corrected by the user and the robot
                                                                   learns what was meant: the most the task can tell)
  ..._d97   the sums are multiplied by 0.97 before every trial that is learned (old sessions fade)
  cued_T2   reference: the cued two-pass start-up sequence of every block, accumulated (cum_T2 of lda_main.py)
The model is refitted after every learned trial. Scoring as leaf_guard.py: the first two trials of every gesture
of a block are not scored in any condition (the interaction conditions still classify and learn from them), dev
blocks 1..10. Kyranou A1 (day 2, re-donned), A2_row2 (the other electrode ring): all windows after those trials.
This is an optimistic simulation: the outcome is assumed to be known for every trial, immediately and without
error; steady-state windows only.
Writes results/lda_context.csv, lda_context_summary.csv, lda_context_external.csv.
Usage (container; Kyranou at /data): python src/lda_context.py [--jobs 19]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lda_anchor as LA  # noqa: E402
import lda_main as LM  # noqa: E402
import leaf_guard as LG  # noqa: E402
import leaf_sweep as LS  # noqa: E402
import pipeline as P  # noqa: E402
import selfcal_sweep as S  # noqa: E402
import zscore_sweep as ZW  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
CONDS = ['fixed', 'self', 'pos', 'all', 'self_d97', 'pos_d97', 'all_d97']
W = LS.ANCHOR_WIN


def run(cond, Xc_raw, yc, blocks, n_out, score_from):
    """blocks: list of (X raw, y) in recorded order. Returns per block: accuracy on the scored windows, share of
    trials whose command was right, trials learned"""
    rule, decay = cond.split('_')[0], (0.97 if cond.endswith('_d97') else 1.0)
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    mdl = LA.OasLDA()
    mdl.add((Xc_raw - mu) / sd, yc)
    mdl.fit()
    rows = []
    for b, (X, y) in enumerate(blocks):
        y = np.asarray(y).astype(np.int64)
        Z = (np.asarray(X, dtype=np.float64) - mu) / sd
        _, scored = LG.split(y, [0], n_out) if b in score_from else (None, np.arange(len(y)))
        smask = np.zeros(len(y), bool)
        smask[scored] = True
        ok = np.zeros(len(y), bool)
        right = learned = 0
        starts = list(range(0, len(y), W))
        for i in starts:
            sl = slice(i, i + W)
            assert np.all(y[sl] == y[i])
            p = mdl.predict(Z[sl])
            ok[sl] = p == y[i]
            cmd = int(np.argmax(np.bincount(p, minlength=LS.K)))
            right += cmd == y[i]
            lab = None
            if rule == 'self':
                lab = cmd
            elif rule == 'pos' and cmd == y[i]:
                lab = cmd
            elif rule == 'all':
                lab = int(y[i])
            if lab is not None:
                mdl.G *= decay
                mdl.s *= decay
                mdl.n *= decay
                mdl.add(Z[sl], np.full(W, lab))
                mdl.fit()
                learned += 1
        rows.append(dict(block=b, acc=ok[smask].mean(), n=int(smask.sum()), cmd_right=right / len(starts),
                         learned=learned))
    return rows


def job_dev(subject, shift):
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    out = []
    for cond in CONDS:
        out += [dict(data='dev', subject=subject, seed=0, shift=shift, stream='base', cond=cond, **r)
                for r in run(cond, Xc_raw, yc, blocks, 2, range(len(blocks)))]
    blk = LG.blocks_for(blocks, 'T2', 2, range(len(blocks)))
    rows, _ = LM.run('cum_T2', Xc_raw, yc, blk)
    out += [dict(data='dev', subject=subject, seed=0, shift=shift, stream='base', cond='cued_T2', **r) for r in rows]
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
        for cond in CONDS:
            out += [dict(data='ext', subject=p, seed=0, comp=comp, cond=cond, **r)
                    for r in run(cond, Xc, yc, blocks, 2, [0])]
        rows, _ = LM.run('cum_T2', Xc, yc, LG.blocks_for(blocks, 'T2', 2, [0]))
        out += [dict(data='ext', subject=p, seed=0, comp=comp, cond='cued_T2', **r) for r in rows]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    ap.add_argument('--data', default='/data')
    args = ap.parse_args()
    import check_features_c as FC
    import lda_context as M
    FC.lib()
    pd.set_option('display.width', 250)
    tasks = [delayed(M.job_dev)(s, sh) for sh in (0.0, 0.5) for s in range(20)]
    tasks += [delayed(M.job_ext)(args.data, p) for p in range(1, 9)]
    res = Parallel(n_jobs=args.jobs, verbose=5)(tasks)
    df = pd.DataFrame([r for rs in res for r in rs])
    df.to_csv(os.path.join(OUT, 'lda_context.csv'), index=False, float_format='%.4f')
    allc = CONDS + ['cued_T2']
    rows = []
    d = df[(df.data == 'dev') & (df.block >= 1)]
    ps = (d.groupby(['shift', 'cond', 'subject']).acc.mean() * 100).unstack('cond')
    cr = (d.groupby(['shift', 'cond', 'subject']).cmd_right.mean() * 100).unstack('cond')
    for sh, g in ps.groupby(level=0):
        for c in allc:
            dd = g[c] - g['fixed']
            m, lo, hi = LS.ci(dd) if np.any(dd != 0) else (0.0, 0.0, 0.0)
            rows.append(dict(shift=sh, cond=c, acc=g[c].mean(), vs_fixed=m, lo=lo, hi=hi, worst=dd.min(),
                             worse=int((dd < 0).sum()), commands_right=cr.loc[sh][c].mean() if c in cr else np.nan))
    sm = pd.DataFrame(rows)
    sm.to_csv(os.path.join(OUT, 'lda_context_summary.csv'), index=False, float_format='%.4g')
    print(sm.round(2).to_string(index=False))
    late = df[(df.data == 'dev') & (df.block >= 6)].groupby(['shift', 'cond']).acc.mean().unstack('cond') * 100
    print('blocks 6..10 only:')
    print(late[allc].round(2).to_string())
    e = df[df.data == 'ext'].assign(ok=lambda x: x.acc * x.n)
    acc = (e.groupby(['comp', 'cond', 'subject'])[['ok', 'n']].sum().assign(acc=lambda g: g.ok / g.n * 100)
           .acc.unstack('cond'))
    rows = []
    for comp, g in acc.groupby(level='comp'):
        for c in allc:
            dd = g[c] - g['fixed']
            m, lo, hi = LS.ci(dd) if np.any(dd != 0) else (0.0, 0.0, 0.0)
            rows.append(dict(comp=comp, cond=c, acc=g[c].mean(), vs_fixed=m, lo=lo, hi=hi, worst=dd.min(),
                             worse=int((dd < 0).sum())))
    ex = pd.DataFrame(rows)
    ex.to_csv(os.path.join(OUT, 'lda_context_external.csv'), index=False, float_format='%.4g')
    print(ex.round(2).to_string(index=False))


if __name__ == '__main__':
    main()
