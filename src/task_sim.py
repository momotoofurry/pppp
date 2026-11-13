"""Closed-loop pick-and-place simulation: the labels come from the TASK, not from an oracle (report 35.17).
PC only, exploratory. Recorded EMG windows drive a simulated user, the decoder, the decision rule, a task state
machine and a timed robot model; the system has to work out the labels by itself.

Task (pilot-freeze-5 commands): a cycle is  pose A (Power) -> grip (Tripod) -> pose B (Pointer) -> release (Open)
-> home (Lateral); the object starts at A. Robot state = location (home / A / B), holding, where the object is.
A command is VALID only if it can do something now: pose X when not at X, home when not at home, grip when the
gripper is empty and the object is here, release when holding. Durations as kinova_bridge / ros_relay: largest
joint change / speed (poses_sim.json, 20 deg/s): home <-> A or B 1.75 s, A <-> B 3.5 s; gripper 1.0 s (assumed).

Simulated user (every 100 ms one window): knows the task; when the robot is idle makes the gesture of the next
useful step (the step that brings the state towards the current target, so wrong robot actions are repaired by the
same rule) using a recorded trial of that gesture (10 windows), then 5 windows of Rest; rests while the robot
moves. With probability p_dev an attempt is a deliberate deviation (the user sends the arm home instead).
Decoder: LDA scores -> class per window -> 3 equal consecutive windows establish a class (decision.c, no rejection)
-> command; commands that arrive while the robot moves are ignored.
What the SYSTEM knows: the robot state and the task model, hence the gesture it EXPECTS next (the same rule as the
user, without the deviations). Labels, without any oracle:
  an executed command equal to the expected one  -> its windows are labelled with it
  an executed or invalid command that is not the expected one -> its windows are labelled with the EXPECTED gesture
  (an invalid command tells that a gesture was made and decoded wrongly; a valid unexpected one is taken as an error)
Wrong labels therefore arise from false commands during Rest (true class Rest) and from deliberate deviations.
`ctx`: the classifier may only choose among the gestures of the currently valid commands and Rest.
Conditions = learner x labels x context x cued passes, see CONDS. Learners from lda_robust.py (plain sums / gate).
Sessions = the blocks of arm_position (a new arm position each; shift 0.5 = electrode offset as well); the model
is carried from session to session. Interaction uses trials 0-2 of every gesture (re-used in turn); the model is
PROBED before and after the session on trials 3-4, which the interaction never sees (window accuracy, no context).
Writes results/task_sim.csv (per session), task_sim_summary.csv, task_sim_trace.csv (one example session: every
robot action with its duration, for the ROS check).
Usage (in the container): python src/task_sim.py [--jobs 19]
"""
import argparse
import os
import sys
from collections import deque

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lda_robust as LR  # noqa: E402
import leaf_guard as LG  # noqa: E402
import leaf_sweep as LS  # noqa: E402
import pipeline as P  # noqa: E402
import zscore_sweep as ZW  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
POWER, LATERAL, TRIPOD, POINTER, OPEN, REST = range(6)
NAME = {POWER: 'pose_A', LATERAL: 'home', TRIPOD: 'grip', POINTER: 'pose_B', OPEN: 'release'}
GOTO = {'A': POWER, 'B': POINTER, 'home': LATERAL}
TARGET = [('A', 0), ('A', 1), ('B', 1), ('B', 0), ('home', 0)]
MOVE = {frozenset(('home', 'A')): 18, frozenset(('home', 'B')): 18, frozenset(('A', 'B')): 35}   # windows (100 ms)
GRIP_WIN = 10
K_DC = 3
N_CYCLES, CAP = 6, 3000                                   # at most 300 s per session
CONDS = {
    'fixed':          dict(learner=None),
    'cue1':           dict(learner='plain', labels=None, cue=1),
    'cue2':           dict(learner='plain', labels=None, cue=2),
    'task_plain':     dict(learner='plain', labels='task'),
    'task_gate':      dict(learner='gate', labels='task'),
    'task_gate_ctx':  dict(learner='gate', labels='task', ctx=True),
    'cue1_task_gate': dict(learner='gate', labels='task', cue=1),
    'cue1_task_gate_ctx': dict(learner='gate', labels='task', cue=1, ctx=True),
    'fixed_ctx':      dict(learner=None, ctx=True),
    'oracle':         dict(learner='plain', labels='oracle'),
}


class World:
    def __init__(self):
        self.loc, self.hold, self.obj, self.step, self.cycles = 'home', 0, 'A', 0, 0

    def valid(self, c):
        return {POWER: self.loc != 'A', POINTER: self.loc != 'B', LATERAL: self.loc != 'home',
                TRIPOD: (not self.hold) and self.loc == self.obj, OPEN: bool(self.hold)}.get(c, False)

    def execute(self, c):
        """returns the duration in windows"""
        if c in (POWER, POINTER, LATERAL):
            new = {POWER: 'A', POINTER: 'B', LATERAL: 'home'}[c]
            d = MOVE[frozenset((self.loc, new))]
            self.loc = new
            return d
        if c == TRIPOD:
            self.hold, self.obj = 1, 'gripper'
        else:
            self.hold, self.obj = 0, self.loc
        return GRIP_WIN

    def intent(self):
        """the gesture that brings the state towards the target of the current step"""
        tl, th = TARGET[self.step]
        if self.step == 3 and not self.hold and self.obj != 'B':          # dropped somewhere else: pick it up again
            return TRIPOD if self.loc == self.obj else GOTO[self.obj]
        if th and not self.hold:
            return TRIPOD if self.loc == self.obj else GOTO[self.obj]
        if not th and self.hold:
            return OPEN if (self.loc == tl or self.step != 3) else GOTO[tl]
        return GOTO[tl] if self.loc != tl else REST

    def advance(self):
        while True:
            tl, th = TARGET[self.step]
            if (self.loc, self.hold) != (tl, th) or (self.step == 3 and self.obj != 'B'):
                return
            self.step += 1
            if self.step == len(TARGET):
                self.step, self.cycles, self.obj = 0, self.cycles + 1, 'A'


def session(mdl, cfg, pools, rng, p_dev, trace=None):
    """one session; pools[c] = list of (10 x 80) arrays of class c. Returns the counters."""
    w = World()
    ptr = [0] * LS.K
    queue = deque()                                       # (row, true class, attempt id)
    busy_until, t = 0, 0
    last, run, latched, run_rows = -1, 0, -1, []
    pend = None                                           # label being collected: [label, rows, pred class, attempt]
    st = dict(labels=0, wrong_labels=0, actions=0, wrong_actions=0, invalid=0, attempts=0, false_rest=0)
    attempt = 0
    learn = cfg.get('labels') is not None and mdl is not None

    def take(c):
        Z = pools[c][ptr[c] % len(pools[c])]
        ptr[c] += 1
        return Z

    def flush():
        nonlocal pend
        if pend is not None and learn and len(pend[1]) >= K_DC:
            lab, rows, true = pend[0], np.stack(pend[1]), pend[3]
            st['labels'] += 1
            st['wrong_labels'] += int(lab != true)
            mdl.learn(rows, lab)
        pend = None

    while w.cycles < N_CYCLES and t < CAP:
        if not queue:
            flush()
            if t < busy_until:
                queue.append((take(REST)[rng.integers(10)], REST, -1))
            else:
                w.advance()
                if w.cycles >= N_CYCLES:
                    break
                g = w.intent()
                if g != LATERAL and w.valid(LATERAL) and rng.random() < p_dev:
                    g = LATERAL                              # the user changes their mind
                attempt += 1
                st['attempts'] += 1
                queue.extend((r, g, attempt) for r in take(g))
                queue.extend((r, REST, -1) for r in take(REST)[:5])
        row, true, att = queue.popleft()
        busy = t < busy_until
        s = mdl.scores(row[None])[0] if mdl is not None else None
        if cfg.get('ctx') and not busy:
            mask = np.full(LS.K, -np.inf)
            mask[[c for c in range(5) if w.valid(c)] + [REST]] = 0.0
            s = s + mask
        pred = int(np.argmax(s))
        if pred == last:
            run = min(run + 1, K_DC)
            run_rows.append(row)
        else:
            last, run, run_rows = pred, 1, [row]
        if pend is not None:
            if pred == pend[2] and att == pend[4]:
                pend[1].append(row)                       # the rest of the same gesture
            else:
                flush()
        if run >= K_DC and pred != latched:
            latched = pred
            if pred != REST and not busy:
                w.advance()                               # the state may already satisfy the current step
                expected = w.intent() if w.cycles < N_CYCLES else REST
                ok = w.valid(pred)
                if ok:
                    st['actions'] += 1
                    st['wrong_actions'] += int(pred != true)
                    st['false_rest'] += int(true == REST)
                    dur = w.execute(pred)
                    busy_until = t + dur
                    if trace is not None:
                        trace.append(dict(t_s=t / 10, command=NAME[pred], intended=NAME.get(true, 'rest'), dur_s=dur / 10,
                                          loc=w.loc, holding=w.hold))
                else:
                    st['invalid'] += 1
                lab = true if cfg.get('labels') == 'oracle' else (expected if expected != REST else None)
                if lab is not None:
                    pend = [lab, list(run_rows), pred, true, att]
        t += 1
    flush()
    st.update(cycles=w.cycles, seconds=t / 10)
    return st


def probe(mdl, Zp, yp):
    return float(np.mean(np.argmax(mdl.scores(Zp), axis=1) == yp) * 100)


def job(subject, shift, p_dev, seed):
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    Zc = (Xc_raw - mu) / sd
    out, traces = [], []
    for name, cfg in CONDS.items():
        rng = np.random.default_rng(seed * 100003 + subject)
        mdl = LR.make(cfg['learner'] or 'plain', Zc, yc)
        for b, (X, y) in enumerate(blocks):
            y = np.asarray(y).astype(np.int64)
            Z = (np.asarray(X, dtype=np.float64) - mu) / sd
            tr = [LG.trials(y, c) for c in range(LS.K)]
            pools = [[Z[i] for i in tr[c][:3]] for c in range(LS.K)]
            pi = np.concatenate([i for c in range(LS.K) for i in tr[c][3:5]])
            before = probe(mdl, Z[pi], y[pi])
            cue_s = 0.0
            for k in range(cfg.get('cue', 0)):
                for c in range(LS.K):
                    mdl.learn(pools[c][k], c)
                cue_s += 8.0
            after_cue = probe(mdl, Z[pi], y[pi])
            trace = [] if (name == 'cue1_task_gate_ctx' and subject == 0 and b == 1 and seed == 0 and p_dev == 0.1) else None
            st = session(mdl, cfg, pools, rng, p_dev, trace)
            if trace:
                traces = trace
            out.append(dict(subject=subject, shift=shift, p_dev=p_dev, seed=seed, cond=name, block=b,
                            probe_before=before, probe_after_cue=after_cue, probe_after=probe(mdl, Z[pi], y[pi]),
                            cue_s=cue_s, **st))
    return out, traces


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    args = ap.parse_args()
    import check_features_c as FC
    import task_sim as M
    FC.lib()
    pd.set_option('display.width', 250)
    tasks = [delayed(M.job)(s, sh, pd_, seed) for sh in (0.0, 0.5) for pd_ in (0.0, 0.1) for seed in (0, 1)
             for s in range(20)]
    res = Parallel(n_jobs=args.jobs, verbose=5)(tasks)
    df = pd.DataFrame([r for rs, _ in res for r in rs])
    df.to_csv(os.path.join(OUT, 'task_sim.csv'), index=False, float_format='%.4g')
    tr = [t for _, t in res if t]
    if tr:
        pd.DataFrame(tr[0]).to_csv(os.path.join(OUT, 'task_sim_trace.csv'), index=False)
    d = df[df.block >= 1].copy()
    d['label_err_pct'] = d.wrong_labels / d.labels.clip(lower=1) * 100
    d['wrong_action_pct'] = d.wrong_actions / d.actions.clip(lower=1) * 100
    d['done'] = (d.cycles >= N_CYCLES) * 100
    d['total_s'] = d.seconds + d.cue_s
    cols = ['probe_before', 'probe_after', 'labels', 'label_err_pct', 'actions', 'wrong_action_pct', 'invalid',
            'attempts', 'done', 'total_s']
    ps = d.groupby(['shift', 'p_dev', 'cond', 'subject'])[cols].mean()
    sm = ps.groupby(level=[0, 1, 2]).mean().reset_index()
    worst = ps.groupby(level=[0, 1, 2]).probe_after.min().reset_index(name='probe_after_worst_subject')
    sm = sm.merge(worst)
    sm.to_csv(os.path.join(OUT, 'task_sim_summary.csv'), index=False, float_format='%.4g')
    for (sh, pdv), g in sm.groupby(['shift', 'p_dev']):
        print(f'shift {sh}, deliberate deviations {pdv}')
        print(g.set_index('cond').loc[list(CONDS), cols + ['probe_after_worst_subject']].round(1).to_string())


if __name__ == '__main__':
    main()
