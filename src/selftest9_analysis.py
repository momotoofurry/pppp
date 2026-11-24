"""Self-test with the 9 directional gestures (report 35.45, 35.48, 35.49; 2026-11-17): how many gestures can 4 sensors
carry, and do task soft labels help with 9 gestures?

Recording (SOP 3B / 4A, panel gesture set "9 方向", files <subj>_d<day>_G_*): TrignoBridge run --firmware lda --classes 9
(board: rtl_task_9c2), TWO cued passes of the 9 gestures (cal 0-8 twice, 4 s each, then calibrate; 35.48, decided
before recording after the DB2 simulation 35.47), then TaskScreen --gestures nine --segments
labelled,task,labelled,task,labelled --reps 3 --n 40 --postures selftest (35.49):
  P0  labelled 1 (neutral posture): 3 x 9 cues of 2 s, random order
  T1  task 1: 40 cued arm commands (up down left right forward back grip_open grip_close, 5 each, random order)
  P1  labelled 2 (A then B)
  T2  task 2: 40 cued commands
  P2  labelled 3 (C then A)
The board is not taught during the recording; the task labels are replayed offline (as selftest_analysis).

Gestures (class order of the firmware; Rest last):
  0 WristExt (up)  1 WristFlex (down)  2 RadialDev (left)  3 UlnarDev (right)  4 Point (forward)  5 ThumbUp (back)
  6 HandOpen (gripper open)  7 Fist (gripper close)  8 Rest (stop)
Gesture sets compared on the SAME recording (each one is a separate model, as if the board had been built for it):
  S9  all 9
  S7  without Point and ThumbUp (the single-finger gestures): 4 wrist directions + HandOpen + Fist + Rest
  S5  the 4 wrist directions + Rest (a mode switch would carry the rest of the commands)

Model per set and day, as on the board (rt_lda.c): the cued windows of the set's gestures (every accepted 'cal g'
before the first segment, both passes and any redo, the last 30 windows of each = windows 9..38 after its stream reset,
like the board's buffer) give the z-score of the session (mean, population SD); Q5.10; running sums (no forgetting in
the cued pass, ld_add); OAS-shrunk pooled covariance LDA with equal priors (lda_robust.oas_solve). Test = the probe
cues whose gesture is in the set: the middle 10 windows of [cue_on + 0.5 s, cue_off] (selftest_analysis.mid / inside),
argmax over the set's classes.

Conditions (offline replay in time order):
  cue       the model of the cued pass, never changed
  cue_soft  + one soft task label per task trial whose target gesture is in the set, as RTL_TASK_LABEL: the trial's
            windows [trial_on, trial_off + 0.5 s]; the first run of 3 equal non-Rest predictions (K_DC) = the command,
            its rows = that run extended while the prediction stays; prior: expected 1 - EPS, the other commands of
            the set share EPS, Rest P0; q ~ prior x exp(BETA x mean discriminant over the rows); forget 0.97
            (ld_decay), add the rows with q (ld_add_soft), refit. EPS 0.15, P0 0.05, BETA 0.3 (rt_lda.h).

Rule 1 (35.45; the gesture set), fixed before the recording, n = 1 self-test, picks the set of the next experiment:
  A(S) = cue-condition window accuracy over all probe windows of the set (P0-P2 pooled), per day, mean over days.
  Choose the LARGEST set with A(S) >= 85 %; if none, the set with the highest A(S), and revise placement / gestures.
Rule 2 (35.49; soft labels with 9 gestures), fixed before the recording, same rule as R12 of selftest_analysis:
  D(S9) = mean over P1 and P2 of (cue_soft - cue) window accuracy, per day; D_bar = mean over days.
  GO if D_bar >= +2 points and D > 0 on at least ceil(2/3 x days) days; else NO-GO. S7 and S5 reported, not decided.
Rule 3 (35.53; accumulation across donnings), fixed before the first 9-gesture recording (2026-11-17), needs >= 2 days
with the same placement:
  acc = one model carried across the days as on the board: day 1 = its cued pass; each later day its own z-score from
  its cued windows, which are ADDED to the running sums (Model.new_session); no task labels. cue = that day's cued
  pass only. Per later day d: D3_d = A_acc - A_cue, A = window accuracy over all probe windows (P0-P2 pooled), S9.
  GO if mean D3 >= +2 points and D3 > 0 on at least ceil(2/3 x (days - 1)) later days; else NO-GO.
  Reported, not decided: S7, S5, and acc_soft (acc + every day's soft labels) - cue.
Comparison groups added 2026-11-22 (35.74), reported only; rules 1-3 are computed exactly as before:
  fixed     no recalibration: the day-1 model, with day 1's z-score, used unchanged on each later day's probes
  cue_self  self-training: as cue_soft, but the expected command of the prior is the model's OWN decided command
            (first run of K_DC equal non-Rest predictions), not the cued one: same amount of extra data, no task
            information. Answers whether cue_soft's gain comes from the task information or just from more windows.
  acc_self  acc + self-training labels every day (vs acc_soft)
Also reported: the board's real-time commands in the task segments (cued-pass model): right / wrong / none and the
latency from the cue to the first command (TaskScreen latency_ms, median and quartiles; includes the user's reaction).
Also reported: per probe, cue-level majority accuracy, bootstrap 95 % intervals over cues (2000 resamples), per-class
recall and the 9-class confusion matrix (cue), chance 1 / |S|, offline command accuracy in the task trials, and the
same with --cal-s 2 (first 2 s of each cue).

usage: python src/selftest9_analysis.py --dir D:/selftest_data/T00 --days T00_d1_G [T00_d2_G ...] [--out ...] [--cal-s 4]
       [--sets S9 S7 S5]
  --sets (report 35.80): the sets to analyse, largest first; the recording needs cued windows of their gestures only.
  S7 recordings (panel set S7, files <subj>_d<day>_S_*, firmware rtl_task_s7b with TrignoBridge --preset s7; Point /
  ThumbUp are not cued): --sets S7 (S5 may be added). Rules 1-3 were pre-registered for the 9-gesture days (S9); with
  --sets without S9 the same numbers are printed as a report, not as the pre-registered decisions. The board's real-time
  line is then the S7 firmware (gate, k 5, stop k 2), not the cued-pass S9 model.
  (each day's files are read from <dir>/<day>/ if that folder has them (the panel's per-day folders, 35.75), else <dir>/)
"""
import argparse
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lda_robust as LR  # noqa: E402
import selftest_analysis as SA  # noqa: E402  (load_emg, features, inside, mid, q16, timing constants)

GESTURES = ['WristExt', 'WristFlex', 'RadialDev', 'UlnarDev', 'Point', 'ThumbUp', 'HandOpen', 'Fist', 'Rest']
G = {g: i for i, g in enumerate(GESTURES)}
COMMAND = {'up': 'WristExt', 'down': 'WristFlex', 'left': 'RadialDev', 'right': 'UlnarDev', 'forward': 'Point',
           'back': 'ThumbUp', 'grip_open': 'HandOpen', 'grip_close': 'Fist'}
REST = G['Rest']
SETS = {
    'S9': list(range(9)),
    'S7': [G[g] for g in ('WristExt', 'WristFlex', 'RadialDev', 'UlnarDev', 'HandOpen', 'Fist', 'Rest')],
    'S5': [G[g] for g in ('WristExt', 'WristFlex', 'RadialDev', 'UlnarDev', 'Rest')],
}
ORDER = ['S9', 'S7', 'S5']                      # largest first
THRESHOLD = 85.0
FS, WIN, STEP, WARMUP, REACT_S, HOLD_S, K_DC = SA.FS, SA.WIN, SA.STEP, SA.WARMUP, SA.REACT_S, SA.HOLD_S, SA.K_DC
EPS, P0, BETA, DECAY = 0.15, 0.05, 0.3, 0.97


def day_folder(folder, name):
    """35.75: the panel saves each day in <dir>/<name>/; older recordings are all in <dir>/"""
    sub = os.path.join(folder, name)
    return sub if os.path.isfile(os.path.join(sub, f'{name}_emg.csv')) else folder


def load_day(folder, name, cal_s, need=frozenset(range(9))):
    folder = day_folder(folder, name)
    X, t0, rate = SA.load_emg(os.path.join(folder, f'{name}_emg.csv'))
    F = SA.features(X)
    nw = len(F)
    ops = pd.read_csv(os.path.join(folder, f'{name}_ops.csv'))
    task = pd.read_csv(os.path.join(folder, f'{name}_task.csv'), dtype=str, keep_default_na=False)
    task['t'] = task.unix_ms.astype(float)
    first_seg = task.loc[task.event == 'seg_start', 't'].min()
    cal_nw = int(round((cal_s * FS - WIN) / STEP)) + 1 - WARMUP
    cue_rows, cue_lab = [], []
    seen = set()
    for r in ops.itertuples():
        c = str(r.command).split()
        if len(c) == 2 and c[0] == 'cal' and c[1].isdigit() and r.unix_ms < first_seg and str(r.accepted) not in ('0', 'False'):
            g = int(c[1])
            rows = SA.inside(t0, nw, float(r.unix_ms), float(r.unix_ms) + cal_s * 1000)[-cal_nw:]
            cue_rows.append(rows)
            cue_lab.append(np.full(len(rows), g))
            seen.add(g)
    assert set(need) <= seen, f'{name}: cued pass incomplete, cal rows for {sorted(seen)}, needs {sorted(need)}'
    runs, cur = {}, None
    for r in task.itertuples():
        if r.event == 'seg_start':
            cur = dict(idx=int(r.text), seg=r.segment, rows=[])
        elif cur is not None:
            cur['rows'].append(r)
            if r.event == 'seg_end':
                runs[cur['idx']] = cur
                cur = None
            elif r.event == 'seg_abort':
                cur = None
    probes, events = [], []                      # events: (time, 'probe', k) / (time, 'trial', (rows, class))
    for idx in sorted(runs):
        run = runs[idx]
        on = {}
        if run['seg'] == 'labelled':
            items = []
            for r in run['rows']:
                if r.event == 'cue_on':
                    on[r.step] = r
                elif r.event == 'cue_off' and r.step in on:
                    w = SA.mid(SA.inside(t0, nw, on[r.step].t + REACT_S * 1000, r.t))
                    if len(w):
                        items.append((w, G[r.target]))
            events.append((run['rows'][-1].t, 'probe', len(probes)))
            probes.append(items)
        elif run['seg'] == 'task':
            for r in run['rows']:
                if r.event == 'trial_on':
                    on[r.step] = r
                elif r.event == 'trial_off' and r.step in on and r.target in COMMAND:
                    w = SA.inside(t0, nw, on[r.step].t, r.t + HOLD_S * 1000)
                    if len(w) >= K_DC:
                        events.append((on[r.step].t, 'trial', (w, G[COMMAND[r.target]])))
    events.sort(key=lambda e: e[0])
    # the board's own real-time commands in the task (cued-pass model, TaskScreen trial_end: result, latency_ms from
    # the cue to the first command)
    live = [(r.result, float(r.latency_ms)) if r.latency_ms not in ('', 'nan') else (r.result, np.nan)
            for r in task.itertuples() if r.event == 'trial_end' and r.segment == 'task']
    s7fw = any(str(c).strip() == 'preset s7' for c in ops.command)    # 35.80: recorded with the S7 firmware settings
    return dict(name=name, F=F, cal_rows=np.concatenate(cue_rows), cal_lab=np.concatenate(cue_lab), probes=probes, s7fw=s7fw,
                events=events, rate=rate, cal_counts=np.bincount(np.concatenate(cue_lab), minlength=9),
                trials=sum(e[1] == 'trial' for e in events), live=live)


class Model:
    """the board's running sums (ldacal.c) over the classes of one set, in the session's z-scored Q5.10 space"""

    def __init__(self, F, rows, lab, classes):
        self.classes = list(classes)
        keep = np.isin(lab, classes)
        Xc, yc = F[rows[keep]], lab[keep]
        self.mu, sd = Xc.mean(0), Xc.std(0)
        self.inv = np.where(sd > 0, 1.0 / np.where(sd > 0, sd, 1.0), 0.0)
        Zq = self.z(Xc)
        K = len(classes)
        idx = np.array([self.classes.index(c) for c in yc])
        self.n = np.bincount(idx, minlength=K).astype(float)
        self.s = np.zeros((K, Zq.shape[1]))
        np.add.at(self.s, idx, Zq)
        self.G = Zq.T @ Zq
        self.fit()

    def new_session(self, F, rows, lab):
        """next donning, as the board: the session's z-score from its own cued windows, which are ADDED to the running
        sums kept from earlier days (no forgetting between days), then refit"""
        keep = np.isin(lab, self.classes)
        Xc, yc = F[rows[keep]], lab[keep]
        self.mu, sd = Xc.mean(0), Xc.std(0)
        self.inv = np.where(sd > 0, 1.0 / np.where(sd > 0, sd, 1.0), 0.0)
        Zq = self.z(Xc)
        idx = np.array([self.classes.index(c) for c in yc])
        self.n = self.n + np.bincount(idx, minlength=len(self.classes))
        np.add.at(self.s, idx, Zq)
        self.G = self.G + Zq.T @ Zq
        self.fit()

    def z(self, X):
        return SA.q16((X - self.mu) * self.inv)

    def fit(self):
        m = self.s / np.maximum(self.n, 1e-9)[:, None]
        N = self.n.sum()
        self.w, self.b = LR.oas_solve((self.G - (m.T * self.n) @ m) / N, N, m)

    def scores(self, X):
        return self.z(X) @ self.w.T + self.b

    def predict(self, X):
        return np.array(self.classes)[np.argmax(self.scores(X), 1)]

    def soft(self, X, expected):
        """one task label (RTL_TASK_LABEL): prior x exp(beta x mean discriminant), forget, add with q, refit"""
        K = len(self.classes)
        others = [c for c in self.classes if c not in (expected, REST)]
        prior = np.array([1 - EPS if c == expected else P0 if c == REST else EPS / max(len(others), 1)
                          for c in self.classes])
        s = self.scores(X).mean(0)
        q = prior * np.exp(BETA * (s - s.max()))
        q /= q.sum()
        Zq = self.z(X)
        self.G = DECAY * self.G + Zq.T @ Zq
        self.s = DECAY * self.s + np.outer(q, Zq.sum(0))
        self.n = DECAY * self.n + q * len(Zq)
        assert len(q) == K
        self.fit()


def decide(mdl, X):
    pr = mdl.predict(X)
    j = next((i for i in range(len(pr) - K_DC + 1) if pr[i] != REST and (pr[i:i + K_DC] == pr[i]).all()), None)
    if j is None:
        return None, None
    end = j
    while end + 1 < len(pr) and pr[end + 1] == pr[j]:
        end += 1
    return int(pr[j]), X[j:end + 1]


def replay(day, sname, cond):
    """-> per probe a list of (cue, true, preds); command counts in the task trials"""
    mdl = Model(day['F'], day['cal_rows'], day['cal_lab'], SETS[sname])
    return run_day(day, SETS[sname], mdl, cond in ('cue_soft', 'cue_self'), 'self' if cond == 'cue_self' else 'task')


def replay_days(days, sname, soft, label='task'):
    """rule 3: one model carried across the days (acc / acc_soft / acc_self); -> per day the run_day result"""
    out, mdl = [], None
    for day in days:
        if mdl is None:
            mdl = Model(day['F'], day['cal_rows'], day['cal_lab'], SETS[sname])
        else:
            mdl.new_session(day['F'], day['cal_rows'], day['cal_lab'])
        out.append(run_day(day, SETS[sname], mdl, soft, label))
    return out


def replay_fixed(days, sname):
    """35.74 'fixed': the day-1 model (and day 1's z-score) never changed; -> per later day the run_day result"""
    mdl = Model(days[0]['F'], days[0]['cal_rows'], days[0]['cal_lab'], SETS[sname])
    return [run_day(day, SETS[sname], mdl, False) for day in days[1:]]


def run_day(day, classes, mdl, soft, label='task'):
    """label: 'task' = the cued command is the prior's expected command (cue_soft); 'self' = the model's own
    decided command (self-training, 35.74)"""
    F = day['F']
    cond = 'cue_soft' if soft else 'cue'
    probes = {}
    cmd = dict(trials=0, cmd=0, ok=0, miss=0)
    for _, kind, pay in day['events']:
        if kind == 'probe':
            probes[pay] = [(ci, g, mdl.predict(F[w])) for ci, (w, g) in enumerate(day['probes'][pay]) if g in classes]
        elif kind == 'trial':
            w, g = pay
            if g not in classes:
                continue
            cmd['trials'] += 1
            pred, X = decide(mdl, F[w])
            if pred is None:
                cmd['miss'] += 1
                continue
            cmd['cmd'] += 1
            cmd['ok'] += int(pred == g)
            if cond == 'cue_soft':
                mdl.soft(X, g if label == 'task' else pred)
    return [probes[k] for k in sorted(probes)], cmd


def win_acc(items):
    return 100 * np.concatenate([pr == g for _, g, pr in items]).mean() if items else float('nan')


def summarize(items, rng):
    cue = np.array([np.mean(pr == g) for _, g, pr in items])
    maj = np.array([np.bincount(pr, minlength=9).argmax() == g for _, g, pr in items])
    boot = [cue[rng.integers(0, len(cue), len(cue))].mean() for _ in range(2000)]
    return win_acc(items), 100 * maj.mean(), 100 * np.percentile(boot, 2.5), 100 * np.percentile(boot, 97.5)


def boot_d(soft, cue, rng, n=2000):
    """bootstrap over the cues of P1 and P2: D = mean over the two probes of (acc_soft - acc_cue)"""
    ds = []
    for _ in range(n):
        v = []
        for ps, pc in zip(soft, cue):
            k = rng.integers(0, len(ps), len(ps))
            a = np.concatenate([ps[i][2] == ps[i][1] for i in k]).mean()
            b = np.concatenate([pc[i][2] == pc[i][1] for i in k]).mean()
            v.append(100 * (a - b))
        ds.append(np.mean(v))
    return np.percentile(ds, [2.5, 97.5])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--days', nargs='+', required=True)
    ap.add_argument('--out', default=None)
    ap.add_argument('--cal-s', type=float, default=4.0)
    ap.add_argument('--sets', nargs='+', default=ORDER, choices=ORDER)
    args = ap.parse_args()
    run = [s for s in ORDER if s in args.sets]                 # largest first
    pre = 'S9' in run                                          # the pre-registered analysis of the 9-gesture days
    lead = run[0]
    need = frozenset(c for s_ in run for c in SETS[s_])
    lines = []

    def p(s=''):
        print(s, flush=True)
        lines.append(s)

    rng = np.random.default_rng(0)
    days = [load_day(args.dir, n, args.cal_s, need) for n in args.days]
    p(f'cued pass: first {args.cal_s:g} s of each cue; rule 1 threshold {THRESHOLD:g} %, rule 2 D_bar >= +2 (pre-registered)'
      + ('' if pre else f'; sets {" ".join(run)}: reported, not the pre-registered decisions (those were for S9)'))
    for d in days:
        p(f"{d['name']}: rate {d['rate']:.1f} Hz, cued windows per gesture {d['cal_counts'].tolist()}, "
          f"probes {len(d['probes'])} with {[len(x) for x in d['probes']]} cues, task trials {d['trials']}")
    A = {s: [] for s in run}
    D = {s: [] for s in run}
    for d in days:
        p(f"\n== {d['name']}")
        p('rule 1, condition cue')
        p('set  classes  chance   window acc %   cue-majority %   95 % CI (cues)   per probe (window %)')
        res = {}
        for s in run:
            res[s] = {c: replay(d, s, c) for c in ('cue', 'cue_soft', 'cue_self')}
            pr_cue = res[s]['cue'][0]
            allc = [x for pr in pr_cue for x in pr]
            wa, ma, lo, hi = summarize(allc, rng)
            A[s].append(wa)
            p(f"{s}   {len(SETS[s]):7d}  {100 / len(SETS[s]):5.1f}   {wa:12.1f}   {ma:14.1f}   {lo:6.1f} - {hi:5.1f}    "
              + '  '.join(f'P{k} {win_acc(x):5.1f}' for k, x in enumerate(pr_cue)))
        cm = np.zeros((9, 9), int)
        for pr in res[lead]['cue'][0]:
            for _, g, pred in pr:
                np.add.at(cm[g], pred, 1)
        cl = SETS[lead]
        gl = [GESTURES[c] for c in cl]
        p(f'\n{lead} confusion, cue (rows = cued gesture, columns = predicted; windows)')
        p(pd.DataFrame(cm[np.ix_(cl, cl)], index=gl, columns=[g[:6] for g in gl]).to_string())
        rec = 100 * np.diag(cm)[cl] / np.maximum(cm[cl].sum(1), 1)
        p(f'{lead} recall %: ' + ', '.join(f'{g} {r:.0f}' for g, r in zip(gl, rec)))
        p('\nrule 2: probe window accuracy % (cue -> cue_soft), D = mean over P1, P2 of (cue_soft - cue)')
        for s in run:
            pc, ps = res[s]['cue'][0], res[s]['cue_soft'][0]
            if len(pc) < 3:
                p(f'{s}: fewer than 3 probes, no D')
                continue
            dd = np.mean([win_acc(ps[k]) - win_acc(pc[k]) for k in (1, 2)])
            lo, hi = boot_d([ps[1], ps[2]], [pc[1], pc[2]], rng)
            D[s].append(dd)
            p(f"{s}: " + '  '.join(f'P{k} {win_acc(pc[k]):5.1f} -> {win_acc(ps[k]):5.1f}' for k in range(len(pc)))
              + f'   D = {dd:+.2f} (bootstrap 95 % {lo:+.2f}, {hi:+.2f})')
        p('(reported, not decided; 35.74) self-training: probe window accuracy % (cue -> cue_self), '
          'D_self = mean over P1, P2 of (cue_self - cue); D - D_self = what the task information adds')
        for s in run:
            pc, pf = res[s]['cue'][0], res[s]['cue_self'][0]
            if len(pc) < 3:
                continue
            dself = np.mean([win_acc(pf[k]) - win_acc(pc[k]) for k in (1, 2)])
            dtask = np.mean([win_acc(res[s]['cue_soft'][0][k]) - win_acc(pc[k]) for k in (1, 2)])
            p(f"{s}: " + '  '.join(f'P{k} {win_acc(pc[k]):5.1f} -> {win_acc(pf[k]):5.1f}' for k in range(len(pc)))
              + f'   D_self = {dself:+.2f}, D - D_self = {dtask - dself:+.2f}')
        p('\noffline commands in the task trials (first run of 3 equal non-Rest windows)')
        for s in run:
            for c in ('cue', 'cue_soft', 'cue_self'):
                m = res[s][c][1]
                p(f"{s} {c:8s}: trials {m['trials']}, commands {m['cmd']}, right {m['ok']}, none {m['miss']}, "
                  f"command accuracy {100 * m['ok'] / max(m['cmd'], 1):.1f} %")
        live = d['live']
        if live:
            res_n = {r: sum(1 for x, _ in live if x == r) for r in sorted({x for x, _ in live})}
            lat_all = np.array([v for _, v in live if np.isfinite(v)])
            lat_ok = np.array([v for x, v in live if x == 'success' and np.isfinite(v)])
            q = lambda a: f'median {np.median(a):.0f} ms (quartiles {np.percentile(a, 25):.0f}-{np.percentile(a, 75):.0f})' if len(a) else 'none'  # noqa: E731
            p(f"\nboard's real-time commands in the task ("
              + ('S7 firmware: gate, k 5, stop k 2' if d['s7fw'] else 'cued-pass model, S9') + '): '
              + ', '.join(f'{k} {v}' for k, v in res_n.items())
              + f' of {len(live)}')
            p(f'  latency cue -> first command: all commands {q(lat_all)}; right commands {q(lat_ok)}')
    mean = {s: float(np.mean(A[s])) for s in run}
    ok = [s for s in run if mean[s] >= THRESHOLD]
    tag = 'RULE 1 DECISION (pre-registered)' if pre else f'rule 1 as a report (sets {" ".join(run)})'
    p('\nrule 1, mean over days: ' + ', '.join(f'{s} {mean[s]:.1f} %' for s in run))
    if ok:
        p(f'{tag}: {ok[0]} ({len(SETS[ok[0]])} gestures) is the largest set with A >= {THRESHOLD:g} %')
    else:
        best = max(run, key=lambda s: mean[s])
        p(f'{tag}: no set reaches {THRESHOLD:g} %; best is {best} ({mean[best]:.1f} %): '
          'revise placement / gestures before the arm experiment')
    if not pre:
        for s in run:
            if D[s]:
                p(f'rule 2 as a report: {s} D_bar = {np.mean(D[s]):+.2f}, positive on {sum(x > 0 for x in D[s])}/{len(D[s])} days')
    if pre and D['S9']:
        dbar = float(np.mean(D['S9']))
        pos = sum(x > 0 for x in D['S9'])
        need = math.ceil(2 / 3 * len(D['S9']))
        verdict = 'GO' if dbar >= 2.0 and pos >= need else 'NO-GO'
        p(f'RULE 2 DECISION (pre-registered): S9 D_bar = {dbar:+.2f}, positive on {pos}/{len(D["S9"])} days '
          f'(need {need}) -> {verdict}')
    if len(days) >= 2:
        p('\nrule 3: accumulation across donnings; pooled probe window accuracy % on each later day')
        D3 = {}
        for s in run:
            cue = [win_acc([x for pr in replay(dd, s, 'cue')[0] for x in pr]) for dd in days]
            acc = [win_acc([x for pr in r[0] for x in pr]) for r in replay_days(days, s, False)]
            accs = [win_acc([x for pr in r[0] for x in pr]) for r in replay_days(days, s, True)]
            accf = [win_acc([x for pr in r[0] for x in pr]) for r in replay_days(days, s, True, 'self')]
            fix = [float('nan')] + [win_acc([x for pr in r[0] for x in pr]) for r in replay_fixed(days, s)]
            D3[s] = [acc[k] - cue[k] for k in range(1, len(days))]
            p(f'{s}: ' + '  '.join(f"{days[k]['name']}: cue {cue[k]:5.1f}, acc {acc[k]:5.1f}, acc_soft {accs[k]:5.1f}"
                                   for k in range(1, len(days)))
              + f'   D3 = {np.mean(D3[s]):+.2f}, acc_soft - cue {np.mean([accs[k] - cue[k] for k in range(1, len(days))]):+.2f}')
            later = range(1, len(days))
            p(f'    (reported, not decided; 35.74) ' + '  '.join(f"{days[k]['name']}: fixed {fix[k]:5.1f}, "
                                                                f"acc_self {accf[k]:5.1f}" for k in later)
              + f'   cue - fixed {np.mean([cue[k] - fix[k] for k in later]):+.2f}, '
              f'acc_soft - acc_self {np.mean([accs[k] - accf[k] for k in later]):+.2f}')
        if pre:
            dbar = float(np.mean(D3['S9']))
            pos = sum(x > 0 for x in D3['S9'])
            need3 = math.ceil(2 / 3 * len(D3['S9']))
            p(f"RULE 3 DECISION (pre-registered): S9 mean D3 = {dbar:+.2f}, positive on {pos}/{len(D3['S9'])} later days "
              f"(need {need3}) -> {'GO' if dbar >= 2.0 and pos >= need3 else 'NO-GO'}")
            for s in ('S7', 'S5'):
                if s in D and D[s]:
                    p(f'   (reported, not decided) {s} D_bar = {np.mean(D[s]):+.2f}')
        else:
            for s in run:
                p(f'rule 3 as a report: {s} mean D3 = {np.mean(D3[s]):+.2f}, positive on '
                  f'{sum(x > 0 for x in D3[s])}/{len(D3[s])} later days')
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, f'selftest9_cal{args.cal_s:g}.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
