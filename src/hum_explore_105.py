"""Report 35.105, EXPLORATORY (after R18 failed; not a decision): an absolute hum estimate from the same PSD.
Excess power in the 52-68 Hz bins over the neighbour-band level (EMG is smooth, so the neighbours estimate the EMG
under the peak), converted to an RMS in uV with the Hamming window's power gain; per window, max over ch1-4.
Judged against the 2 s coherent truth with T from day 1 (<= 5 % false flags on CLEAN), on day 2; and the same
for R18's ratio. Also what each would flag among the cued Rest windows (day 1 hum 10-17 uV, day 2 2-4 uV)."""
import os
import sys

import numpy as np
from scipy.signal import butter, sosfilt

sys.path.insert(0, '/work/src')
import hum_gate_r18 as H   # noqa: E402
import selftest_analysis as SA   # noqa: E402
import selftest9_analysis as S9  # noqa: E402

sos = butter(4, (10 / 1000, 500 / 1000), btype='bandpass', output='sos')
ham = 0.54 - 0.46 * np.cos(2 * np.pi * np.arange(H.WIN) / H.WIN)
GAIN = (ham ** 2).sum()                   # periodogram of a sinusoid of RMS a: total power ~ a^2 * GAIN (one-sided x2)
hb = H.bins(*H.HUM_BAND)
nb = H.bins(*H.NB_BANDS[0]) + H.bins(*H.NB_BANDS[1])
out = []
D = []
for name in ('T00_d1_G', 'T00_d2_G'):
    d = S9.load_day('/sd/T00', name, 4.0, need=set(S9.SETS['S7']))
    X, _, _ = SA.load_emg(os.path.join(S9.day_folder('/sd/T00', name), f'{name}_emg.csv'))
    x = sosfilt(sos, X[:, :4].astype(np.float64), axis=0)
    nw = min(len(d['F']), (len(x) - H.WIN) // H.STEP + 1)
    P = H.psd_windows(x, nw)
    excess = np.maximum(P[:, :, hb].sum(2) - P[:, :, nb].mean(2) * len(hb), 0)
    A = np.sqrt(excess / GAIN).max(1)        # uV-scale estimate of the hum RMS
    R = H.ratio(P, [H.HUM_BAND], H.NB_BANDS).max(1)
    tr = H.truth(x, nw).max(1)
    rest = d['cal_rows'][d['cal_lab'] == S9.REST]
    D.append(dict(name=name, A=A, R=R, tr=tr, rest=rest))
    out.append(f'{name}: estimate vs truth (all windows) correlation {np.corrcoef(A, tr)[0, 1]:.2f}; median estimate / truth '
               f'{np.median(A / np.maximum(tr, 1e-9)):.2f}')
for key, lab in (('A', 'absolute estimate'), ('R', 'R18 ratio')):
    c1 = D[0]['tr'] <= H.CLEAN
    T = float(np.quantile(D[0][key][c1], 0.95))
    out.append(f'{lab}: T from day 1 {T * (1e6 if key == "A" else 1):.2f}{" uV" if key == "A" else ""}')
    for d in D:
        c, h = d['tr'] <= H.CLEAN, d['tr'] >= H.HUM
        fl = d[key] > T
        out.append(f'  {d["name"]}: recall {100 * fl[h].mean():.1f} %, false {100 * fl[c].mean():.1f} %, cued Rest flagged '
                   f'{100 * fl[d["rest"]].mean():.0f} %, all windows {100 * fl.mean():.1f} %')
txt = 'EXPLORATORY (35.105, after R18 failed)\n' + '\n'.join(out)
print(txt)
open('/work/results/hum_105/explore.txt', 'w').write(txt + '\n')
