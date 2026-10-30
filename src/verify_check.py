"""Day-1 calibration check (VALIDATION_PLAN.md, report 22): right after the one-shot calibration the user does each
gesture once more (2 s, labelled); the calibration is redone when the new model gets too few of these windows right.
Simulated on the development data (arm_position, 20 subjects x 3 seeds): verification = the first recording of each
gesture in test block 0 (same session and arm position as the calibration; windows 9..18 -> 60 windows), classified
by the one-shot model (C, as stress_check.py; no alignment on day 1). Calibrations: normal, half (5 of 10 windows per
gesture), low (raw EMG x 0.5). Reports the verification accuracy per calibration and, per threshold, how often each
calibration passes. Writes results/verify_check.csv and verify_check_summary.csv.
Usage (in the container): python src/verify_check.py [--jobs 19]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_features_c as FC  # noqa: E402
import pipeline as P  # noqa: E402
import shift_sweep as SH  # noqa: E402
import stress_check as ST  # noqa: E402
from pipeline import emg_functions  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
THRESHOLDS = [50, 55, 60, 65, 70, 75, 80]
PER_WIN = FC.NWIN - FC.W0                                            # 10 scored windows per recording


def job(subject, seed):
    lib = ST.build()
    emg_functions.get_predictions = lambda mdl, f: (P.predict(mdl, np.asarray(f), SH.PREC), None)
    z = np.load(SH.prepare(subject, 0))
    Xc, yc = z['Xc'], z['yc']
    half = (np.arange(len(yc)) % PER_WIN) < 5
    cals = {'normal': (Xc, yc), 'half': (Xc[half], yc[half]), 'low': ST.low_cal(subject)}
    X0, y0 = np.ascontiguousarray(z['X0'], dtype=np.float32), z['y0'].astype(int)
    rec_y = y0[::PER_WIN]
    first = [int(np.flatnonzero(rec_y == c)[0]) for c in range(6)]
    rows_v = np.concatenate([np.arange(r * PER_WIN, (r + 1) * PER_WIN) for r in first])
    out = []
    for name, (Xcal, ycal) in cals.items():
        md = ST.model(subject, seed, Xcal, ycal)
        lib.sc_init(ST.ctypes.byref(md['m']), md['cal'].ctypes.data, md['caly'].ctypes.data, len(md['cal']), 1)
        lib.ad_init(md['mu'].ctypes.data, md['inv'].ctypes.data, md['calf'].ctypes.data, len(md['calf']))
        q = np.zeros(80, np.int16)
        ok = np.zeros(6)
        for i in rows_v:
            lib.ad_normalize(X0[i].ctypes.data, q.ctypes.data)
            ok[y0[i]] += lib.sc_predict_oneshot(q.ctypes.data) == y0[i]
        out.append(dict(subject=subject, seed=seed, cal=name, verify_acc=ok.sum() / len(rows_v) * 100,
                        worst_gesture=ok.min() / PER_WIN * 100))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=19)
    args = ap.parse_args()
    ST.build()
    FC.lib()
    res = Parallel(n_jobs=args.jobs, verbose=2)(delayed(job)(s, seed) for s in range(20) for seed in range(3))
    df = pd.DataFrame([r for rs in res for r in rs])
    df.to_csv(os.path.join(OUT, 'verify_check.csv'), index=False, float_format='%.2f')
    rows = []
    for name, g in df.groupby('cal'):
        row = dict(cal=name, runs=len(g), mean=g.verify_acc.mean(), p05=g.verify_acc.quantile(0.05),
                   min=g.verify_acc.min(), max=g.verify_acc.max())
        for t in THRESHOLDS:
            row[f'pass_{t}'] = (g.verify_acc >= t).mean() * 100
        rows.append(row)
    sm = pd.DataFrame(rows)
    sm.to_csv(os.path.join(OUT, 'verify_check_summary.csv'), index=False, float_format='%.2f')
    pd.set_option('display.width', 220)
    print(sm.round(1).to_string(index=False))


if __name__ == '__main__':
    main()
