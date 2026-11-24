"""Wrong locks (35.78 follow-up): two candidate causes tested in the EMG-driven pick-and-place.
  onset  'cue'   gesture stretches start at cue_on (they contain the user's reaction to the visual cue; the simulated
                 user already reacts REACT steps late: counted twice)
         'motor' they start one window before the activity first reaches half the median gesture activity
                 (act_ratio >= 0.5; the same start for both rules)
  lock   steps of rest needed in mode 1 before a stop in front of an object / shelf locks it (modes.py: 1, now);
         3 / 5 = 0.3 / 0.5 s (the grasp already needs CONFIRM_STEPS = 10)
Rules: old (S7, no gate, k 3), new (S7, gate 0.5, k 5). 300 trials per row, seeds fixed per donning and rule."""
import os
import sys

import numpy as np

sys.path.insert(0, '/work/src/assist')
import assist_sim as S  # noqa: E402
import modes as M  # noqa: E402
import modes_sim as MS  # noqa: E402
import modes_sim_emg as E  # noqa: E402

ORIG_LOCK = M.ModeAssist._lock


def set_lock_steps(n):
    def _lock(self, x):
        if self.rest_n >= n:
            ORIG_LOCK(self, x)
    M.ModeAssist._lock = _lock if n > 1 else ORIG_LOCK


def motor_onset(tr, path, key):
    z = np.load(path)
    lab, ratio = z[key], z['act_ratio']
    by = {c: [] for c in E.CLS.values()}
    for s, n, g in zip(z['cue_starts'], z['cue_lens'], z['cue_cls']):
        if int(g) in by:
            i = np.flatnonzero(ratio[s:s + n] >= 0.5)
            a = max(int(i[0]) - 1, 0) if len(i) else 0
            by[int(g)].append(lab[s + a:s + n])
    by[8] = tr.by[8]
    tr.by = by
    return tr


def main():
    out = '/work/results/selftest_T00'
    print('  donning rule                onset  lock   success   time median s   wrong locks/trial   '
          'moving after 1.5 s rest   stop delay ms   stopped while held > 1.5 s')
    for d, name in enumerate(('T00_d1_G', 'T00_d2_G')):
        path = os.path.join(out, f'rt_s7_labels_{name}.npz')
        for i, (lab, key, k) in enumerate((('old (no gate, k 3)', 'lab_raw', 3), ('new (gate 0.5, k 5)', 'lab', 5))):
            for onset in ('cue', 'motor'):
                for ls in (1, 3, 5):
                    tr = E.Traces(path, key)
                    if onset == 'motor':
                        tr = motor_onset(tr, path, key)
                    set_lock_steps(ls)
                    res = E.run(tr, k, 300, 7000 + 10 * d + i, 'mix')
                    ok = np.array([r[0] for r, _ in res])
                    tm = np.array([r[1] for r, _ in res if r[0]])
                    wl = np.mean([r[4] for r, _ in res])
                    st = {kk: sum(s[kk] for _, s in res) for kk in res[0][1] if kk != 'stop'}
                    stop = np.concatenate([s['stop'] for _, s in res]) * 100
                    print(f'  {name[4:6]}      {lab:<20} {onset:<6} {ls:3d}   {100 * ok.mean():5.1f} %   '
                          f'{np.median(tm):5.1f}          {wl:5.2f}               '
                          f'{st["sus_moving"] * 0.1 / max(st["sus_steps"] * 0.1 / 60, 1e-9):6.2f} s/min        '
                          f'{np.median(stop):5.0f}          {100 * st["hold_stopped"] / max(st["hold_steps"], 1):5.1f} %',
                          flush=True)
    set_lock_steps(1)


main()
