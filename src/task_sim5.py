"""Two follow-ups of task_sim4.py (report 35.20): wrong labels that CONFIRM a wrong action, and the activity-gate
threshold. PC only, exploratory.

(a) task_sim4 made a wrong task label a random other gesture. That is the easy case for P-CIIL (a wrong action
    rarely matches a random label). The realistic bad case is a MISSED UNDO: the robot did the wrong thing, the user
    did not undo it, and the system takes the executed gesture as the intended one ("confirm" noise, task_sim4.session
    kind='confirm'; e = probability per command that the context does this).
(b) In task_sim4 the activity gate cost completion: one cued pass + P+N finished 86 % of the sessions with the gate
    and 100 % without it at shift 0.5, while without a cued pass the gate kept false commands from Rest at 0.3 %
    instead of 19.8 %. The threshold (geometric mean of the Rest median and the smallest gesture median, day 1) is
    scaled by k in {0.5, 0.7, 1.0}.
Conditions: one cued pass + {pos, pn, gate, soft} for noise (none), (random, 0.1/0.3), (confirm, 0.1/0.3), each
for every k; references cue1 per k, cue1 without the gate, and pn without a cued pass per k (the false-command stress
case). shift 0 and 0.5, p_dev 0.1, seeds 0-1, 20 subjects.
Decision rules, fixed before running (probe accuracy, blocks 1-10, per subject, 95 % CI):
  R4 under confirm noise e = 0.3, shift 0.5, k = 1: the gate rule is "needed" if gate - pos >= +1 point with CI
     above 0; soft labels are "enough" if soft is within 0.5 points of the best of the four.
  R5 recommended k = the largest completion rate (done) at shift 0.5 for cue1_pn among the k whose no-cue pn keeps
     false commands from Rest (false_rest_pct) <= 1.0 % at shift 0.5.
Writes results/task_sim5.csv and task_sim5_summary.csv.
Usage (in the container): python src/task_sim5.py [--jobs 19]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leaf_guard as LG  # noqa: E402
import leaf_sweep as LS  # noqa: E402
import pipeline as P  # noqa: E402
import task_sim as T  # noqa: E402
import task_sim2 as T2  # noqa: E402
import task_sim4 as T4  # noqa: E402
import zscore_sweep as ZW  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
REST = T.REST
KS = (0.5, 0.7, 1.0)
NOISE = [('none', 0.0), ('random', 0.1), ('random', 0.3), ('confirm', 0.1), ('confirm', 0.3)]
MODES = {'pos': dict(labels='pos'), 'pn': dict(labels='hard'), 'gate': dict(labels='hard', learner='gate'),
         'soft': dict(labels='soft')}


def conds():
    out = [('cue1_noact', dict(cue=1, act=False), 'none', 0.0, 1.0)]
    for k in KS:
        out.append(('cue1', dict(cue=1, act=True), 'none', 0.0, k))
        out.append(('pn', dict(labels='hard', act=True), 'none', 0.0, k))
        for kind, e in NOISE:
            for m, v in MODES.items():
                out.append(('cue1_' + m, dict(dict(cue=1, act=True), **v), kind, e, k))
    return out


def job(subject, shift, p_dev, seed):
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    Zc = (Xc_raw - mu) / sd
    act_c = Xc_raw[:, T2.MAV].sum(1)
    med = [np.median(act_c[yc == c]) for c in range(LS.K)]
    thr0 = float(np.sqrt(med[REST] * min(med[:5])))
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
        data.append((pools, apools, Z[pi], y[pi], A[pi]))
    out = []
    for name, cfg, kind, e, k in conds():
        rng = np.random.default_rng(seed * 100003 + subject)
        rng_e = np.random.default_rng(seed * 7919 + subject * 31 + int(round(e * 100)))
        mdl = T4.make(cfg, Zc, yc)
        thr = thr0 * k
        for b, (pools, apools, Zp, yp, Ap) in enumerate(data):
            for kk in range(cfg.get('cue', 0)):
                for c in range(LS.K):
                    mdl.learn(pools[c][kk], c)
            st = T4.session(mdl, cfg, pools, apools, thr, rng, rng_e, p_dev, e, kind)
            gate_miss = float(np.mean(Ap[yp != REST] < thr) * 100)          # held-out gesture windows the gate drops
            gate_fa = float(np.mean(Ap[yp == REST] >= thr) * 100)           # held-out Rest windows it lets through
            out.append(dict(subject=subject, shift=shift, seed=seed, cond=name, kind=kind, e=e, k=k, block=b,
                            probe_after=T.probe(mdl, Zp, yp), cue_s=8.0 * cfg.get('cue', 0), gate_miss=gate_miss,
                            gate_fa=gate_fa, **st))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    args = ap.parse_args()
    import check_features_c as FC
    import task_sim5 as M
    FC.lib()
    pd.set_option('display.width', 250)
    tasks = [delayed(M.job)(s, sh, 0.1, seed) for sh in (0.0, 0.5) for seed in (0, 1) for s in range(20)]
    df = pd.DataFrame([r for rs in Parallel(n_jobs=args.jobs, verbose=5)(tasks) for r in rs])
    df.to_csv(os.path.join(OUT, 'task_sim5.csv'), index=False, float_format='%.4g')
    d = df[df.block >= 1].copy()
    d['label_err_pct'] = d.wrong_labels / d.labels.clip(lower=1) * 100
    d['wrong_action_pct'] = d.wrong_actions / d.actions.clip(lower=1) * 100
    d['false_rest_pct'] = d.false_rest / d.actions.clip(lower=1) * 100
    d['done'] = (d.cycles >= T.N_CYCLES) * 100
    d['total_s'] = d.seconds + d.cue_s
    cols = ['probe_after', 'label_err_pct', 'wrong_action_pct', 'false_rest_pct', 'done', 'total_s', 'gate_miss', 'gate_fa']
    keys = ['shift', 'k', 'kind', 'e', 'cond']
    ps = d.groupby(keys + ['subject'])[cols].mean()
    sm = ps.groupby(level=list(range(5))).mean().reset_index()
    sm.to_csv(os.path.join(OUT, 'task_sim5_summary.csv'), index=False, float_format='%.4g')
    for (sh, k), g in sm.groupby(['shift', 'k']):
        print(f'shift {sh}, gate threshold x{k}')
        print(g.set_index(['kind', 'e', 'cond'])[cols].round(1).to_string())
    pa = ps.probe_after

    def get(sh, k, kind, e, c):
        return pa.xs((sh, k, kind, e, c), level=list(range(5)))

    def diff(a, b, label):
        dd = a - b
        m, lo, hi = LS.ci(dd)
        print(f'  {label} = {m:+.2f} ({lo:+.2f}, {hi:+.2f}), better {int((dd > 0).sum())} worse {int((dd < 0).sum())}')
        return m, lo

    print('R4: confirm noise (missed undo), one cued pass, k = 1')
    for sh in (0.0, 0.5):
        for e in (0.1, 0.3):
            for c in ('pos', 'pn', 'gate', 'soft'):
                diff(get(sh, 1.0, 'confirm', e, 'cue1_' + c), get(sh, 1.0, 'none', 0.0, 'cue1'), f'shift {sh} e {e}: cue1_{c} - cue1')
    m, lo = diff(get(0.5, 1.0, 'confirm', 0.3, 'cue1_gate'), get(0.5, 1.0, 'confirm', 0.3, 'cue1_pos'), 'R4 gate - pos')
    print('    gate rule needed: ' + ('YES' if (m >= 1 and lo > 0) else 'NO'))
    means = {c: get(0.5, 1.0, 'confirm', 0.3, 'cue1_' + c).mean() for c in MODES}
    print(f'    soft within 0.5 of the best: {"YES" if means["soft"] >= max(means.values()) - 0.5 else "NO"} {means}')
    print('R5: activity-gate threshold at shift 0.5')
    best = None
    for k in KS:
        r = sm[(sm['shift'] == 0.5) & (sm.k == k) & (sm.kind == 'none')].set_index('cond')
        ok = r.loc['pn', 'false_rest_pct'] <= 1.0
        print(f'  k {k}: cue1_pn done {r.loc["cue1_pn", "done"]:.1f} % probe {r.loc["cue1_pn", "probe_after"]:.1f}; '
              f'no-cue pn false_rest {r.loc["pn", "false_rest_pct"]:.2f} %; gate miss {r.loc["cue1", "gate_miss"]:.1f} % '
              f'fa {r.loc["cue1", "gate_fa"]:.1f} %' + ('' if ok else '  (false commands > 1 %)'))
        if ok and (best is None or r.loc['cue1_pn', 'done'] > best[1]):
            best = (k, r.loc['cue1_pn', 'done'])
    print(f'  recommended k = {best[0] if best else None}')


if __name__ == '__main__':
    main()
