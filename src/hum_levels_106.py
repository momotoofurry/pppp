"""Report 35.106: hum levels (calibrated estimate, fundamental) on the 11/23 days, to set R19's threshold.
Also checks the estimate against the 2 s coherent fit of the fundamental alone."""
import os
import sys

import numpy as np
from scipy.signal import butter, sosfilt

sys.path.insert(0, '/work/src')
import hum_abs as HA   # noqa: E402
import selftest_analysis as SA   # noqa: E402
import selftest9_analysis as S9  # noqa: E402

sos = butter(4, (10 / 1000, 500 / 1000), btype='bandpass', output='sos')
t = np.arange(20 * HA.STEP) / HA.FS
Hm = np.column_stack([np.sin(2 * np.pi * 59.98 * t), np.cos(2 * np.pi * 59.98 * t)])
Pm = Hm @ np.linalg.pinv(Hm)
L = []
res = {}
for name in ('T00_d1_G', 'T00_d2_G'):
    d = S9.load_day('/sd/T00', name, 4.0, need=set(S9.SETS['S7']))
    X, _, _ = SA.load_emg(os.path.join(S9.day_folder('/sd/T00', name), f'{name}_emg.csv'))
    x = sosfilt(sos, X[:, :4].astype(np.float64), axis=0)
    nw = min(len(d['F']), (len(x) - HA.WIN) // HA.STEP + 1)
    Hc = HA.hum_ch(HA.psd_windows(x, nw)) * 1e6           # (nw, 4) uV
    H = Hc.max(1)
    tru = np.zeros((nw, 4))
    for b0 in range(0, nw, 20):
        seg = x[b0 * HA.STEP:b0 * HA.STEP + 20 * HA.STEP]
        if len(seg) < 20 * HA.STEP:
            seg = x[-20 * HA.STEP:]
        tru[b0:b0 + 20] = np.sqrt(((Pm @ seg) ** 2).mean(0)) * 1e6
    rest = d['cal_rows'][d['cal_lab'] == S9.REST]
    act = d['cal_rows'][np.isin(d['cal_lab'], [g for g in S9.SETS['S7'] if g != S9.REST])]
    task = np.zeros(nw, bool)
    for _, kind, pay in d['events']:
        if kind == 'trial':
            task[pay[0][pay[0] < nw]] = True
    res[name] = dict(H=H, rest=rest, act=act, task=task)
    L.append(f'{name}:')
    L.append(f'  estimate vs 2 s coherent fundamental, per channel: median ratio on cued Rest '
             f'{np.median(Hc[rest] / np.maximum(tru[rest], 1e-3), 0).round(2).tolist()}, on gestures '
             f'{np.median(Hc[act] / np.maximum(tru[act], 1e-3), 0).round(2).tolist()}')
    L.append(f'  cued Rest: estimate median per channel {np.median(Hc[rest], 0).round(1).tolist()} uV, window max median '
             f'{np.median(H[rest]):.1f} uV')
    L.append(f'  cued gestures: window max median {np.median(H[act]):.1f} uV (p90 {np.percentile(H[act], 90):.1f}); '
             f'task segments median {np.median(H[task]):.1f} uV (p90 {np.percentile(H[task], 90):.1f})')
r1 = np.median(res['T00_d1_G']['H'][res['T00_d1_G']['rest']])
r2 = np.median(res['T00_d2_G']['H'][res['T00_d2_G']['rest']])
T = float(np.sqrt(r1 * r2))
L.append(f'\nT = geometric mean of the two days cued-Rest medians = sqrt({r1:.2f} x {r2:.2f}) = {T:.2f} uV')
for name, r in res.items():
    H = r['H']
    L.append(f'  {name}: cued Rest > T {100 * (H[r["rest"]] > T).mean():.0f} %, cued gestures > T {100 * (H[r["act"]] > T).mean():.1f} %, '
             f'task windows > T {100 * (H[r["task"]] > T).mean():.1f} %, all {100 * (H > T).mean():.1f} %')
txt = '\n'.join(L)
print(txt)
os.makedirs('/work/results/hum_106', exist_ok=True)
open('/work/results/hum_106/levels_1123.txt', 'w').write(txt + '\n')
