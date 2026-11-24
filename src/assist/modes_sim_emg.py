"""Pick-and-place with the two-mode control (modes_sim.py, report 35.63) driven by the user's own recorded EMG
(report 35.78): the decoder is not an independent random error any more, but the windows the firmware actually
classified in the two self-test donnings (check_rt_s7.py: rt_lda.c, 9-class build, classes S7).

Empirical decoder, one 100 ms window per simulation step (DT = 0.1 s = the window step):
  When the simulated user's intended class changes, a recorded stretch of that class starts from its beginning:
    up / down / left / right = a probe cue of WristExt / WristFlex / RadialDev / UlnarDev from its motor onset: one
      window before the activity first reaches half the median gesture activity (act_ratio >= 0.5). Not from
      cue_on: that adds the reaction to the visual cue (about 0.3-0.7 s of rest) on top of the simulated user's own
      REACT delay; counted twice it stopped the arm at every change of direction and, with modes.py locking on the
      first rest step in front of an object, made 3-4.5 wrong locks per trial with the gate (lock_diag, 35.79);
      rest after a direction = the release of a probe cue of that same gesture (cue_off to the next cue_on,
      about 1 s: the decaying EMG of the gesture being let go), then steady rest; rest otherwise = steady rest.
      Steady rest = the recorded rest from 0.5 s after its start: task rest periods (posture A / B / C), the
      releases after the probe cues, the Rest cues.
  A held class outlasts its stretch: then a random stretch of the same class continues from 1 s after its start
    to 0.5 s before its end (a gesture), or another steady-rest stretch (rest).
  The window's class -> decision.c (k equal windows establish a class; Rest establishes without a command); the
    established class drives the arm (hold = move, Rest = stop). HandOpen / Fist (S7 classes the task never needs)
    stop the arm and count as spurious grip commands.
Rules compared (both on the same recorded windows):
  new  the firmware of 35.78: S7, activity gate 0.5 x median gesture activity (mode 2), k 5 (the MCU's own windows)
  old  S7 without the gate, k 3 (the Python reference of check_rt_s7.py, same LDA; = the earlier board rule on S7)
  and the reference modes_sim rows with independent window errors e = 0, 0.1.
Donnings separately (each its own calibration and its own recorded windows), seeds fixed.
Measured, besides modes_sim's columns: unintended motion = steps the arm moves while the user means rest, per
minute of meant rest; wrong-direction steps = the arm moves another way than the user's held direction, share of
the steps the user holds a direction; spurious grip commands per trial.

usage: python src/assist/modes_sim_emg.py [--trials 300] [--out results/selftest_T00]
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assist_sim as S  # noqa: E402
import modes_sim as MS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NAMES = {0: 'up', 1: 'down', 2: 'left', 3: 'right', 6: 'grip_open', 7: 'grip_close', 8: 'rest'}
CLS = {'up': 0, 'down': 1, 'left': 2, 'right': 3, 'rest': 8}
DIRS = ('up', 'down', 'left', 'right')


class Traces:
    def __init__(self, path, key):
        z = np.load(path)
        lab = z[key]
        self.by = {c: [] for c in CLS.values()}
        for s, n, g in zip(z['cue_starts'], z['cue_lens'], z['cue_cls']):
            if int(g) in self.by:
                i = np.flatnonzero(z['act_ratio'][s:s + n] >= 0.5)
                a = max(int(i[0]) - 1, 0) if len(i) else 0
                self.by[int(g)].append(lab[s + a:s + n])
        for s, n in zip(z['rest_starts'], z['rest_lens']):
            self.by[8].append(lab[s:s + n])
        self.rel = {c: [] for c in range(4)}
        for s, n, g in zip(z['rel_starts'], z['rel_lens'], z['rel_cls']):
            if int(g) in self.rel:
                self.rel[int(g)].append(lab[s:s + n])
        for c, v in list(self.by.items()) + list(self.rel.items()):
            assert v and all((t >= 0).all() for t in v), (path, c)


class EmgDecoder:
    def __init__(self, tr, k, rng, stats, k_rest=None):
        self.tr, self.k, self.rng, self.st = tr, k, rng, stats
        self.k_rest = k if k_rest is None else k_rest
        self.since = 0                                  # steps since the user last switched to rest
        self.stopped = True
        self.held = 0
        self.want = None
        self.seq, self.i = None, 0
        self.last, self.run, self.lat = -1, 0, 8
        self.est = 'rest'

    def _next_window(self, want):
        c = CLS[want]
        if want != self.want:
            pool = self.tr.rel[CLS[self.want]] if c == 8 and self.want in DIRS else self.tr.by[c]
            self.want = want
            self.seq = pool[self.rng.integers(len(pool))]
            self.i = 0
        elif self.i >= len(self.seq) - (5 if c != 8 else 0):
            t = self.tr.by[c][self.rng.integers(len(self.tr.by[c]))]
            if c != 8:
                b = len(t) - 5
                t = t[min(10, b - 1):b]
            self.seq = t
            self.i = 0
        w = int(self.seq[self.i])
        self.i += 1
        return w

    def __call__(self, want):
        if want == 'rest' and self.want != 'rest':
            self.since, self.stopped = 0, False
        if want in DIRS and self.want != want:
            self.held = 0
        p = self._next_window(want)
        self.run = min(self.run + 1, max(self.k, self.k_rest)) if p == self.last else 1
        self.last = p
        if self.run >= (self.k_rest if p == 8 else self.k) and p != self.lat:
            self.lat = p
            if p in (6, 7):
                self.st['grip'] += 1
        self.est = NAMES[self.lat]
        if want == 'rest':
            self.st['rest_steps'] += 1
            self.st['rest_moving'] += self.est in DIRS
            if not self.stopped and self.est not in DIRS:
                self.stopped = True
                self.st['stop'].append(self.since)
            if self.since >= 15:
                self.st['sus_steps'] += 1
                self.st['sus_moving'] += self.est in DIRS
            self.since += 1
        elif want in DIRS:
            self.st['dir_steps'] += 1
            self.st['dir_wrong'] += self.est in DIRS and self.est != want
            self.held += 1
            if self.held > 15:                          # held over 1.5 s: past the onset
                self.st['hold_steps'] += 1
                self.st['hold_stopped'] += self.est not in DIRS
        return self.est if self.est in DIRS else 'rest'


def run(tr, k, trials, seed, rule, k_rest=None):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(trials):
        st = dict(grip=0, rest_steps=0, rest_moving=0, dir_steps=0, dir_wrong=0, sus_steps=0, sus_moving=0, stop=[],
                  hold_steps=0, hold_stopped=0)
        S.Decoder = lambda classes, e, r, _st=st: EmgDecoder(tr, k, rng, _st, k_rest)  # used inside modes_sim.trial
        out.append((MS.trial(0.0, rng, rule), st))
    return out


def summary(label, res):
    ok = np.array([r[0] for r, _ in res])
    tm = np.array([r[1] for r, _ in res if r[0]])
    cols = np.array([r[2].n for r, _ in res])
    st = {k: sum(s[k] for _, s in res) for k in res[0][1] if k != 'stop'}
    stop = np.concatenate([s['stop'] for _, s in res]) * 100 if 'stop' in res[0][1] else np.array([])
    rest_min = st['rest_steps'] * 0.1 / 60
    sus = (f'{st["sus_moving"] * 0.1 / max(st["sus_steps"] * 0.1 / 60, 1e-9):6.2f} s/min'
           if st.get('sus_steps') else '     -     ')
    stp = f'{np.median(stop):5.0f} ({np.percentile(stop, 75):.0f}, {np.percentile(stop, 95):.0f})' if len(stop) else '   -'
    q = (f'{np.median(tm):5.1f} ({np.percentile(tm, 25):.1f}-{np.percentile(tm, 75):.1f})' if len(tm) else '  -  ')
    return (f'  {label:<26} {100 * ok.mean():5.1f} %   {q:<18} {cols.sum():5d} ({int((cols > 0).sum())})   '
            f'{np.mean([r[4] for r, _ in res]):5.2f}   '
            f'{st["rest_moving"] * 0.1 / max(rest_min, 1e-9) / 60 * 60:6.2f} s/min   '
            f'{100 * st["dir_wrong"] / max(st["dir_steps"], 1):5.1f} %   {st["grip"] / len(res):5.2f}   '
            f'{stp:<18} {sus}   ' + (f'{100 * st["hold_stopped"] / max(st["hold_steps"], 1):5.1f} %'
                                    if st.get('hold_steps') else '  -'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trials', type=int, default=300)
    ap.add_argument('--out', default=os.path.join(ROOT, 'results', 'selftest_T00'))
    ap.add_argument('--days', nargs='+', default=['T00_d1_G', 'T00_d2_G'])
    ap.add_argument('--rule', default='mix', choices=['mix', 'lead'])
    a = ap.parse_args()
    lines = []

    def p(s=''):
        print(s, flush=True)
        lines.append(s)

    p(f'two-mode pick-and-place (modes_sim.py, rule {a.rule}) driven by the recorded EMG, {a.trials} trials per row, '
      f'limit {MS.T_MAX * 0.1:.0f} s')
    p('  decoder                    success   time median (IQR) s  collisions (trials)  wrong locks/trial   '
      'arm moving while resting   wrong-direction steps   spurious grips/trial   stop delay ms median (p75, p95)   '
      'moving after 1.5 s of rest   stopped while held > 1.5 s')
    orig = S.Decoder
    for j, e in enumerate((0.0, 0.1)):
        S.Decoder = orig
        rng = np.random.default_rng(5000 + j)
        res = [(MS.trial(e, rng, a.rule), dict(grip=0, rest_steps=1, rest_moving=0, dir_steps=1, dir_wrong=0))
               for _ in range(a.trials)]
        p(summary(f'random e {e:.1f} (35.63)', res).replace('  0.00 s/min     0.0 %   0.00', '     -            -        -  '))
    for d, name in enumerate(a.days):
        path = os.path.join(a.out, f'rt_s7_labels_{name}.npz')
        for i, (lab, key, k, kr) in enumerate((('old (no gate, k 3)', 'lab_raw', 3, None),
                                               ('new (gate 0.5, k 5)', 'lab', 5, None),
                                               ('new, stop k 2', 'lab', 5, 2), ('new, stop k 1', 'lab', 5, 1))):
            res = run(Traces(path, key), k, a.trials, 7000 + 10 * d + i, a.rule, kr)
            p(summary(f'{name[4:6]} {lab}', res))
    S.Decoder = orig
    with open(os.path.join(a.out, f'modes_sim_emg_{a.rule}.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
