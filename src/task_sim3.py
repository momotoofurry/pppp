"""Does the task-label method only work in the task it was designed for? Weaker task structure (report 35.19).
PC only, exploratory. Same user / decoder / robot model as task_sim2.py, a more general pick-and-place world.

World: three places (home, A, B; durations as task_sim: home <-> A or B 1.75 s, A <-> B 3.5 s, gripper 1.0 s).
An object lies at one place; the user's goal is to bring it to a destination; then a new goal starts from where it
lies. Commands as before (Power = go to A, Pointer = go to B, Lateral = go home, Tripod = grip, Open = release).
The object can also be put down and picked up at home.
Task structure = what the SYSTEM knows about the goal (the user always knows it):
  fixed          the earlier task: object at A -> B, then the arm goes home and the object is put back at A.
                 The system knows every step.
  known_goal     source and destination random every time; the system is told the destination (for example on
                 a screen or by voice). It knows the next step.
  unknown_goal   random as above; the system sees where the object is (and remembers where it was picked up) but
                 does not know where it should go: while carrying, any place other than here and the source is a
                 plausible next move, and releasing is plausible anywhere except at the source.
  free           no task model: every currently valid command is plausible.
User deviations (p_dev per attempt): the user changes the destination (fixed: sends the arm home instead, as
before); the system is never told.
Labels from the task, with P = the plausible next gestures in the system's view:
  hard     the windows of a command are labelled with the command if it is in P; with the only element of P if it
           is not and P has one element; otherwise not labelled
  retro    hard, plus a retrospective rule: when a move made while carrying the object is directly followed by
           another move while carrying (nothing released in between), the first one is relabelled with the gesture of the second (the user went on to
           where they actually wanted); a command outside a larger P waits for the next executed command and takes
           its gesture if that one is plausible. Labels are therefore learned one command later.
  soft     q(g) ~ prior(g) x exp(beta x mean discriminant), prior: 1 - eps spread over P, eps over the other valid
           commands, p0 Rest, 0.01 invalid (eps 0.15, p0 0.05, beta 0.3 as task_sim2)
All with the activity gate (task_sim2 'act'). Learners: hard / retro with the gate rule (lda_robust), soft with
the plain sums. Conditions with one cued pass at every session (8 s) and without; references: fixed model,
cue1 alone, oracle labels.
Writes results/task_sim3.csv and task_sim3_summary.csv.
Usage (in the container): python src/task_sim3.py [--jobs 19]
"""
import argparse
import os
import sys
from collections import deque

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leaf_guard as LG  # noqa: E402
import leaf_sweep as LS  # noqa: E402
import lda_robust as LR  # noqa: E402
import pipeline as P  # noqa: E402
import task_sim as T  # noqa: E402
import task_sim2 as T2  # noqa: E402
import zscore_sweep as ZW  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
POWER, LATERAL, TRIPOD, POINTER, OPEN, REST = range(6)
GOTO = {'A': POWER, 'B': POINTER, 'home': LATERAL}
PLACE = {POWER: 'A', POINTER: 'B', LATERAL: 'home'}
MOVES = (POWER, POINTER, LATERAL)
PLACES = ('home', 'A', 'B')
STRUCTS = ['fixed', 'known_goal', 'unknown_goal', 'free']
METHODS = {
    'fixed_model': dict(), 'cue1': dict(cue=1), 'oracle': dict(labels='oracle'),
    'hard': dict(labels='hard'), 'retro': dict(labels='retro'), 'soft': dict(labels='soft'),
    'cue1_hard': dict(labels='hard', cue=1), 'cue1_retro': dict(labels='retro', cue=1),
    'cue1_soft': dict(labels='soft', cue=1),
}


class World:
    def __init__(self, struct, rng):
        self.struct, self.rng = struct, rng
        self.loc, self.hold, self.obj, self.cycles, self.need_home = 'home', 0, 'A', 0, False
        self.new_goal()

    def new_goal(self):
        if self.struct == 'fixed':
            self.obj, self.src, self.dst = 'A', 'A', 'B'
        else:
            self.src = self.obj
            self.dst = str(self.rng.choice([p for p in PLACES if p != self.obj]))
        self.dst_sys = self.dst                           # what the system was told / assumes

    def valid(self, c):
        if c in MOVES:
            return self.loc != PLACE[c]
        if c == TRIPOD:
            return (not self.hold) and self.loc == self.obj
        if c == OPEN:
            return bool(self.hold)
        return False

    def execute(self, c):
        if c in MOVES:
            new = PLACE[c]
            d = 18 if 'home' in (self.loc, new) else 35
            self.loc = new
            return d
        if c == TRIPOD:
            self.hold, self.obj = 1, 'gripper'
            self.src_sys = self.loc
        else:
            self.hold, self.obj = 0, self.loc
        return T.GRIP_WIN

    def _step(self, dst):
        if self.need_home:
            return LATERAL if self.loc != 'home' else REST
        if self.hold:
            return OPEN if self.loc == dst else GOTO[dst]
        if self.obj == dst:
            return REST
        return TRIPOD if self.loc == self.obj else GOTO[self.obj]

    def intent(self):
        return self._step(self.dst)

    def advance(self):
        if self.need_home and self.loc == 'home':
            self.need_home = False
            self.cycles += 1
            self.new_goal()
        elif not self.need_home and not self.hold and self.obj == self.dst:
            if self.struct == 'fixed':
                self.need_home = True
                if self.loc == 'home':
                    self.advance()
            else:
                self.cycles += 1
                self.new_goal()

    def deviate(self):
        """the user changes their mind; returns the gesture to make now"""
        if self.struct == 'fixed':
            return LATERAL if self.valid(LATERAL) else None
        if self.hold:
            others = [p for p in PLACES if p not in (self.dst, getattr(self, 'src_sys', self.src))]
            if others:
                self.dst = str(self.rng.choice(others))
        return None

    def plausible(self):
        if self.struct in ('fixed', 'known_goal'):
            g = self._step(self.dst_sys)
            return [g] if g != REST else []
        if self.struct == 'free':
            return [c for c in range(5) if self.valid(c)]
        if not self.hold:                                 # unknown_goal: the object is visible
            return [TRIPOD] if self.loc == self.obj else [GOTO[self.obj]]
        src = getattr(self, 'src_sys', self.src)
        out = [GOTO[p] for p in PLACES if p not in (self.loc, src)]
        if self.loc != src:
            out.append(OPEN)
        return out


def session(mdl, cfg, pools, apools, thr, rng, p_dev, struct):
    w = World(struct, rng)
    ptr = [0] * LS.K
    queue = deque()
    busy_until, t = 0, 0
    last, run, latched, run_rows = -1, 0, -1, []
    pend = None                                           # [plausible, rows, pred, true, attempt, valid, executed, carrying]
    held = None                                           # retro: [rows, label or None, is_move, true, plausible]
    st = dict(labels=0, wrong_labels=0, actions=0, wrong_actions=0, invalid=0, attempts=0, p_size=0, p_n=0)
    attempt = 0
    mode = cfg.get('labels')

    def take(c):
        k = ptr[c] % len(pools[c])
        ptr[c] += 1
        return pools[c][k], apools[c][k]

    def learn(rows, lab, true):
        st['labels'] += 1
        st['wrong_labels'] += int(lab != true)
        mdl.learn(rows, lab)

    def settle(new=None):
        """retro: resolve the held item with the next executed command `new` = (gesture, plausible) or at the end"""
        nonlocal held
        if held is None:
            return
        rows, lab, is_move, true, _ = held
        if new is not None:
            g, pl, carry = new
            if is_move and carry and g in MOVES:
                lab = g
            elif lab is None and g in pl:
                lab = g
        if lab is not None:
            learn(rows, lab, true)
        held = None

    def flush():
        nonlocal pend, held
        if pend is None or mode is None or len(pend[1]) < T.K_DC:
            pend = None
            return
        pl, rows, pred, true, _, valid, executed, carry = pend
        Z = np.stack(rows)
        pend = None
        if mode == 'oracle':
            return learn(Z, true, true)
        if mode == 'soft':
            prior = np.full(LS.K, T2.P_INVALID)
            others = [c for c in range(5) if valid[c] and c not in pl]
            for c in pl:
                prior[c] = (1 - T2.EPS) / len(pl)
            for c in others:
                prior[c] = T2.EPS / len(others) if pl else 1.0 / len(others)
            prior[REST] = T2.P0
            s = mdl.m.scores(Z).mean(0)
            q = prior * np.exp(T2.BETA * (s - s.max()))
            q /= q.sum()
            st['labels'] += 1
            st['wrong_labels'] += int(np.argmax(q) != true)
            return T2.learn_soft(mdl.m, Z, q)
        lab = pred if pred in pl else (pl[0] if len(pl) == 1 else None)
        if mode == 'hard':
            if lab is not None:
                learn(Z, lab, true)
            return
        held_new = [Z, lab, executed and pred in MOVES and carry, true, pl]
        if executed:
            settle((pred, pl, carry))
        if held is not None:                              # an older item that no command resolved
            settle()
        held = held_new

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
                if rng.random() < p_dev:
                    d = w.deviate()
                    g = d if d is not None else w.intent()
                if g == REST:
                    w.advance()
                    g = w.intent()
                    if g == REST:
                        t += 1
                        continue
                attempt += 1
                st['attempts'] += 1
                Zg, ag = take(g)
                queue.extend((r, a, g, attempt) for r, a in zip(Zg, ag))
                Zr, ar = take(REST)
                queue.extend((r, a, REST, -1) for r, a in zip(Zr[:5], ar[:5]))
        row, a, true, att = queue.popleft()
        busy = t < busy_until
        pred = int(np.argmax(mdl.scores(row[None])[0]))
        if a < thr:
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
                pl = w.plausible()
                st['p_size'] += len(pl)
                st['p_n'] += 1
                valid = [w.valid(c) for c in range(5)]
                ex = valid[pred]
                carry = bool(w.hold)
                if ex:
                    st['actions'] += 1
                    st['wrong_actions'] += int(pred != true)
                    busy_until = t + w.execute(pred)
                else:
                    st['invalid'] += 1
                pend = [pl, list(run_rows), pred, true, att, valid, ex, carry]
        t += 1
    flush()
    settle()
    st.update(cycles=w.cycles, seconds=t / 10)
    return st


def job(subject, shift, p_dev, seed, struct):
    Xc_raw, yc, blocks, _ = ZW.load('arm_position', subject, shift)
    yc = yc.astype(np.int64)
    mu, sd = Xc_raw.mean(0), Xc_raw.std(0)
    Zc = (Xc_raw - mu) / sd
    act_c = Xc_raw[:, T2.MAV].sum(1)
    med = [np.median(act_c[yc == c]) for c in range(LS.K)]
    thr = float(np.sqrt(med[REST] * min(med[:5])))
    out = []
    for name, cfg in METHODS.items():
        rng = np.random.default_rng(seed * 100003 + subject * 7 + STRUCTS.index(struct))
        mdl = LR.make('plain' if cfg.get('labels') in ('soft', None, 'oracle') else 'gate', Zc, yc)
        for b, (X, y) in enumerate(blocks):
            y = np.asarray(y).astype(np.int64)
            X = np.asarray(X, dtype=np.float64)
            Z = (X - mu) / sd
            A = X[:, T2.MAV].sum(1)
            tr = [LG.trials(y, c) for c in range(LS.K)]
            pools = [[Z[i] for i in tr[c][:3]] for c in range(LS.K)]
            apools = [[A[i] for i in tr[c][:3]] for c in range(LS.K)]
            pi = np.concatenate([i for c in range(LS.K) for i in tr[c][3:5]])
            for k in range(cfg.get('cue', 0)):
                for c in range(LS.K):
                    mdl.learn(pools[c][k], c)
            st = session(mdl, cfg, pools, apools, thr, rng, p_dev, struct)
            out.append(dict(subject=subject, shift=shift, p_dev=p_dev, seed=seed, struct=struct, cond=name, block=b,
                            probe_after=T.probe(mdl, Z[pi], y[pi]), cue_s=8.0 * cfg.get('cue', 0), **st))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    args = ap.parse_args()
    import check_features_c as FC
    import task_sim3 as M
    FC.lib()
    pd.set_option('display.width', 250)
    tasks = [delayed(M.job)(s, sh, 0.1, seed, st) for st in STRUCTS for sh in (0.0, 0.5) for seed in (0, 1)
             for s in range(20)]
    df = pd.DataFrame([r for rs in Parallel(n_jobs=args.jobs, verbose=5)(tasks) for r in rs])
    df.to_csv(os.path.join(OUT, 'task_sim3.csv'), index=False, float_format='%.4g')
    d = df[df.block >= 1].copy()
    d['label_err_pct'] = d.wrong_labels / d.labels.clip(lower=1) * 100
    d['labels_per_action'] = d.labels / d.actions.clip(lower=1)
    d['wrong_action_pct'] = d.wrong_actions / d.actions.clip(lower=1) * 100
    d['p_size'] = d.p_size / d.p_n.clip(lower=1)
    d['done'] = (d.cycles >= T.N_CYCLES) * 100
    cols = ['probe_after', 'label_err_pct', 'labels_per_action', 'wrong_action_pct', 'p_size', 'done']
    ps = d.groupby(['struct', 'shift', 'cond', 'subject'])[cols].mean()
    sm = ps.groupby(level=[0, 1, 2]).mean().reset_index()
    sm = sm.merge(ps.groupby(level=[0, 1, 2]).probe_after.min().reset_index(name='worst_subject'))
    sm.to_csv(os.path.join(OUT, 'task_sim3_summary.csv'), index=False, float_format='%.4g')
    for sh in (0.0, 0.5):
        print(f'shift {sh}: probe accuracy after the session (%)')
        print(sm[sm['shift'] == sh].pivot(index='cond', columns='struct', values='probe_after')
              .loc[list(METHODS), STRUCTS].round(1).to_string())
        print('label error (%)')
        print(sm[sm['shift'] == sh].pivot(index='cond', columns='struct', values='label_err_pct')
              .loc[[m for m in METHODS if 'labels' in METHODS[m] and m != 'oracle'], STRUCTS].round(1).to_string())
        print('labels per executed action')
        print(sm[sm['shift'] == sh].pivot(index='cond', columns='struct', values='labels_per_action')
              .loc[[m for m in METHODS if 'labels' in METHODS[m] and m != 'oracle'], STRUCTS].round(2).to_string())
    print('plausible set size:', sm.groupby('struct').p_size.mean().round(2).to_dict())
    k = ps.xs(0.5, level='shift').probe_after.unstack('cond')
    for s in STRUCTS:
        for a, b in (('cue1_retro', 'cue1'), ('cue1_soft', 'cue1'), ('cue1_hard', 'cue1'), ('retro', 'hard')):
            dd = k.loc[s][a] - k.loc[s][b]
            m, lo, hi = LS.ci(dd)
            print(f'shift 0.5 {s:13s} {a} - {b} = {m:+.2f} ({lo:+.2f}, {hi:+.2f})')


if __name__ == '__main__':
    main()
