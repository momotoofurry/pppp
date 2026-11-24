"""Why the EMG-driven sim locks the wrong object/shelf (report 35.78 follow-up). Same loop as modes_sim.trial, with
every lock event logged: was it wrong, what the simulated user meant at that step (a direction held for how long /
rest), what the decoder had latched (Rest / a grip class / a direction), the user's last direction."""
import os
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, '/work/src/assist')
import assist_sim as S  # noqa: E402
import modes as M  # noqa: E402
import modes_sim as MS  # noqa: E402
import modes_sim_emg as E  # noqa: E402


def trial(dec_factory, rng):
    ma = M.ModeAssist(MS.OBJ, MS.SHELVES, rule='mix')
    t_obj = int(rng.integers(3))
    free = [k for k in range(len(MS.SHELVES))
            if all(np.linalg.norm(o[:2] - MS.SHELVES[k][:2]) > 0.06 or abs(o[2] - (MS.SHELVES[k][2] + M.OBJ_H / 2)) > 0.03
                   for o in MS.OBJ)]
    t_shelf = int(rng.choice(free))
    dec = dec_factory()
    x = MS.X0.copy()
    hist = [x.copy()] * (S.REACT + 1)
    last_lock, ev, wants = None, [], []
    for t in range(MS.T_MAX):
        want = MS.user(ma, hist[-1 - S.REACT], t_obj, t_shelf, dec.est)
        wants.append(want)
        cmd = dec(want)
        xp = x.copy()
        v = ma.step(cmd if cmd != 'rest' else None, x)
        if ('邊緣' in ma.msg or '太靠近' in ma.msg) and ma.armed is False:
            ma.msg = ''
            ma.armed = True
        lock = (ma.phase, ma.goal, ma.shelf) if ma.m == 2 else None
        if lock != last_lock and lock is not None and lock[0] in ('pick', 'place'):
            wrong = (lock[0] == 'pick' and lock[1] != t_obj) or (lock[0] == 'place' and lock[2] != t_shelf)
            # how long the user has meant the current thing
            n = 1
            while n < len(wants) and wants[-1 - n] == want:
                n += 1
            prev_dir = next((w for w in reversed(wants[:-n]) if w in E.DIRS), None) if want == 'rest' else None
            ev.append(dict(wrong=wrong, phase=lock[0], want=want, for_steps=n, latched=E.NAMES[dec.lat],
                           prev_dir=prev_dir))
        last_lock = lock
        x = x + v * M.DT
        hist.append(x.copy())
        on = (ma.held is None and abs(ma.obj[t_obj][2] - (MS.SHELVES[t_shelf][2] + M.OBJ_H / 2)) < 1e-6
              and abs(ma.obj[t_obj][0] - MS.SHELVES[t_shelf][0]) <= M.SHELF_HX - M.EDGE + 1e-6
              and abs(ma.obj[t_obj][1] - MS.SHELVES[t_shelf][1]) <= M.SHELF_HY - M.EDGE + 1e-6)
        if on and ma.m == 1:
            return True, ev
    return False, ev


def main():
    out = '/work/results/selftest_T00'
    for name in ('T00_d1_G', 'T00_d2_G'):
        path = os.path.join(out, f'rt_s7_labels_{name}.npz')
        for lab, key, k in (('old (no gate, k 3)', 'lab_raw', 3), ('new (gate 0.5, k 5)', 'lab', 5)):
            tr = E.Traces(path, key)
            rng = np.random.default_rng(42)
            st = dict(grip=0, rest_steps=0, rest_moving=0, dir_steps=0, dir_wrong=0, sus_steps=0, sus_moving=0,
                      stop=[], hold_steps=0, hold_stopped=0)
            evs, ok = [], 0
            for _ in range(300):
                s, ev = trial(lambda: E.EmgDecoder(tr, k, rng, st), rng)
                ok += s
                evs += ev
            w = [e for e in evs if e['wrong']]
            print(f'\n{name[4:6]} {lab}: success {ok / 3:.1f} %, locks {len(evs)}, wrong {len(w)} '
                  f'({len(w) / 300:.2f} per trial)')
            c = Counter()
            for e in w:
                if e['want'] in E.DIRS:
                    c[f'user still holding a direction ({"<" if e["for_steps"] < 15 else ">="}1.5 s), decoder latched {e["latched"]}'] += 1
                else:
                    c[f'user resting ({"<" if e["for_steps"] < 10 else ">="}1 s), decoder latched {e["latched"]}'] += 1
            for kk, v in c.most_common():
                print(f'   {v:5d}  {kk}')
            r = [e for e in w if e['want'] == 'rest']
            if r:
                print('   wrong locks while resting, by phase:', dict(Counter(e['phase'] for e in r)),
                      ' rest duration steps median', int(np.median([e['for_steps'] for e in r])))


main()
