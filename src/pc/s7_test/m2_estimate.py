# report 35.86 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
"""What M2 (commands in the task rest periods, rest_on..rest_off as TaskScreen counts them) would the S7 firmware have
given on the two 9-gesture donnings? The firmware's own window classes (check_rt_s7 labels, gate, k 5, stop k 2),
one continuous stream; also M3 (S7 probe cues) for reference. The trials themselves were cut short by the old board's
commands, so M1 cannot be replayed offline."""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, '/work/src')
import selftest_analysis as SA
import selftest9_analysis as S9
K, KR, REST = 5, 2, 8
for name in ('T00_d1_G', 'T00_d2_G'):
    z = np.load(f'/work/results/selftest_T00/rt_s7_labels_{name}.npz')
    lab = z['lab']; nw = len(lab)
    folder = S9.day_folder('/sd/T00', name)
    _, t0, _ = SA.load_emg(os.path.join(folder, f'{name}_emg.csv'))
    task = pd.read_csv(os.path.join(folder, f'{name}_task.csv'), dtype=str, keep_default_na=False)
    task['t'] = task.unix_ms.astype(float)
    rests, on, prev = [], {}, None
    C = {'up': 0, 'down': 1, 'left': 2, 'right': 3, 'grip_open': 6, 'grip_close': 7, 'forward': 4, 'back': 5}
    for r in task[task.segment == 'task'].itertuples():
        if r.event == 'trial_on': prev = C.get(r.target)
        if r.event == 'rest_on': on[r.step] = (r.t, prev)
        elif r.event == 'rest_off' and r.step in on:
            t_on, pv = on.pop(r.step)
            rests.append((SA.inside(t0, nw, t_on, r.t), pv))
    cmds, last, rn, lat = [], -1, 0, -1
    for i in np.flatnonzero(lab >= 0):
        p = lab[i]; rn = min(rn + 1, max(K, KR)) if p == last else 1; last = p
        if rn >= (KR if p == REST else K) and p != lat:
            lat = p
            if p != REST: cmds.append(i)
    cls = {i: lab[i] for i in cmds}
    rs = np.zeros(nw, bool); late = other = early_other = 0
    for w, pv in rests:
        if not len(w): continue
        rs[w] = True
        for i in cmds:
            if w[0] <= i <= w[-1]:
                dt = (i - w[0]) * 100
                if cls[i] == pv and dt < 1500: late += 1
                else:
                    other += 1
                    early_other += dt < 1000
    mins = rs.sum() * 0.1 / 60
    print(f'{name}: task rest {mins:.2f} min; commands in rest {late + other}: the trial target arriving late (< 1.5 s) {late}, '
          f'other {other} (of them < 1 s after rest_on {early_other}) -> M2 all {(late + other) / mins:.2f} / min, '
          f'without the late target {other / mins:.2f} / min')
