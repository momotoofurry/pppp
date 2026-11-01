"""Start-up alignment confidence on the development data (arm_position, 20 subjects): for the 6-gesture start-up
recording (first 60 windows of test block 0, as rt.c) with the raw EMG rotated by s positions (shift_sweep.raw_features,
s = 0, +-0.5, +-1, +-2), the 8 rotation scores of ad_align_finish (sum over 3 amplitude features x 8 channels of
calibration profile x rolled start-up profile; divided by 24 here, so a perfect match is 1) and the margin
best - score(k = 0). The C estimate (libstress.so, ad_align_finish with the confidence rule of report 25) is
checked against the python argmax + rule (k_old = plain argmax as pilot-freeze-3, k = after the rule).
Kyranou 2025 (--data): the same for A1 / A3 (strap not rotated) and A2 row 2 (half offset), NOT independent any more
(report 24); reported only to see the false rotations, not used to choose the rule.
Writes results/align_margin.csv. Usage (in the container): python src/align_margin.py [--data /data]
"""
import argparse
import ctypes
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as P  # noqa: E402
import shift_sweep as SH  # noqa: E402
import stress_check as ST  # noqa: E402

OUT = os.path.join(P.ROOT, 'results')
SHIFTS = (0, 0.5, -0.5, 1, -1, 2, -2)
N = ST.ALIGN_N
KMAX, MARGIN = 1, 0.20                       # adapt.h AD_ALIGN_KMAX, AD_ALIGN_MARGIN


def scores(Xc, X):
    q, p = SH.profile(Xc), SH.profile(X[:N])
    return np.array([np.sum(q * np.roll(p, k, axis=1)) for k in range(8)]) / q.size


def c_k(lib, Xc, X):
    mu, var = Xc.mean(0), Xc.var(0)
    mu32, inv = np.ascontiguousarray(mu, np.float32), np.ascontiguousarray(1 / np.sqrt(var), np.float32)
    calf = np.ascontiguousarray(Xc, np.float32)
    lib.ad_init(mu32.ctypes.data, inv.ctypes.data, calf.ctypes.data, len(calf))
    lib.ad_align_reset()
    X = np.ascontiguousarray(X[:N], np.float32)
    for i in range(N):
        lib.ad_align_push(X[i].ctypes.data)
    return lib.ad_align_finish()


def row(src, subject, case, truth, sc, kc):
    kb = int(np.argmax(sc))
    kb = kb if kb < 4 else kb - 8
    order = np.sort(sc)[::-1]
    k = kb if abs(kb) <= KMAX and order[0] - sc[0] >= MARGIN else 0
    assert k == kc, (src, subject, case, kb, k, kc)
    return dict(src=src, subject=subject, case=case, truth=truth, k_old=kb, k=k, score0=sc[0], best=order[0],
                second=order[1], margin=order[0] - sc[0], gap12=order[0] - order[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=None)
    args = ap.parse_args()
    lib = ST.build()
    rows = []
    for s in range(20):
        for sh in SHIFTS:
            z = np.load(SH.prepare(s, sh))
            Xc, X = z['Xc'], z['X0']
            # raw shift s: the right estimate is k = s (k = 0 or +-1 for s = +-0.5)
            rows.append(row('arm_position', s, f'shift {sh:+g}', sh, scores(Xc, X), c_k(lib, Xc, X)))
    if args.data:
        import external_check as E
        for p in E.SUBJECTS:
            d1 = [E.Session(args.data, p, 1, b) for b in (1, 2)]
            d2 = [E.Session(args.data, p, 2, b) for b in (1, 2)]
            r, g = d1[0].pick(5)
            cal = [r[np.flatnonzero(g == c)[0]] for c in range(6)]
            Xc = d1[0].features(cal, E.ROW1, 0)
            tests = {'A1': (d2, 5, E.ROW1, 0), 'A2_row2': (d1[1:], 5, E.ROW2, None)}
            for pos in E.A3_POS:
                tests[f'A3_P{pos}'] = (d1, pos, E.ROW1, 0)
            for case, (ss, pos, ch, truth) in tests.items():
                X = E.stream(ss, pos, ch, 0)[0][0].astype(np.float64)
                rows.append(row('kyranou', p, case, truth if truth is not None else np.nan, scores(Xc, X),
                                c_k(lib, Xc, X)))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, 'align_margin.csv'), index=False, float_format='%.4f')
    pd.set_option('display.width', 200)
    g = df.groupby(['src', 'case'], sort=False)
    print(g.agg(n=('k', 'size'), k_old=('k_old', lambda s: ' '.join(f'{a}:{b}' for a, b in s.value_counts().sort_index().items())),
                k_counts=('k', lambda s: ' '.join(f'{a}:{b}' for a, b in s.value_counts().sort_index().items())),
                margin_min=('margin', 'min'), margin_med=('margin', 'median'), margin_max=('margin', 'max')).round(3).to_string())


if __name__ == '__main__':
    main()
