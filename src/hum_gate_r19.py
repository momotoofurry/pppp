"""Report 35.106, rule R19 (results/hum_106/PREREG_R19.md): the absolute 60 Hz gate, judged on the S7 days.
  python src/hum_gate_r19.py --dir /sd/T00 --days T00_d1_S T00_d2_S --out results/hum_106          (the decision)
  python src/hum_gate_r19.py --dir /sd/T00 --days T00_d1_G T00_d2_G --out results/hum_106 --dev    (dry run)
--dev writes r19_dryrun_<...>.txt and marks it as development (those days set T)."""
import argparse
import os
import sys

import numpy as np
from scipy.signal import butter, sosfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hum_abs as HA   # noqa: E402
import selftest_analysis as SA   # noqa: E402
import selftest9_analysis as S9  # noqa: E402

T, RHO = 7.07, 0.5
F0 = 59.98


def day(dirn, name):
    d = S9.load_day(dirn, name, 4.0, need=set(S9.SETS['S7']))
    X, _, _ = SA.load_emg(os.path.join(S9.day_folder(dirn, name), f'{name}_emg.csv'))
    sos = butter(4, (10 / 1000, 500 / 1000), btype='bandpass', output='sos')
    x = sosfilt(sos, X[:, :4].astype(np.float64), axis=0)
    nw = min(len(d['F']), (len(x) - HA.WIN) // HA.STEP + 1)
    Hc = HA.hum_ch(HA.psd_windows(x, nw)) * 1e6
    idx = np.arange(HA.WIN)[None, :] + HA.STEP * np.arange(nw)[:, None]
    rms = np.sqrt((x[idx] ** 2).mean(1)) * 1e6
    t = np.arange(20 * HA.STEP) / HA.FS
    Hm = np.column_stack([np.sin(2 * np.pi * F0 * t), np.cos(2 * np.pi * F0 * t)])
    Pm = Hm @ np.linalg.pinv(Hm)
    h = np.zeros((nw, 4))
    for b0 in range(0, nw, 20):
        seg = x[b0 * HA.STEP:b0 * HA.STEP + 20 * HA.STEP]
        if len(seg) < 20 * HA.STEP:
            seg = x[-20 * HA.STEP:]
        h[b0:b0 + 20] = np.sqrt(((Pm @ seg) ** 2).mean(0)) * 1e6
    task = np.zeros(nw, bool)
    for _, kind, pay in d['events']:
        if kind == 'trial':
            task[pay[0][pay[0] < nw]] = True
    return dict(name=name, Hc=Hc, rms=rms, h=h, task=task, cal_rows=d['cal_rows'], cal_lab=d['cal_lab'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--days', nargs='+', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--dev', action='store_true')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    D = [day(a.dir, n) for n in a.days]
    L = [('DEVELOPMENT DRY RUN (these days set T; NOT the decision)\n' if a.dev else '') +
         f'R19 (35.106): T {T} uV, RHO {RHO}; days {a.days}']
    # rule A
    judged, right = 0, 0
    for d in D:
        rest = d['cal_rows'][d['cal_lab'] == S9.REST]
        share = (d['Hc'][rest].max(1) > T).mean()
        alert = share >= 0.5
        truth = np.median(d['h'][rest].max(1))
        must = True if truth >= T else False if truth <= T / 2 else None
        if must is not None:
            judged += 1
            right += int(alert == must)
        L.append(f'A {d["name"]}: cued Rest over T {100 * share:.0f} % -> alert {alert}; truth median {truth:.2f} uV -> '
                 f'{"must alert" if must else "must not alert" if must is False else "not judged"}'
                 f'{"" if must is None else (" -> right" if alert == must else " -> WRONG")}')
    A = 'undecided (no judged session)' if judged == 0 else ('PASS' if right == judged else 'FAIL')
    L.append(f'Rule A: {right}/{judged} judged sessions right -> {A}')
    # rule B
    flag = np.concatenate([((d['Hc'] > T) & (d['Hc'] > RHO * d['rms'])).any(1) for d in D])
    harm = np.concatenate([((d['h'] > 1.5 * T) & (d['h'] > 1.5 * RHO * d['rms'])).any(1) for d in D])
    clean = np.concatenate([((d['h'] < T / 2) | (d['h'] < RHO / 2 * d['rms'])).all(1) for d in D])
    fp = flag[clean].mean()
    rec = flag[harm].mean() if harm.sum() else float('nan')
    rec_ok = True if harm.sum() < 30 else rec >= 0.90
    B = 'PASS' if (fp <= 0.05 and rec_ok) else 'FAIL'
    L.append(f'Rule B: HARMFUL windows {harm.sum()} recall {100 * rec:.1f} %{" (not judged: < 30)" if harm.sum() < 30 else ""}; '
             f'CLEAN windows {clean.sum()} false flags {100 * fp:.1f} % -> {B}')
    for d in D:
        f = ((d['Hc'] > T) & (d['Hc'] > RHO * d['rms'])).any(1)
        per = [f'{S9.GESTURES[g]} {100 * f[d["cal_rows"][d["cal_lab"] == g]].mean():.0f} %' for g in S9.SETS['S7']]
        L.append(f'  {d["name"]}: task windows flagged {100 * f[d["task"]].mean():.1f} %; cued: ' + ', '.join(per))
    txt = '\n'.join(L)
    print(txt)
    fn = ('r19_dryrun_' if a.dev else 'r19_') + '_'.join(a.days) + '.txt'
    open(os.path.join(a.out, fn), 'w').write(txt + '\n')


if __name__ == '__main__':
    main()
