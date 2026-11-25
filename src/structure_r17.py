"""Report 35.98, rule R17 (results/structure_97/PREREG_R17.md): OAS shrinkage with the Kish effective sample size
N_eff = N / (1 + (m - 1) ICC), on top of L (log RMS / WL / MAV). Self-test S7 (board model) and NinaPro DB6 (cue1).
usage (container): python src/structure_r17.py --dir /sd/T00 --days T00_d1_G T00_d2_G --out results/structure_97"""
import argparse, os, sys
import numpy as np
from scipy import stats as sst
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lda_robust as LR            # noqa: E402
import selftest9_analysis as S9    # noqa: E402
import structure_r16 as R16        # noqa: E402
import structure_r16_db6 as R16b   # noqa: E402

ICC0 = 0.25
GRID = (0.0, 0.05, 0.1, 0.25, 0.5, 1.0)
_orig = LR.oas_solve
DEFF = [1.0]


def oas_eff(Sw, N, m):
    return _orig(Sw, N / DEFF[0], m)


LR.oas_solve = oas_eff


def selftest(dirn, names):
    days = [S9.load_day(dirn, n, 4.0, need=set(S9.SETS['S7'])) for n in names]
    days = [dict(d, F=R16.transform(d['F'], 'L')) for d in days]
    out = {}
    for icc in GRID:
        DEFF[0] = 1 + (30 - 1) * icc
        A, X = [], []
        for d in days:
            mdl = S9.Model(d['F'], d['cal_rows'], d['cal_lab'], S9.SETS['S7'])
            probes, _ = S9.run_day(d, S9.SETS['S7'], mdl, False)
            A.append(R16.acc([it for p in probes for it in p]))
        for i in range(2):
            probes, _ = S9.replay_fixed([days[i], days[1 - i]], 'S7')[0]
            X.append(R16.acc([it for p in probes for it in p]))
        out[icc] = (A, X)
    return out


def db6():
    out = {}
    for icc in GRID:
        DEFF[0] = 1 + (10 - 1) * icc
        out[icc] = {s: R16b.run(s, R16b.logamp) for s in range(1, 11)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--days', nargs='+', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    st, dd = selftest(a.dir, a.days), db6()
    L = [f'R17 (35.98): Kish-corrected OAS on top of L; ICC fixed {ICC0} (decision), others = sensitivity\n',
         'Self-test S7 (m 30): ICC  A per day  mean  | cross-day fixed mean']
    for icc in GRID:
        A, X = st[icc]
        L.append(f'  {icc:4.2f}  {np.round(A, 1)}  {np.mean(A):.1f}  | {np.mean(X):.1f}')
    L.append('DB6 cue1 / fixed / within (m 10), mean over 10 people:')
    for icc in GRID:
        L.append(f'  {icc:4.2f}  ' + '  '.join(f'{k} {np.mean([dd[icc][s][k] for s in dd[icc]]):.2f}' for k in ('cue1', 'fixed', 'within')))
    dA = np.array(st[ICC0][0]) - np.array(st[0.0][0])
    ok1 = dA.mean() >= 1 and (dA > 0).all()
    d = np.array([dd[ICC0][s]['cue1'] - dd[0.0][s]['cue1'] for s in range(1, 11)])
    h = sst.t.ppf(0.975, 9) * d.std(ddof=1) / np.sqrt(10)
    ok2 = d.mean() - h > 0
    L.append(f'\nDecision: self-test dA {np.round(dA, 1)} mean {dA.mean():+.1f} -> {"pass" if ok1 else "fail"};'
             f' DB6 cue1 diff {d.mean():+.2f} (95% CI {d.mean()-h:+.2f}, {d.mean()+h:+.2f}), better in {(d>0).sum()}/10 -> {"pass" if ok2 else "fail"}')
    L.append(f'R17: K is {"a CANDIDATE" if ok1 and ok2 else "NOT adopted"}')
    txt = '\n'.join(L); print(txt)
    open(os.path.join(a.out, 'r17.txt'), 'w').write(txt + '\n')


if __name__ == '__main__':
    main()
