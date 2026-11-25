"""Report 35.106: the absolute 60 Hz hum estimate the MCU can compute from features.c's PSD, in uV.

Per channel, from the one-sided periodogram P of the Hamming-windowed 200 ms window (400 samples) zero-padded to 512
(as features.c): the power in the 52-68 Hz bins minus the EMG floor under them (the mean bin power of 32-46 Hz and
74-88 Hz times the number of hum bins), converted to an RMS with Parseval: a sinusoid of RMS a gives a one-sided
periodogram total of a^2 * NFFT * sum(w^2). (35.105 forgot NFFT: its estimates were sqrt(512) = 22.6 times too big.)
Window value = max over the channels. Only the 60 Hz fundamental.
  hum_uv(P) -> (windows,) uV;  synthetic self-test: python src/hum_abs.py --selftest"""
import sys

import numpy as np

FS, WIN, STEP, NFFT = 2000, 400, 200, 512
DF = FS / NFFT
HAM = 0.54 - 0.46 * np.cos(2 * np.pi * np.arange(WIN) / WIN)
GAIN = NFFT * (HAM ** 2).sum()


def bins(lo, hi):
    return [k for k in range(NFFT // 2 + 1) if lo <= k * DF <= hi]


HUM_BINS = bins(52, 68)
NB_BINS = bins(32, 46) + bins(74, 88)


def psd_windows(x, nw):
    """(nw, ch, bins): features.c's one-sided periodogram (periodic Hamming, zero-padded to 512, x2 except DC / Nyquist)"""
    idx = np.arange(WIN)[None, :] + STEP * np.arange(nw)[:, None]
    seg = x[idx] * HAM[None, :, None]
    P = np.abs(np.fft.rfft(seg, NFFT, axis=1)) ** 2
    P[:, 1:-1] *= 2
    return np.transpose(P, (0, 2, 1))


def hum_ch(P):
    """(nw, ch) hum RMS estimate (same unit as the signal)"""
    excess = P[:, :, HUM_BINS].sum(2) - P[:, :, NB_BINS].mean(2) * len(HUM_BINS)
    return np.sqrt(np.maximum(excess, 0) / GAIN)


def hum_uv(P):
    return hum_ch(P).max(1) * 1e6


def selftest():
    rng = np.random.default_rng(0)
    n = 2000 * 20
    t = np.arange(n) / FS
    ok = True
    for a_uv, emg_uv, f in ((10, 0, 59.98), (10, 3, 59.98), (3, 3, 59.98), (10, 30, 59.98), (5, 50, 60.1), (0, 30, 60)):
        a = a_uv * 1e-6
        x = a * np.sqrt(2) * np.sin(2 * np.pi * f * t + 0.3) + emg_uv * 1e-6 * rng.standard_normal(n)
        x = np.column_stack([x, 0.1 * x])
        nw = (n - WIN) // STEP + 1
        est = hum_uv(psd_windows(x, nw))
        med = float(np.median(est))
        print(f'  hum {a_uv:4.1f} uV + white noise {emg_uv:4.1f} uV ({f} Hz): estimate median {med:5.2f} uV, '
              f'p10-p90 {np.percentile(est, 10):.2f}-{np.percentile(est, 90):.2f}')
        if a_uv > 0:
            ok &= abs(med - a_uv) / a_uv < 0.15
        else:
            ok &= med < 1.0
    print('SELFTEST', 'OK' if ok else 'FAILED')
    return ok


if __name__ == '__main__' and '--selftest' in sys.argv:
    sys.exit(0 if selftest() else 1)
