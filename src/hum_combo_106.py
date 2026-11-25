"""Report 35.106: R19's label-gate rule on the 11/23 days (development, sets nothing new): flag a window if on any
channel the hum estimate > T AND > RHO x that channel's window RMS. T = 7.07 uV (levels_1123.txt), RHO = 0.5."""
import os
import sys

import numpy as np
from scipy.signal import butter, sosfilt

sys.path.insert(0, '/work/src')
import hum_abs as HA   # noqa: E402
import selftest_analysis as SA   # noqa: E402
import selftest9_analysis as S9  # noqa: E402

T, RHO = 7.07, 0.5
sos = butter(4, (10 / 1000, 500 / 1000), btype='bandpass', output='sos')
L = [f'label gate: hum > {T} uV AND hum > {RHO} x channel RMS, any of ch1-4 (11/23, development)']
for name in ('T00_d1_G', 'T00_d2_G'):
    d = S9.load_day('/sd/T00', name, 4.0, need=set(S9.SETS['S7']))
    X, _, _ = SA.load_emg(os.path.join(S9.day_folder('/sd/T00', name), f'{name}_emg.csv'))
    x = sosfilt(sos, X[:, :4].astype(np.float64), axis=0)
    nw = min(len(d['F']), (len(x) - HA.WIN) // HA.STEP + 1)
    Hc = HA.hum_ch(HA.psd_windows(x, nw)) * 1e6
    idx = np.arange(HA.WIN)[None, :] + HA.STEP * np.arange(nw)[:, None]
    rms = np.sqrt((x[idx] ** 2).mean(1)) * 1e6                    # (nw, 4) uV, the window RMS per channel
    flag = ((Hc > T) & (Hc > RHO * rms)).any(1)
    rest = d['cal_rows'][d['cal_lab'] == S9.REST]
    task = np.zeros(nw, bool)
    for _, kind, pay in d['events']:
        if kind == 'trial':
            task[pay[0][pay[0] < nw]] = True
    per = [f'{S9.GESTURES[g]} {100 * flag[d["cal_rows"][d["cal_lab"] == g]].mean():.0f} %' for g in S9.SETS['S7']]
    L.append(f'{name}: cued windows flagged: ' + ', '.join(per))
    L.append(f'  task windows flagged {100 * flag[task].mean():.1f} %, all {100 * flag.mean():.1f} %')
txt = '\n'.join(L)
print(txt)
open('/work/results/hum_106/combo_1123.txt', 'w').write(txt + '\n')
