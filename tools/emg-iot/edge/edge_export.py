"""Edge node, offline part: turn a recorded self-test session into the stream the edge (board + bridge) would emit,
one record per 200 ms window every 100 ms:
  t_ms      unix ms at the window's end
  phase     cal / probe / task / idle
  label     the cued class (cal and probe windows), else -1
  pred      class predicted by the session's model (S7 set, board LDA, log of amplitude features = report 35.97 L)
  rms1-4    RMS of the band-passed signal, uV
  hum1-4    mains hum RMS, uV (least-squares fit of 8 harmonics of 59.98 Hz, report 35.97)
Runs in the rf-emg container with the thesis repo mounted at /model (read only).
usage: python edge_export.py --dir /sd/T00 --days T00_d1_G T00_d2_G --out /out
"""
import argparse, os, sys
import numpy as np
from scipy.signal import butter, sosfilt
sys.path.insert(0, '/model/src')
import selftest_analysis as SA          # noqa: E402
import selftest9_analysis as S9         # noqa: E402
import structure_r16 as R16             # noqa: E402

F0, NH = 59.98, 8


def hum_rms(x, nw):
    t = np.arange(SA.WIN) / SA.FS
    H = np.column_stack([fn(2 * np.pi * F0 * k * t) for k in range(1, NH + 1) for fn in (np.sin, np.cos)])
    P = H @ np.linalg.pinv(H)
    rms, hum = np.zeros((nw, 4)), np.zeros((nw, 4))
    for i in range(nw):
        seg = x[i * SA.STEP:i * SA.STEP + SA.WIN]
        h = P @ seg
        rms[i] = np.sqrt((seg ** 2).mean(0))
        hum[i] = np.sqrt((h ** 2).mean(0))
    return rms * 1e6, hum * 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--days', nargs='+', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    sos = butter(4, (10 / 1000, 500 / 1000), btype='bandpass', output='sos')
    for name in a.days:
        d = S9.load_day(a.dir, name, 4.0, need=set(S9.SETS['S7']))
        X, t0, _ = SA.load_emg(os.path.join(S9.day_folder(a.dir, name), f'{name}_emg.csv'))
        x = sosfilt(sos, X[:, :4].astype(np.float64), axis=0)
        nw = len(d['F'])
        rms, hum = hum_rms(x, nw)
        F = R16.transform(d['F'], 'L')
        mdl = S9.Model(F, d['cal_rows'], d['cal_lab'], S9.SETS['S7'])
        pred = mdl.predict(F)
        phase = np.array(['idle'] * nw, dtype=object)
        label = np.full(nw, -1)
        for _, kind, pay in d['events']:
            if kind == 'trial':
                phase[pay[0]] = 'task'
        keep = np.isin(d['cal_lab'], S9.SETS['S7'])
        phase[d['cal_rows'][keep]] = 'cal'
        label[d['cal_rows'][keep]] = d['cal_lab'][keep]
        for p in d['probes']:
            for w, g in p:
                if g in S9.SETS['S7']:
                    phase[w] = 'probe'
                    label[w] = g
        t_ms = t0 + (np.arange(nw) * SA.STEP + SA.WIN) / SA.FS * 1000
        path = os.path.join(a.out, f'{name}_edge.csv')
        with open(path, 'w') as f:
            f.write('t_ms,phase,label,pred,' + ','.join(f'rms{c}' for c in range(1, 5)) + ',' + ','.join(f'hum{c}' for c in range(1, 5)) + '\n')
            for i in range(nw):
                f.write(f'{t_ms[i]:.1f},{phase[i]},{label[i]},{pred[i]},' + ','.join(f'{v:.2f}' for v in rms[i]) + ','
                        + ','.join(f'{v:.2f}' for v in hum[i]) + '\n')
        lab = label >= 0
        print(f'{name}: {nw} windows, phases {dict(zip(*np.unique(phase, return_counts=True)))}, '
              f'labelled accuracy {100 * (pred[lab] == label[lab]).mean():.1f} %  -> {path}')


if __name__ == '__main__':
    main()
