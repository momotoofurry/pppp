"""Report 35.105, rule R18 (results/hum_105/PREREG_R18.md): can the MCU flag 60 Hz hum from the PSD it already has?
Truth: hum RMS from a least-squares fit of k x 59.98 Hz (k 1..8) over 2 s blocks. Detector: per channel, mean PSD
power per bin in 52-68 Hz / in 32-46 + 74-88 Hz (features.c's 512-point FFT of the Hamming-windowed 200 ms window);
window flag = max over ch1-4 > T. T from day 1 (<= 5 % false flags on its clean windows), judged on day 2.
usage (container): python src/hum_gate_r18.py --dir /sd/T00 --days T00_d1_G T00_d2_G --out results/hum_105"""
import argparse
import os
import sys

import numpy as np
from scipy.signal import butter, sosfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import selftest_analysis as SA   # noqa: E402
import selftest9_analysis as S9  # noqa: E402

F0, NH, BLOCK = 59.98, 8, 20             # 20 windows = 2 s
NFFT, WIN, STEP, FS = 512, 400, 200, 2000
DF = FS / NFFT
HUM_BAND, NB_BANDS = (52, 68), ((32, 46), (74, 88))
HUM2_BAND, NB2_BANDS = (112, 128), ((92, 106), (134, 148))
CLEAN, HUM = 2e-6, 5e-6


def bins(lo, hi):
    return [k for k in range(NFFT // 2 + 1) if lo <= k * DF <= hi]


def psd_windows(x, nw):
    """(nw, ch, bins) one-sided power as features.c (periodic Hamming, zero-padded to 512, x2 except DC / Nyquist)"""
    ham = 0.54 - 0.46 * np.cos(2 * np.pi * np.arange(WIN) / WIN)
    idx = np.arange(WIN)[None, :] + STEP * np.arange(nw)[:, None]
    seg = x[idx] * ham[None, :, None]                       # (nw, WIN, ch)
    P = np.abs(np.fft.rfft(seg, NFFT, axis=1)) ** 2
    P[:, 1:-1] *= 2
    return np.transpose(P, (0, 2, 1))


def ratio(P, hum_bands, nb_bands):
    h = sum((P[:, :, bins(*b)] for b in hum_bands), start=None) if False else np.concatenate([P[:, :, bins(*b)] for b in hum_bands], 2)
    n = np.concatenate([P[:, :, bins(*b)] for b in nb_bands], 2)
    return h.mean(2) / np.maximum(n.mean(2), 1e-30)


def truth(x, nw):
    t = np.arange(BLOCK * STEP) / FS
    H = np.column_stack([fn(2 * np.pi * F0 * k * t) for k in range(1, NH + 1) for fn in (np.sin, np.cos)])
    Pm = H @ np.linalg.pinv(H)
    hum = np.zeros((nw, x.shape[1]))
    for b0 in range(0, nw, BLOCK):
        s0 = b0 * STEP
        seg = x[s0:s0 + BLOCK * STEP]
        if len(seg) < BLOCK * STEP:
            seg = x[len(x) - BLOCK * STEP:]
        h = Pm @ seg
        hum[b0:b0 + BLOCK] = np.sqrt((h ** 2).mean(0))
    return hum


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--days', nargs='+', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    sos = butter(4, (10 / 1000, 500 / 1000), btype='bandpass', output='sos')
    D = []
    for name in a.days:
        d = S9.load_day(a.dir, name, 4.0, need=set(S9.SETS['S7']))
        X, _, _ = SA.load_emg(os.path.join(S9.day_folder(a.dir, name), f'{name}_emg.csv'))
        x = sosfilt(sos, X[:, :4].astype(np.float64), axis=0)
        nw = len(d['F'])
        nw = min(nw, (len(x) - WIN) // STEP + 1)
        P = psd_windows(x, nw)
        R = ratio(P, [HUM_BAND], NB_BANDS).max(1)
        R2 = ratio(P, [HUM_BAND, HUM2_BAND], list(NB_BANDS) + list(NB2_BANDS)).max(1)
        tr = truth(x, nw).max(1)
        task = np.zeros(nw, bool)
        for _, kind, pay in d['events']:
            if kind == 'trial':
                task[pay[0][pay[0] < nw]] = True
        D.append(dict(name=name, R=R, R2=R2, tr=tr, cal_rows=d['cal_rows'], cal_lab=d['cal_lab'], task=task))
    L = [f'R18 (35.105): 60 Hz gate from the MCU PSD; truth = 2 s coherent fit; HUM >= {HUM*1e6:.0f} uV, CLEAN <= {CLEAN*1e6:.0f} uV\n']
    for key, lab in (('R', '60 Hz band (decided)'), ('R2', '60 + 120 Hz bands (reported)')):
        d1 = D[0]
        clean1 = d1['tr'] <= CLEAN
        T = float(np.quantile(d1[key][clean1], 0.95))
        L.append(f'{lab}: T from day 1 = {T:.2f}')
        for d in D:
            c, h = d['tr'] <= CLEAN, d['tr'] >= HUM
            fl = d[key] > T
            L.append(f'  {d["name"]}: HUM windows {h.sum()} recall {100 * fl[h].mean():.1f} % | CLEAN windows {c.sum()} '
                     f'false flags {100 * fl[c].mean():.1f} % | all windows flagged {100 * fl.mean():.1f} %, task segments '
                     f'{100 * fl[d["task"]].mean():.1f} %')
            if key == 'R':
                per = [f'{S9.GESTURES[g]} {100 * fl[d["cal_rows"][d["cal_lab"] == g]].mean():.0f} %' for g in S9.SETS['S7']]
                L.append('    cued windows flagged per class: ' + ', '.join(per))
        if key == 'R':
            d2 = D[1]
            c, h = d2['tr'] <= CLEAN, d2['tr'] >= HUM
            fl = d2['R'] > T
            ok = fl[h].mean() >= 0.90 and fl[c].mean() <= 0.05
            L.append(f'  R18 decision (day 2): recall {100 * fl[h].mean():.1f} % (>= 90), false {100 * fl[c].mean():.1f} % '
                     f'(<= 5) -> {"PASS" if ok else "FAIL"}\n')
    txt = '\n'.join(L)
    print(txt)
    open(os.path.join(a.out, 'r18.txt'), 'w').write(txt + '\n')


if __name__ == '__main__':
    main()
