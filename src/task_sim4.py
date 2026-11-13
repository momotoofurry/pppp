"""CIIL comparators and wrong task labels on the closed-loop task simulation (report 35.20). PC only, exploratory.

Why: the closest prior work, Campbell et al. 2024 (JNER 21:70, "context-informed incremental learning", CIIL), already
adapts an LDA from task context (a virtual 2-DOF cursor game, perfect context every 100 ms). Two questions the thesis
has to answer before it can claim anything:
  (1) how do the CIIL strategies do in THIS task (discrete robot commands, one outcome per command, Rest windows,
      electrode offset), next to the gate rule and the soft labels of task_sim2.py?
  (2) what happens when the task label itself is wrong (the robot's outcome or the user's undo misread)? Campbell
      et al. and Xavier Fidencio et al. 2025 both assume perfect context; both name this as open.
CIIL mapped onto task_sim2's session (a "command" = the windows that established a decoded gesture; the expected
gesture = what the task model says comes next):
  uhc      unsupervised high confidence: learn the windows with the classifier's own class when its mean LDA posterior
           over the windows is >= 0.99 (Campbell exp. 2 threshold). Uses no task information.
  pos      P-CIIL: learn only when the decoded gesture equals the expected one (with that class).
  neg      N-CIIL: learn only when it does not, with the expected gesture.
  pn       P+N-CIIL: both. This is exactly task_sim's "hard" labels: the earlier baseline WAS P+N-CIIL.
  pn_rule  pn with CIIL's own update rule instead of the running sums: labelled windows are buffered and every 10 s
           (100 windows) each class mean and covariance are blended in, a = 0.1 Nb / (Nc + 0.1 Nb), Nc = windows of
           the class collected for adaptation so far (Campbell eq. 1-2); pooled covariance, OAS shrinkage as ours.
  pn_noact pn without the activity gate (CIIL had no such front end).
  gate     task_sim's gate rule on hard labels; soft  task_sim2's soft labels (eps 0.15, p0 0.05, beta 0.3).
All but pn_noact use the activity gate of task_sim2. Each with no cued pass and with one cued pass (8 s).
References: fixed, cue1, cue2 (no task labels), oracle. p_dev 0.1 (the user sometimes sends the arm home).
Wrong task labels: with probability e (0, 0.1, 0.2, 0.3) the expected gesture the system uses for a command is
replaced by a random other gesture, before any rule sees it (separate random stream, so the user's behaviour is the
same for every e). uhc and the references do not use it and run at e = 0 only.
Decision rules, fixed before running (shift 0.5, probe accuracy averaged over blocks 1-10, per subject, 95 % CI):
  R1 soft is "more tolerant of wrong task labels than CIIL" only if, with one cued pass, soft - best CIIL variant
     (pos/neg/pn/pn_rule, best by mean) is >= +2 points with CI above 0 at e = 0.3, and >= -0.5 at e = 0.
  R2 the earlier claim "task labels alone fail under electrode offset" stands only if no CIIL variant without a cued
     pass comes within 1 point of cue1 (the cued pass alone).
  R3 report, for soft and pn with one cued pass, the largest e at which they are still above cue1.
Writes results/task_sim4.csv and task_sim4_summary.csv.
Usage (in the container): python src/task_sim4.py [--jobs 19]
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
import lda_robust as LR  # noqa: E402
import leaf_guard as LG  # noqa: E402
import leaf_sweep as LS  # noqa: E402
import pipeline as P  # noqa: E402
import task_sim as T  # noqa: E402
import task_sim2 as T2  # noqa: E402
import zscore_sweep as ZW  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
REST = T.REST
UHC_THR, ALPHA, BATCH = 0.99, 0.1, 100
ERRS = (0.0, 0.1, 0.2, 0.3)
TASK_MODES = {
    'pos': dict(labels='pos'), 'neg': dict(labels='neg'), 'pn': dict(labels='hard'),
    'pn_rule': dict(labels='hard', learner='rule'), 'pn_noact': dict(labels='hard', act=False),
    'gate': dict(labels='hard', learner='gate'), 'soft': dict(labels='soft'),
}
REFS = {'fixed': dict(), 'cue1': dict(cue=1), 'cue2': dict(cue=2), 'oracle': dict(labels='oracle'),
        'uhc': dict(labels='uhc'), 'cue1_uhc': dict(labels='uhc', cue=1)}


def conds():
    out = [(k, dict(act=True, **v), 0.0) for k, v in REFS.items()]
    for e in ERRS:
        for k, v in TASK_MODES.items():
            for cue in (0, 1):
                out.append((('cue1_' if cue else '') + k, dict(dict(act=True, cue=cue), **v), e))
    return out


class Rule:
    """CIIL's update (Campbell et al. 2024, eq. 1-2) on class means and covariances, pooled covariance + OAS"""

    def __init__(self, Zc, yc):
        Zq = LA.OasLDA.q(Zc)
        self.mu = np.stack([Zq[yc == c].mean(0) for c in range(LS.K)])
        self.cov = np.stack([np.cov(Zq[yc == c].T, bias=True) for c in range(LS.K)])
        self.N0 = float(len(Zq))
        self.na = np.zeros(LS.K)
        self.buf, self.t = [], 0
        self.fit()

    def fit(self):
        self.w, self.b = LR.oas_solve(self.cov.mean(0), self.N0, self.mu)

    def learn(self, Z, lab):
        self.buf.append((LA.OasLDA.q(Z), lab))

    def tick(self):
        self.t += 1
        if self.t % BATCH == 0:
            self.commit()

    def commit(self):
        if not self.buf:
            return
        for c in range(LS.K):
            Zb = [z for z, l in self.buf if l == c]
            if not Zb:
                continue
            Zb = np.concatenate(Zb)
            if len(Zb) < 2:
                continue
            nb = len(Zb)
            self.na[c] += nb
            a = ALPHA * nb / (self.na[c] + ALPHA * nb)
            self.mu[c] = (1 - a) * self.mu[c] + a * Zb.mean(0)
            self.cov[c] = (1 - a) * self.cov[c] + a * np.cov(Zb.T, bias=True)
        self.buf = []
        self.fit()

    def scores(self, Z):
        return LA.OasLDA.q(Z) @ self.w.T + self.b


def make(cfg, Zc, yc):
    return Rule(Zc, yc) if cfg.get('learner') == 'rule' else LR.make(cfg.get('learner', 'plain'), Zc, yc)


def session(mdl, cfg, pools, apools, thr, rng, rng_e, p_dev, e, kind='random'):
    """task_sim2.session with the CIIL label modes and wrong task labels. kind 'random': a wrong label is a random
    other gesture; 'confirm': the context takes the executed gesture for the intended one (a missed undo)"""
    w = T.World()
    ptr = [0] * LS.K
    queue = deque()
    busy_until, t = 0, 0
    last, run, latched, run_rows = -1, 0, -1, []
    pend = None                                           # [expected, rows, pred, true, attempt, valid mask]
    st = dict(labels=0, wrong_labels=0, actions=0, wrong_actions=0, invalid=0, attempts=0, false_rest=0, flipped=0)
    attempt = 0
    mode = cfg.get('labels')

    def take(c):
        k = ptr[c] % len(pools[c])
        ptr[c] += 1
        return pools[c][k], apools[c][k]

    def put(Z, lab, true):
        st['labels'] += 1
        st['wrong_labels'] += int(lab != true)
        mdl.learn(Z, lab)

    def flush():
        nonlocal pend
        if pend is not None and mode is not None and len(pend[1]) >= T.K_DC:
            exp, rows, pred, true, _, valid = pend
            Z = np.stack(rows)
            if mode not in ('oracle', 'uhc') and e > 0 and rng_e.random() < e:
                other = int(rng_e.choice([c for c in range(5) if c != exp]))
                new = other if kind == 'random' else (pred if pred < 5 else exp)
                st['flipped'] += int(new != exp)
                exp = new
            if mode == 'oracle':
                put(Z, true, true)
            elif mode == 'uhc':
                s = mdl.scores(Z)
                p = np.exp(s - s.max(1, keepdims=True))
                p /= p.sum(1, keepdims=True)
                if p[:, pred].mean() >= UHC_THR:
                    put(Z, pred, true)
            elif mode == 'hard':
                put(Z, exp, true)
            elif mode == 'pos':
                if pred == exp:
                    put(Z, pred, true)
            elif mode == 'neg':
                if pred != exp:
                    put(Z, exp, true)
            else:                                         # soft, as task_sim2
                prior = np.full(LS.K, T2.P_INVALID)
                others = [c for c in range(5) if valid[c] and c != exp]
                prior[exp] = 1 - T2.EPS if others else 1 - T2.P0
                for c in others:
                    prior[c] = T2.EPS / len(others)
                prior[REST] = T2.P0
                s = mdl.m.scores(Z).mean(0)
                q = prior * np.exp(T2.BETA * (s - s.max()))
                q /= q.sum()
                st['labels'] += 1
                st['wrong_labels'] += int(np.argmax(q) != true)
                T2.learn_soft(mdl.m, Z, q)
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
        if hasattr(mdl, 'tick'):
            mdl.tick()
        pred = int(np.argmax(mdl.scores(row[None])[0]))
        if cfg.get('act') and a < thr:
            pred = REST
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
    if hasattr(mdl, 'commit'):
        mdl.commit()
    st.update(cycles=w.cycles, seconds=t / 10)
    return st


def job(subject, shift, p_dev, seed):
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    Zc = (Xc_raw - mu) / sd
    act_c = Xc_raw[:, T2.MAV].sum(1)
    med = [np.median(act_c[yc == c]) for c in range(LS.K)]
    thr = float(np.sqrt(med[REST] * min(med[:5])))
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
    for name, cfg, e in conds():
        rng = np.random.default_rng(seed * 100003 + subject)
        rng_e = np.random.default_rng(seed * 7919 + subject * 31 + int(round(e * 100)))
        mdl = make(cfg, Zc, yc)
        for b, (pools, apools, Zp, yp) in enumerate(data):
            cue_s = 0.0
            for k in range(cfg.get('cue', 0)):
                for c in range(LS.K):
                    mdl.learn(pools[c][k], c)
                cue_s += 8.0
            if hasattr(mdl, 'commit'):
                mdl.commit()
            st = session(mdl, cfg, pools, apools, thr, rng, rng_e, p_dev, e)
            out.append(dict(subject=subject, shift=shift, p_dev=p_dev, seed=seed, cond=name, e=e, block=b,
                            probe_after=T.probe(mdl, Zp, yp), cue_s=cue_s, **st))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    args = ap.parse_args()
    import check_features_c as FC
    import task_sim4 as M
    FC.lib()
    pd.set_option('display.width', 250)
    tasks = [delayed(M.job)(s, sh, 0.1, seed) for sh in (0.0, 0.5) for seed in (0, 1) for s in range(20)]
    df = pd.DataFrame([r for rs in Parallel(n_jobs=args.jobs, verbose=5)(tasks) for r in rs])
    df.to_csv(os.path.join(OUT, 'task_sim4.csv'), index=False, float_format='%.4g')
    d = df[df.block >= 1].copy()
    d['label_err_pct'] = d.wrong_labels / d.labels.clip(lower=1) * 100
    d['wrong_action_pct'] = d.wrong_actions / d.actions.clip(lower=1) * 100
    d['false_rest_pct'] = d.false_rest / d.actions.clip(lower=1) * 100
    d['done'] = (d.cycles >= T.N_CYCLES) * 100
    d['total_s'] = d.seconds + d.cue_s
    cols = ['probe_after', 'labels', 'label_err_pct', 'wrong_action_pct', 'false_rest_pct', 'done', 'total_s']
    ps = d.groupby(['shift', 'e', 'cond', 'subject'])[cols].mean()
    sm = ps.groupby(level=[0, 1, 2]).mean().reset_index()
    sm = sm.merge(ps.groupby(level=[0, 1, 2]).probe_after.min().reset_index(name='worst_subject'))
    sm.to_csv(os.path.join(OUT, 'task_sim4_summary.csv'), index=False, float_format='%.4g')
    for (sh, e), g in sm.groupby(['shift', 'e']):
        print(f'shift {sh}, wrong task labels e = {e}')
        print(g.set_index('cond')[cols + ['worst_subject']].round(1).to_string())
    k = ps.probe_after.unstack('cond')

    def diff(sh, ea, a, eb, b):
        dd = k.loc[(sh, ea)][a] - k.loc[(sh, eb)][b]
        m, lo, hi = LS.ci(dd)
        print(f'  shift {sh}: {a}@{ea} - {b}@{eb} = {m:+.2f} ({lo:+.2f}, {hi:+.2f}), better {int((dd > 0).sum())} worse {int((dd < 0).sum())}')
        return m, lo

    print('R1: soft vs the best CIIL variant, one cued pass')
    for sh in (0.0, 0.5):
        for e in ERRS:
            best = max(('cue1_pos', 'cue1_neg', 'cue1_pn', 'cue1_pn_rule'), key=lambda c: k.loc[(sh, e)][c].mean())
            m, lo = diff(sh, e, 'cue1_soft', e, best)
            if sh == 0.5:
                print(f'    best CIIL = {best}; ' + ('R1 e=0.3: ' + ('PASS' if (m >= 2 and lo > 0) else 'FAIL') if e == 0.3 else
                                                   'R1 e=0: ' + ('PASS' if m >= -0.5 else 'FAIL') if e == 0 else ''))
    print('R2: no cued pass vs the cued pass alone (shift 0.5)')
    for c in ('uhc', 'pos', 'neg', 'pn', 'pn_rule', 'pn_noact', 'gate', 'soft'):
        m, _ = diff(0.5, 0.0, c, 0.0, 'cue1')
        print(f'    {c}: ' + ('within 1 point of cue1 -> revise the claim' if m >= -1 else 'below cue1 by more than 1 point'))
    print('R3: one cued pass + task labels vs cue1 as the task labels get worse')
    for sh in (0.0, 0.5):
        for c in ('cue1_soft', 'cue1_pn', 'cue1_gate', 'cue1_pos', 'cue1_neg', 'cue1_pn_rule'):
            for e in ERRS:
                diff(sh, e, c, 0.0, 'cue1')


if __name__ == '__main__':
    main()
