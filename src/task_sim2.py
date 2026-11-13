"""Proposed method on the closed-loop task simulation (report 35.18): task-guided intent inference with soft
labels, and an activity gate that does not depend on the electrode position. PC only, exploratory.

Why (task_sim.py, report 35.17): without a cued sequence and with an electrode offset the labels from the task were
wrong 24 % of the time and the model drifted. Looking at the records, the wrong labels there are almost all false
commands fired while the user RESTS (the offset model takes Rest windows for gestures); the system then labels
those windows with the expected gesture.
Two components, both cheap on a device:
  act    activity gate. a = sum over the 8 channels of the raw MAV of the window. A sum over all channels does not
         change when the electrode ring is rotated. Threshold from the day-1 calibration: geometric mean of the Rest
         median and the smallest gesture median. A window below the threshold is Rest, whatever the classifier
         says: no command, no label.
  soft   instead of the hard label 'the expected gesture', a distribution over the gestures for the windows of a
         command:  q(g)  ~  prior(g | robot state)  x  exp(beta x mean discriminant of g)
         prior: expected gesture 1 - eps, the other currently valid commands share eps, Rest p0, invalid ones 0.01
         each (eps 0.15, p0 0.05, beta 0.3; fixed before running, not tuned). The LDA sums are updated with the
         weights q: the outer-product sum needs no label, only the class sums and counts are weighted, so the cost
         on the MCU is unchanged. This keeps a deliberate deviation of the user (the EMG says 'home' although the
         task expected 'grip') from being written in as the expected gesture, and gives uncertain trials less say.
The user's reaction after a wrong action (undo / redo) would be a third, independent piece of evidence; in this
simulation an error and a change of mind are followed by the same next step, so it cannot be tested here. It needs
recordings of real use.
Conditions: hard = task_sim's labels with the plain sums; gate = lda_robust's gate rule; soft; each with / without
act; each with / without one cued pass. References fixed, cue1, cue2, oracle. p_dev 0 and 0.25.
Decision rule fixed beforehand: the proposed method (soft + act) is worth making the main method if, with NO cued
pass and shift 0.5, its probe accuracy is at least 5 points above task labels with the gate rule (task_sim's
task_gate), and with one cued pass it is not more than 0.5 points below cue1 + gate.
Writes results/task_sim2.csv and task_sim2_summary.csv.
Usage (in the container): python src/task_sim2.py [--jobs 19]
"""
import argparse
import os
import sys
from collections import deque

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lda_anchor as LA  # noqa: E402
import lda_context2 as C2  # noqa: E402
import lda_robust as LR  # noqa: E402
import leaf_guard as LG  # noqa: E402
import leaf_sweep as LS  # noqa: E402
import pipeline as P  # noqa: E402
import task_sim as T  # noqa: E402
import zscore_sweep as ZW  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
REST = T.REST
EPS, P0, BETA, P_INVALID = 0.15, 0.05, 0.3, 0.01
MAV = slice(P.FEATS.index('mav') * 8, P.FEATS.index('mav') * 8 + 8)
CONDS = {
    'fixed': dict(), 'fixed_act': dict(act=True),
    'cue1': dict(cue=1), 'cue2': dict(cue=2),
    'hard': dict(labels='hard'), 'gate': dict(labels='hard', learner='gate'),
    'hard_act': dict(labels='hard', act=True), 'gate_act': dict(labels='hard', learner='gate', act=True),
    'soft': dict(labels='soft'), 'soft_act': dict(labels='soft', act=True),
    'cue1_gate': dict(labels='hard', learner='gate', cue=1),
    'cue1_gate_act': dict(labels='hard', learner='gate', cue=1, act=True),
    'cue1_soft_act': dict(labels='soft', cue=1, act=True),
    'oracle': dict(labels='oracle'),
}


def learn_soft(m, Z, q):
    Zq = LA.OasLDA.q(Z)
    m.G = C2.DECAY * m.G + Zq.T @ Zq
    m.s = C2.DECAY * m.s + np.outer(q, Zq.sum(0))
    m.n = C2.DECAY * m.n + q * len(Zq)
    m.fit()


def session(mdl, cfg, pools, apools, thr, rng, p_dev):
    """task_sim.session with the activity gate and soft labels; pools[c] trials (10 x 80), apools[c] their activity"""
    w = T.World()
    ptr = [0] * LS.K
    queue = deque()                                       # (row, activity, true class, attempt id)
    busy_until, t = 0, 0
    last, run, latched, run_rows = -1, 0, -1, []
    pend = None                                           # [expected, rows, pred, true, attempt, valid mask]
    st = dict(labels=0, wrong_labels=0, actions=0, wrong_actions=0, invalid=0, attempts=0, false_rest=0, q_true=0.0)
    attempt = 0
    mode = cfg.get('labels')

    def take(c):
        k = ptr[c] % len(pools[c])
        ptr[c] += 1
        return pools[c][k], apools[c][k]

    def flush():
        nonlocal pend
        if pend is not None and mode is not None and len(pend[1]) >= T.K_DC:
            exp, rows, _, true, _, valid = pend
            Z = np.stack(rows)
            if mode == 'oracle':
                mdl.learn(Z, true)
            elif mode == 'hard':
                st['wrong_labels'] += int(exp != true)
                mdl.learn(Z, exp)
            else:
                prior = np.full(LS.K, P_INVALID)
                others = [c for c in range(5) if valid[c] and c != exp]
                prior[exp] = 1 - EPS if others else 1 - P0
                for c in others:
                    prior[c] = EPS / len(others)
                prior[REST] = P0
                s = mdl.m.scores(Z).mean(0)
                q = prior * np.exp(BETA * (s - s.max()))
                q /= q.sum()
                st['wrong_labels'] += int(np.argmax(q) != true)
                st['q_true'] += float(q[true])
                learn_soft(mdl.m, Z, q)
            st['labels'] += 1
        pend = None

    while w.cycles < T.N_CYCLES and t < T.CAP:
        if not queue:
            flush()
            if t < busy_until:
                Zr, ar = take(REST)
                j = rng.integers(10)
                queue.append((Zr[j], ar[j], REST, -1))
            else:
                w.advance()
                if w.cycles >= T.N_CYCLES:
                    break
                g = w.intent()
                if g != T.LATERAL and w.valid(T.LATERAL) and rng.random() < p_dev:
                    g = T.LATERAL
                attempt += 1
                st['attempts'] += 1
                Zg, ag = take(g)
                queue.extend((r, a, g, attempt) for r, a in zip(Zg, ag))
                Zr, ar = take(REST)
                queue.extend((r, a, REST, -1) for r, a in zip(Zr[:5], ar[:5]))
        row, a, true, att = queue.popleft()
        busy = t < busy_until
        pred = int(np.argmax(mdl.scores(row[None])[0]))
        if cfg.get('act') and a < thr:
            pred = REST                                   # not contracting: Rest, whatever the classifier says
        if pred == last:
            run = min(run + 1, T.K_DC)
            run_rows.append(row)
        else:
            last, run, run_rows = pred, 1, [row]
        if pend is not None:
            if pred == pend[2] and att == pend[4]:
                pend[1].append(row)
            else:
                flush()
        if run >= T.K_DC and pred != latched:
            latched = pred
            if pred != REST and not busy:
                w.advance()
                expected = w.intent() if w.cycles < T.N_CYCLES else REST
                valid = [w.valid(c) for c in range(5)]
                if valid[pred]:
                    st['actions'] += 1
                    st['wrong_actions'] += int(pred != true)
                    st['false_rest'] += int(true == REST)
                    busy_until = t + w.execute(pred)
                else:
                    st['invalid'] += 1
                if expected != REST:
                    pend = [expected, list(run_rows), pred, true, att, valid]
        t += 1
    flush()
    st.update(cycles=w.cycles, seconds=t / 10)
    return st


def job(subject, shift, p_dev, seed):
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    Zc = (Xc_raw - mu) / sd
    act_c = Xc_raw[:, MAV].sum(1)
    med = [np.median(act_c[yc == c]) for c in range(LS.K)]
    thr = float(np.sqrt(med[REST] * min(med[:5])))
    out = []
    for name, cfg in CONDS.items():
        rng = np.random.default_rng(seed * 100003 + subject)
        mdl = LR.make(cfg.get('learner', 'plain'), Zc, yc)
        for b, (X, y) in enumerate(blocks):
            y = np.asarray(y).astype(np.int64)
            X = np.asarray(X, dtype=np.float64)
            Z = (X - mu) / sd
            A = X[:, MAV].sum(1)
            tr = [LG.trials(y, c) for c in range(LS.K)]
            pools = [[Z[i] for i in tr[c][:3]] for c in range(LS.K)]
            apools = [[A[i] for i in tr[c][:3]] for c in range(LS.K)]
            pi = np.concatenate([i for c in range(LS.K) for i in tr[c][3:5]])
            before = T.probe(mdl, Z[pi], y[pi])
            gate_ok = float(np.mean((A[pi] >= thr) == (y[pi] != REST)) * 100)     # the activity gate alone, held-out
            cue_s = 0.0
            for k in range(cfg.get('cue', 0)):
                for c in range(LS.K):
                    mdl.learn(pools[c][k], c)
                cue_s += 8.0
            st = session(mdl, cfg, pools, apools, thr, rng, p_dev)
            out.append(dict(subject=subject, shift=shift, p_dev=p_dev, seed=seed, cond=name, block=b, probe_before=before,
                            probe_after=T.probe(mdl, Z[pi], y[pi]), cue_s=cue_s, act_gate_acc=gate_ok, **st))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    args = ap.parse_args()
    import check_features_c as FC
    import task_sim2 as M
    FC.lib()
    pd.set_option('display.width', 250)
    tasks = [delayed(M.job)(s, sh, pd_, seed) for sh in (0.0, 0.5) for pd_ in (0.0, 0.25) for seed in (0, 1)
             for s in range(20)]
    df = pd.DataFrame([r for rs in Parallel(n_jobs=args.jobs, verbose=5)(tasks) for r in rs])
    df.to_csv(os.path.join(OUT, 'task_sim2.csv'), index=False, float_format='%.4g')
    d = df[df.block >= 1].copy()
    d['label_err_pct'] = d.wrong_labels / d.labels.clip(lower=1) * 100
    d['wrong_action_pct'] = d.wrong_actions / d.actions.clip(lower=1) * 100
    d['false_rest_pct'] = d.false_rest / d.actions.clip(lower=1) * 100
    d['done'] = (d.cycles >= T.N_CYCLES) * 100
    d['total_s'] = d.seconds + d.cue_s
    cols = ['probe_after', 'labels', 'label_err_pct', 'wrong_action_pct', 'false_rest_pct', 'invalid', 'done', 'total_s']
    ps = d.groupby(['shift', 'p_dev', 'cond', 'subject'])[cols + ['act_gate_acc']].mean()
    sm = ps.groupby(level=[0, 1, 2]).mean().reset_index()
    sm = sm.merge(ps.groupby(level=[0, 1, 2]).probe_after.min().reset_index(name='worst_subject'))
    sm.to_csv(os.path.join(OUT, 'task_sim2_summary.csv'), index=False, float_format='%.4g')
    for (sh, pdv), g in sm.groupby(['shift', 'p_dev']):
        print(f'shift {sh}, deliberate deviations {pdv}; activity gate alone (held-out windows): {g.act_gate_acc.mean():.1f} %')
        print(g.set_index('cond').loc[list(CONDS), cols + ['worst_subject']].round(1).to_string())
    # the decision rule
    k = ps.xs(0.5, level='shift').xs(0.0, level='p_dev').probe_after.unstack('cond')
    for a, b in (('soft_act', 'gate'), ('cue1_soft_act', 'cue1_gate'), ('gate_act', 'gate'), ('soft', 'hard')):
        dd = k[a] - k[b]
        m, lo, hi = LS.ci(dd)
        print(f'shift 0.5, p_dev 0: {a} - {b} = {m:+.2f} ({lo:+.2f}, {hi:+.2f}), better {int((dd > 0).sum())} worse {int((dd < 0).sum())}')


if __name__ == '__main__':
    main()
