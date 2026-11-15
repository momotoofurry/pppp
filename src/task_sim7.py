"""Soft-label forms on the closed-loop task simulation (report 35.41). PC only.

Why: Campbell's PhD thesis (UNB 2026, ch. 4 = Campbell et al. 2024 TNSRE) already uses SOFT context labels: when the
context is negative, the pseudo-label is split EQUALLY over the context-eligible options (e.g. 0.5 / 0.5), then refined
by label spreading over a growing kNN memory bank (which the author notes does not suit embedded devices). So "soft
labels" alone is not new; what this thesis adds is the task prior MULTIPLIED by the classifier's own scores, learned in
closed form into fixed-size LDA running sums. This script asks whether the classifier-score factor matters.
Same world, data, users and wrong-label stream as task_sim4.py (it reuses task_sim4.session with three extra label
modes; everything else is unchanged). All with one cued pass (8 s), activity gate on.
  cue1_soft   this thesis (task_sim2): q ~ prior * exp(beta (s - max s)), beta 0.3, prior 0.85 / eps shared / rest 0.05
  cue1_prior  the same prior with beta = 0 (no classifier factor): isolates what the scores add
  cue1_avg    Campbell ch. 4 adapted to running sums: if the decoded gesture equals the expected one (positive context),
              learn it as a hard label (P-CIIL); otherwise split the label equally over the eligible gestures (the
              expected one + the other gestures valid at that moment). No label spreading (it needs a memory bank).
  cue1_pn     P+N-CIIL (hard), cue1_pos P-CIIL, cue1 (no task labels): references, as in task_sim4.
Wrong task labels e = 0, 0.1, 0.2, 0.3 exactly as task_sim4 (the expected gesture is replaced by a random other one).
Decision rules, fixed before running (shift 0.5, probe accuracy, blocks 1-10, per subject, 20 subjects x 2 seeds
averaged per subject, paired 95 % CI):
  R14 "multiplying by the classifier scores matters" only if cue1_soft - cue1_avg >= +1 point with CI above 0 at
      e = 0.3, and >= -0.5 at e = 0. Otherwise the thesis claims only the fixed-memory closed-form soft update (and
      the robot / per-donning / MCU parts), and reports the equal-split form as equivalent.
  R15 report cue1_soft - cue1_prior at each e (what the score factor adds over the prior alone); no verdict.
Writes results/task_sim7.csv and task_sim7_summary.csv.
Usage (in the container): python src/task_sim7.py [--jobs 19]
"""
import argparse
import inspect
import os
import sys
import textwrap

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leaf_sweep as LS  # noqa: E402
import pipeline as P  # noqa: E402
import task_sim as T  # noqa: E402
import task_sim2 as T2  # noqa: E402
import task_sim4 as T4  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
ERRS = T4.ERRS

# task_sim4.session with two more label modes, inserted before its soft branch (source otherwise unchanged)
_SRC = textwrap.dedent(inspect.getsource(T4.session))
_OLD = "            else:                                         # soft, as task_sim2\n"
_NEW = ("            elif mode == 'avg':                           # Campbell ch. 4: hard if positive, equal split if negative\n"
        "                if pred == exp:\n"
        "                    put(Z, pred, true)\n"
        "                else:\n"
        "                    elig = [exp] + [c for c in range(5) if valid[c] and c != exp]\n"
        "                    q = np.zeros(LS.K)\n"
        "                    q[elig] = 1.0 / len(elig)\n"
        "                    st['labels'] += 1\n"
        "                    st['wrong_labels'] += int(np.argmax(q) != true)\n"
        "                    T2.learn_soft(mdl.m, Z, q)\n"
        + _OLD)
assert _SRC.count(_OLD) == 1
_ns = dict(vars(T4))
exec(compile(_SRC.replace(_OLD, _NEW), T4.__file__ + ':session+avg', 'exec'), _ns)
session = _ns['session']

CONDS = [('cue1', dict(act=True, cue=1), 0.0)]
for _e in ERRS:
    CONDS += [('cue1_soft', dict(act=True, cue=1, labels='soft'), _e),
              ('cue1_prior', dict(act=True, cue=1, labels='soft', beta=0.0), _e),
              ('cue1_avg', dict(act=True, cue=1, labels='avg'), _e),
              ('cue1_pn', dict(act=True, cue=1, labels='hard'), _e),
              ('cue1_pos', dict(act=True, cue=1, labels='pos'), _e)]


def job(subject, shift, p_dev, seed):
    """task_sim4.job, restricted to CONDS and calling the session above"""
    import zscore_sweep as ZW
    import leaf_guard as LG
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    Zc = (Xc_raw - mu) / sd
    act_c = Xc_raw[:, T2.MAV].sum(1)
    med = [np.median(act_c[yc == c]) for c in range(LS.K)]
    thr = float(np.sqrt(med[T4.REST] * min(med[:5])))
    data = []
    for X, y in blocks:
        y = np.asarray(y).astype(np.int64)
        X = np.asarray(X, dtype=np.float64)
        Z = (X - mu) / sd
        A = X[:, T2.MAV].sum(1)
        tr = [LG.trials(y, c) for c in range(LS.K)]
        pools = [[Z[i] for i in tr[c][:3]] for c in range(LS.K)]
        apools = [[A[i] for i in tr[c][:3]] for c in range(LS.K)]
        pi = np.concatenate([i for c in range(LS.K) for i in tr[c][3:5]])
        data.append((pools, apools, Z[pi], y[pi]))
    out = []
    beta0 = T2.BETA
    for name, cfg, e in CONDS:
        T2.BETA = cfg.get('beta', beta0)                  # read by the soft branch at call time (one process per job)
        rng = np.random.default_rng(seed * 100003 + subject)
        rng_e = np.random.default_rng(seed * 7919 + subject * 31 + int(round(e * 100)))
        mdl = T4.make(cfg, Zc, yc)
        for b, (pools, apools, Zp, yp) in enumerate(data):
            for k in range(cfg.get('cue', 0)):
                for c in range(LS.K):
                    mdl.learn(pools[c][k], c)
            if hasattr(mdl, 'commit'):
                mdl.commit()
            st = session(mdl, cfg, pools, apools, thr, rng, rng_e, p_dev, e)
            out.append(dict(subject=subject, shift=shift, p_dev=p_dev, seed=seed, cond=name, e=e, block=b,
                            probe_after=T.probe(mdl, Zp, yp), **st))
    T2.BETA = beta0
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    args = ap.parse_args()
    import check_features_c as FC
    import task_sim7 as M
    FC.lib()
    pd.set_option('display.width', 250)
    tasks = [delayed(M.job)(s, sh, 0.1, seed) for sh in (0.0, 0.5) for seed in (0, 1) for s in range(20)]
    df = pd.DataFrame([r for rs in Parallel(n_jobs=args.jobs, verbose=5)(tasks) for r in rs])
    df.to_csv(os.path.join(OUT, 'task_sim7.csv'), index=False, float_format='%.4g')
    d = df[df.block >= 1].copy()
    d['label_err_pct'] = d.wrong_labels / d.labels.clip(lower=1) * 100
    ps = d.groupby(['shift', 'e', 'cond', 'subject'])[['probe_after', 'label_err_pct']].mean()
    sm = ps.groupby(level=[0, 1, 2]).mean().reset_index()
    sm.to_csv(os.path.join(OUT, 'task_sim7_summary.csv'), index=False, float_format='%.4g')
    print(sm.pivot_table(index=['shift', 'cond'], columns='e', values='probe_after').round(2).to_string())
    k = ps.probe_after.unstack('cond')
    cue = ps.probe_after.xs(0.0, level='e').unstack('cond')['cue1']

    def diff(sh, e, a, b):
        x = k.loc[(sh, e)][a]
        y = cue.loc[sh] if b == 'cue1' else k.loc[(sh, e)][b]
        dd = x - y
        m, lo, hi = LS.ci(dd)
        print(f'  shift {sh} e={e}: {a} - {b} = {m:+.2f} ({lo:+.2f}, {hi:+.2f}), better {int((dd > 0).sum())} worse {int((dd < 0).sum())}')
        return m, lo

    for sh in (0.0, 0.5):
        print(f'R14 / R15, shift {sh}')
        for e in ERRS:
            m, lo = diff(sh, e, 'cue1_soft', 'cue1_avg')
            if sh == 0.5 and e in (0.0, 0.3):
                ok = (m >= 1 and lo > 0) if e == 0.3 else (m >= -0.5)
                print(f'    R14 e={e}: ' + ('PASS' if ok else 'FAIL'))
            diff(sh, e, 'cue1_soft', 'cue1_prior')
            diff(sh, e, 'cue1_avg', 'cue1_pn')
            diff(sh, e, 'cue1_avg', 'cue1')


if __name__ == '__main__':
    main()
