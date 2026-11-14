"""Self-test analysis (report 35.35): do task labels help LATER commands of the SAME donning when the gestures are
interleaved? PC only, offline replay of the recorded raw EMG. Written and committed BEFORE the first recording.

Recording (SELFTEST.md): per day, one donning. TrignoBridge.exe run --firmware lda (raw EMG -> <name>_emg.csv,
typed commands -> <name>_ops.csv); the cued pass is typed in the bridge: cal 0 ... cal 5 (2 s each), calibrate;
then TaskScreen --segments labelled,task,labelled,task,labelled --reps 2 --n 40 (-> <name>_task.csv):
  P0  labelled segment 1: every gesture twice, random order  (right after the cued pass)
  T1  task segment 1: 40 cued commands (pose_A grip pose_B release home, balanced, random order)
  P1  labelled segment 2
  T2  task segment 2: 40 cued commands
  P2  labelled segment 3
Live, the board runs the cued-pass model only; all conditions below are computed offline from the same recording.
Arm posture (SELFTEST.md, fixed with this rule): the cued pass and P0 with the forearm resting on the table (neutral);
T1, P1, T2, P2 in the postures of robot use (reaching forward / raised), changed every 10 trials or cues. Without
this, one donning in one posture tends to sit at the ceiling (the synthetic dry run: 85-100 % right after the pass).

Signal path offline: emg.csv (unix_ms, frame, ch0_V..ch7_V at the TCU's rate) -> rate from a line fit of unix_ms on
the frame number -> resampled to 2000 Hz (scipy resample_poly; the bridge uses a windowed sinc, so the samples are
not bit-equal to what the board saw) -> src/c/features.c streamed over the whole session (window w = samples
200 w .. 200 w + 399) -> z-score (two modes, below) -> Q5.10 -> shrinkage LDA from running sums (OAS), forgetting 0.97 per learned trial, 6 classes
(Power Lateral Tripod Pointer Open Rest, the label order of TaskScreen and decision.c).
Windows used:
  cued pass   'cal g' rows of ops.csv (the last one per gesture before the first TaskScreen segment): windows
              wholly inside [t, t + 2 s], the last 10 (as the 2 s recordings of arm_position, windows 9-18)
  probes      cue_on .. cue_off of the labelled segments: windows wholly inside [cue_on + 0.5 s, cue_off], the
              central 10 (0.5 s for the reaction)
  task trials trial_on .. trial_off + 0.5 s of the task segments (TaskScreen ends a trial at the board's first
              command, so the gesture usually goes on a little): all windows wholly inside; the offline decision = the first
              run of 3 equal non-rest predictions (task_sim K_DC); its rows = that run extended while the prediction
              stays; no decision -> no label. Expected gesture = the trial's target (command -> gesture as
              TaskScreen / decision.c: pose_A Power, home Lateral, grip Tripod, pose_B Pointer, release Open);
              with probability e replaced by a random other command's gesture (sensitivity, 20 seeds).
Only completed segment runs are used (seg_end; the last completed run of each segment index).
z-score, two modes (added 2026-11-14, before any recording):
  session    the statistics of THIS day's cued pass (mu, sd of its 60 windows): what the firmware does (rt_lda.c
             recomputes them at every FIT; the running sums keep the rows of earlier days in their own day's
             z-score)                                                         <- PRIMARY for R12
  day1       the statistics of day 1's cued pass, fixed afterwards (what the offline analyses so far did: db6_sim,
             task_sim*); reported as a sensitivity analysis
Conditions (events processed in recorded time order; every day starts from the state the previous day ended in):
  fixed      day 1's cued-pass model, never updated (inputs in the mode's z-score)
  cue        + every day's cued pass (running sums, kept across days)          <- what runs live
  cue_soft   + soft task labels (task_sim2: prior expected 1 - eps, the other 4 commands eps / 4, Rest p0;
             q = prior x exp(beta x mean score))
  cue_pn     + hard labels (P+N-CIIL); cue_pos  + only labels whose prediction equals the expected (P-CIIL)
  cue_soft_t1  soft labels from T1 only, frozen after T1 (P2 then measures labels 5-10 min old)
Scores: accuracy over the probe windows of P0, P1, P2 with the model state at that time.
Decision rule, fixed before the first recording (n = 1 self-test: a go / no-go for keeping task labels as a main
axis of the thesis, not a population claim). Evaluated in the 'session' z-score mode (the device); the same
numbers in the 'day1' mode are reported next to it and do not change the verdict:
  D = mean over P1 and P2 of (cue_soft - cue) at e 0, per day; D_bar = mean over days.
  R12  GO          if D_bar >= +2 points and D > 0 on at least ceil(2/3 x days) days
       NO-GO       if D_bar <= 0
       INCONCLUSIVE otherwise (then: the pilot with more subjects decides).
       CEILING (reported as INCONCLUSIVE) when cue is already >= 97 % on P1 and P2 on most days: nothing left to gain.
  Also reported: a bootstrap 95 % interval of D per day (2000 resamples of the probe cues), cue_soft - cue_pn and
  cue_soft - cue_pos at e 0.3, cue_soft_t1 - cue at P2, and from day 2 on cue - fixed.
Usage (in the container): python src/selftest_analysis.py --dir <folder> --days S01_d1_A S01_d2_A [S01_d3_A]
  (<folder>/<name>_emg.csv, <name>_ops.csv, <name>_task.csv)  [--out results/selftest]
"""
import argparse
import math
import os
import sys
from fractions import Fraction

import numpy as np
import pandas as pd
from scipy.signal import resample_poly

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_features_c as FC  # noqa: E402
import lda_robust as LR  # noqa: E402
import pipeline as P  # noqa: E402
import task_sim2 as T2  # noqa: E402

GESTURES = ['Power', 'Lateral', 'Tripod', 'Pointer', 'Open', 'Rest']
G = {g: i for i, g in enumerate(GESTURES)}
COMMAND = {'pose_A': 'Power', 'home': 'Lateral', 'grip': 'Tripod', 'pose_B': 'Pointer', 'release': 'Open'}
CMD_G = sorted(G[g] for g in COMMAND.values())
K, REST = 6, 5
FS, WIN, STEP, NW = 2000.0, 400, 200, 10
CAL_S, REACT_S, HOLD_S, K_DC, DECAY = 2.0, 0.5, 0.5, 3, 0.97
EPS, P0, BETA = T2.EPS, T2.P0, T2.BETA
ERRS, SEEDS = (0.0, 0.1, 0.3), 20
CONDS = ('fixed', 'cue', 'cue_soft', 'cue_pn', 'cue_pos', 'cue_soft_t1')


def q16(X):
    return P.quantize(X).astype(np.float64) / (1 << P.Q_SHIFT)


class RunLDA:
    def __init__(self, d=80):
        self.G, self.s, self.n = np.zeros((d, d)), np.zeros((K, d)), np.zeros(K)

    def learn(self, Z, lab, fit=True):
        Zq = q16(Z)
        self.G = DECAY * self.G + Zq.T @ Zq
        self.s = DECAY * self.s
        self.n = DECAY * self.n
        self.s[lab] += Zq.sum(0)
        self.n[lab] += len(Zq)
        if fit:
            self.fit()

    def learn_soft(self, Z, qq):
        Zq = q16(Z)
        self.G = DECAY * self.G + Zq.T @ Zq
        self.s = DECAY * self.s + np.outer(qq, Zq.sum(0))
        self.n = DECAY * self.n + qq * len(Zq)
        self.fit()

    def fit(self):
        N = self.n.sum()
        m = self.s / np.maximum(self.n, 1e-9)[:, None]
        S = (self.G - (m.T * self.n) @ m) / N
        self.w, self.b = LR.oas_solve(S, N, m)
        return self

    def copy(self):
        o = RunLDA(self.G.shape[0])
        o.G, o.s, o.n = self.G.copy(), self.s.copy(), self.n.copy()
        o.w, o.b = self.w.copy(), self.b.copy()
        return o

    def scores(self, Z):
        return q16(Z) @ self.w.T + self.b


# ------------------------------------------------------------------ reading one day
def load_emg(path):
    df = pd.read_csv(path)
    X = df[[f'ch{c}_V' for c in range(8)]].to_numpy(np.float64)
    fr = df.frame.to_numpy(np.float64)
    ms = df.unix_ms.to_numpy(np.float64)
    slope, icpt = np.polyfit(fr, ms - ms[0], 1)                 # ms per frame
    rate = 1000.0 / slope
    t0 = ms[0] + icpt
    if abs(rate - FS) > 2.0:
        fr_ = Fraction(FS / rate).limit_denominator(2000)
        X = resample_poly(X, fr_.numerator, fr_.denominator, axis=0)
    return X.astype(np.float32), t0, rate


def features(X):
    x = np.ascontiguousarray(X.T)
    n = x.shape[1]
    nw = (n - WIN) // STEP + 1
    F = np.zeros((nw, 80), dtype=np.float32)
    assert FC.lib().fe_recording(x.ctypes.data, n, F.ctypes.data, nw) == nw
    return np.nan_to_num(F.astype(np.float64))


def inside(t0, nw, a, b):
    """indices of the windows wholly inside [a, b] (unix ms)"""
    st = t0 + np.arange(nw) * STEP / FS * 1000
    return np.flatnonzero((st >= a) & (st + WIN / FS * 1000 <= b))


def mid(idx):
    if len(idx) <= NW:
        return idx
    o = (len(idx) - NW) // 2
    return idx[o:o + NW]


def load_day(folder, name):
    X, t0, rate = load_emg(os.path.join(folder, f'{name}_emg.csv'))
    F = features(X)
    nw = len(F)
    ops = pd.read_csv(os.path.join(folder, f'{name}_ops.csv'))
    task = pd.read_csv(os.path.join(folder, f'{name}_task.csv'), dtype=str, keep_default_na=False)
    task['t'] = task.unix_ms.astype(float)
    first_seg = task.loc[task.event == 'seg_start', 't'].min()
    cal = {}
    for r in ops.itertuples():
        c = str(r.command).split()
        if len(c) == 2 and c[0] == 'cal' and c[1].isdigit() and r.unix_ms < first_seg and str(r.accepted) not in ('0', 'False'):
            cal[int(c[1])] = float(r.unix_ms)
    assert sorted(cal) == list(range(K)), f'{name}: cued pass incomplete, cal rows for {sorted(cal)}'
    ev = []                                                     # (time, kind, payload)
    cue_rows = [inside(t0, nw, cal[g], cal[g] + CAL_S * 1000)[-NW:] for g in range(K)]
    ev.append((max(cal.values()), 'cuepass', [(rows, g) for g, rows in enumerate(cue_rows)]))
    # the last completed run of every segment index
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
    probe_no = 0
    for idx in sorted(runs):
        run = runs[idx]
        if run['seg'] == 'labelled':
            on = {}
            items = []
            for r in run['rows']:
                if r.event == 'cue_on':
                    on[r.step] = r
                elif r.event == 'cue_off' and r.step in on:
                    w = mid(inside(t0, nw, on[r.step].t + REACT_S * 1000, r.t))
                    if len(w):
                        items.append((w, G[r.target]))
            ev.append((run['rows'][-1].t, f'probe{probe_no}', items))
            probe_no += 1
        elif run['seg'] == 'task':
            on = {}
            for r in run['rows']:
                if r.event == 'trial_on':
                    on[r.step] = r
                elif r.event == 'trial_off' and r.step in on:
                    w = inside(t0, nw, on[r.step].t, r.t + HOLD_S * 1000)
                    if len(w) >= K_DC:
                        ev.append((on[r.step].t, 'trial', (w, G[COMMAND[r.target]], f'T{idx}')))
    ev.sort(key=lambda e: e[0])
    return dict(name=name, F=F, events=ev, rate=rate, probes=probe_no,
                trials=sum(e[1] == 'trial' for e in ev), cal_windows=[len(c) for c in cue_rows])


# ------------------------------------------------------------------ replay
def decide(mdl, Z):
    pr = np.argmax(mdl.scores(Z), 1)
    j = next((i for i in range(len(pr) - K_DC + 1) if pr[i] != REST and (pr[i:i + K_DC] == pr[i]).all()), None)
    if j is None:
        return None, None
    end = j
    while end + 1 < len(pr) and pr[end + 1] == pr[j]:
        end += 1
    return int(pr[j]), Z[j:end + 1]


def task_label(mdl, mode, rows, pred, exp):
    if mode == 'pn':
        mdl.learn(rows, exp)
    elif mode == 'pos':
        if pred == exp:
            mdl.learn(rows, pred)
    elif mode == 'soft':
        prior = np.full(K, EPS / (len(CMD_G) - 1))
        prior[exp] = 1 - EPS
        prior[REST] = P0
        s = mdl.scores(rows).mean(0)
        qq = prior * np.exp(BETA * (s - s.max()))
        mdl.learn_soft(rows, qq / qq.sum())


def replay(days, cond, e, seed, stats):
    """-> rows: per day and probe, the per-cue correct counts (for the bootstrap) and accuracy"""
    rng = np.random.default_rng(seed)
    mode = {'cue_soft': 'soft', 'cue_pn': 'pn', 'cue_pos': 'pos', 'cue_soft_t1': 'soft'}.get(cond)
    mdl, out, cmds = None, [], dict(cmd=0, ok=0, miss=0)
    for di, D in enumerate(days):
        mu, sd = stats[di]
        Z = (D['F'] - mu) / sd
        frozen = False
        for t, kind, pay in D['events']:
            if kind == 'cuepass':
                if mdl is None:
                    mdl = RunLDA()
                    for rows, g in pay:
                        mdl.learn(Z[rows], g, fit=False)
                    mdl.fit()
                elif cond != 'fixed':
                    for rows, g in pay:
                        mdl.learn(Z[rows], g, fit=False)
                    mdl.fit()
            elif kind.startswith('probe'):
                per = [int((np.argmax(mdl.scores(Z[w]), 1) == g).sum()) for w, g in pay]
                n = [len(w) for w, _ in pay]
                out.append(dict(day=di + 1, name=D['name'], probe=kind, cond=cond, e=e, seed=seed,
                                acc=100.0 * sum(per) / max(sum(n), 1), correct=per, n=n))
                if cond == 'cue_soft_t1' and kind == 'probe1':
                    frozen = True
            elif kind == 'trial' and mode and not frozen:
                w, g, _ = pay
                pred, rows = decide(mdl, Z[w])
                if pred is None:
                    cmds['miss'] += 1
                    continue
                cmds['cmd'] += 1
                cmds['ok'] += int(pred == g)
                exp = g
                if e > 0 and rng.random() < e:
                    exp = int(rng.choice([c for c in CMD_G if c != g]))
                task_label(mdl, mode, rows, pred, exp)
    return out, cmds


def boot_d(a, b, rng, n=2000):
    """bootstrap over the probe cues of P1 and P2: D = mean over the two probes of (acc_a - acc_b)"""
    ds = []
    for _ in range(n):
        v = []
        for pa, pb in zip(a, b):
            k = rng.integers(0, len(pa['n']), len(pa['n']))
            na = np.array(pa['n'])[k].sum()
            v.append(100.0 * (np.array(pa['correct'])[k].sum() - np.array(pb['correct'])[k].sum()) / na)
        ds.append(np.mean(v))
    return np.percentile(ds, [2.5, 97.5])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--days', nargs='+', required=True)
    ap.add_argument('--out', default=os.path.join(P.ROOT, 'results', 'selftest'))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    lines = []

    def p(s=''):
        lines.append(s)
        print(s, flush=True)

    days = [load_day(args.dir, n) for n in args.days]
    for D in days:
        p(f"{D['name']}: TCU rate {D['rate']:.1f} Hz, {len(D['F'])} windows, cued pass windows {D['cal_windows']}, "
          f"probes {D['probes']}, task trials {D['trials']}")
        assert D['probes'] == 3, 'expected 3 completed labelled segments (P0 P1 P2)'
    def cue_stats(D):
        cp = next(pay for _, kind, pay in D['events'] if kind == 'cuepass')
        X = np.concatenate([D['F'][r] for r, _ in cp])
        mu, sd = X.mean(0), X.std(0)
        bad = ~np.isfinite(sd) | (sd == 0)
        mu[bad], sd[bad] = 0.0, np.inf
        return mu, sd

    per_day = [cue_stats(D) for D in days]
    STATS = {'session': per_day, 'day1': [per_day[0]] * len(days)}
    all_rows, all_cmd = [], []
    for zmode, stats in STATS.items():
        for cond in CONDS:
            for e in (ERRS if cond in ('cue_soft', 'cue_pn', 'cue_pos') else (0.0,)):
                for seed in (range(SEEDS) if e > 0 else (0,)):
                    o, c = replay(days, cond, e, seed, stats)
                    all_rows += [dict(r, zmode=zmode) for r in o]
                    all_cmd.append(dict(zmode=zmode, cond=cond, e=e, seed=seed, **c))
    pd.DataFrame(all_rows).drop(columns=['correct', 'n']).to_csv(os.path.join(args.out, 'selftest_probes.csv'), index=False)
    pd.DataFrame(all_cmd).to_csv(os.path.join(args.out, 'selftest_commands.csv'), index=False)
    verdicts = {}
    for zmode in STATS:
        verdicts[zmode] = report(p, zmode, [r for r in all_rows if r['zmode'] == zmode],
                                 [c for c in all_cmd if c['zmode'] == zmode], len(days))
    p('')
    p(f"R12 verdict (primary, z-score per donning as on the device): {verdicts['session']}")
    p(f"   sensitivity (day-1 z-score): {verdicts['day1']}")
    with open(os.path.join(args.out, 'selftest_summary.txt'), 'w') as f:
        f.write('\n'.join(lines) + '\n')


def report(p, zmode, rows, cmd_rows, ndays):
    df = pd.DataFrame(rows)
    p('')
    p(f'================ z-score mode: {zmode} ' + ('(PRIMARY: as on the device)' if zmode == 'session' else '(sensitivity)'))
    acc = df.groupby(['cond', 'e', 'day', 'probe']).acc.mean().unstack('probe')
    p('\nprobe accuracy % (6 classes); P0 right after the cued pass, P1 after task segment 1, P2 after segment 2')
    p(acc.round(2).to_string())
    p('\nR12: D = mean over P1, P2 of (cue_soft - cue), e 0')
    rng = np.random.default_rng(0)
    Ds = []
    for di in range(1, ndays + 1):
        a = [r for r in rows if r['cond'] == 'cue_soft' and r['e'] == 0 and r['day'] == di and r['probe'] in ('probe1', 'probe2')]
        b = [r for r in rows if r['cond'] == 'cue' and r['day'] == di and r['probe'] in ('probe1', 'probe2')]
        d = float(np.mean([x['acc'] - y['acc'] for x, y in zip(a, b)]))
        lo, hi = boot_d(a, b, rng)
        Ds.append(d)
        p(f'  day {di}: D = {d:+.2f}  (bootstrap 95 % {lo:+.2f}, {hi:+.2f})')
    need = math.ceil(2 * len(Ds) / 3)
    pos = sum(d > 0 for d in Ds)
    dbar = float(np.mean(Ds))
    verdict = 'GO' if (dbar >= 2 and pos >= need) else ('NO-GO' if dbar <= 0 else 'INCONCLUSIVE')
    cue12 = df[(df.cond == 'cue') & df.probe.isin(['probe1', 'probe2'])].groupby('day').acc.min()
    if (cue12 >= 97).sum() > len(Ds) / 2:
        verdict = 'INCONCLUSIVE (ceiling: cue >= 97 % on P1 and P2 on most days)'
    p(f'  D_bar = {dbar:+.2f}, positive on {pos}/{len(Ds)} days (need {need}) -> {verdict}')

    def m(cond, e, probes, day=None):
        x = df[(df.cond == cond) & (df.e == e) & df.probe.isin(probes)]
        if day is not None:
            x = x[x.day >= day]
        return x.acc.mean()

    p('\nalso reported (mean over days and seeds)')
    p(f"  cue_soft - cue_pn  at e 0.3, P1-P2: {m('cue_soft', 0.3, ['probe1', 'probe2']) - m('cue_pn', 0.3, ['probe1', 'probe2']):+.2f}")
    p(f"  cue_soft - cue_pos at e 0.3, P1-P2: {m('cue_soft', 0.3, ['probe1', 'probe2']) - m('cue_pos', 0.3, ['probe1', 'probe2']):+.2f}")
    p(f"  cue_soft_t1 - cue at P2 (labels 5-10 min old): {m('cue_soft_t1', 0.0, ['probe2']) - m('cue', 0.0, ['probe2']):+.2f}")
    if ndays > 1:
        p(f"  cue - fixed, days 2+, all probes: {m('cue', 0.0, ['probe0', 'probe1', 'probe2'], 2) - m('fixed', 0.0, ['probe0', 'probe1', 'probe2'], 2):+.2f}")
    cm = pd.DataFrame(cmd_rows).groupby(['cond', 'e'])[['cmd', 'ok', 'miss']].mean()
    cm['cmd_acc %'] = (cm.ok / cm.cmd * 100).round(1)
    p('\noffline task-trial decisions (mean over seeds, all days)')
    p(cm.round(1).to_string())
    return verdict


if __name__ == '__main__':
    main()
