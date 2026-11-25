"""Report 35.97, rule R16 (results/structure_97/PREREG_R16.md): front-end changes derived from the structure of the
self-test data, evaluated with the board's model (selftest9_analysis.Model / run_day), gesture set S7.

  B0  current: 80 features (fe_recording)
  N   causal IIR notch at k x F0 (k = 1..8, 2 Hz wide) before the features
  U   the 40 distinct features (ch5-8 are copies of ch1-4)
  L   log of RMS, WL, MAV before the session z-score
usage: python src/structure_r16.py --dir /sd/T00 --days T00_d1_G T00_d2_G --out results/structure_97
"""
import argparse, os, sys
import numpy as np
from scipy.signal import iirnotch, sosfilt, tf2sos
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import selftest_analysis as SA          # noqa: E402
import selftest9_analysis as S9         # noqa: E402

F0, NH, BW = 59.98, 8, 2.0
UNIQ = [k * 8 + c for k in range(10) for c in range(4)]
AMP = (0, 1, 4)                          # RMS, WL, MAV
CONDS = ['B0', 'N', 'U', 'L', 'N+U', 'N+U+L']


def notch_sos():
    return np.vstack([tf2sos(*iirnotch(k * F0, k * F0 / BW, fs=SA.FS)) for k in range(1, NH + 1)])


def transform(F, cond):
    F = F.copy()
    if 'L' in cond.split('+'):
        for k in AMP:
            F[:, k * 8:(k + 1) * 8] = np.log(np.maximum(F[:, k * 8:(k + 1) * 8], 1e-12))
    if 'U' in cond.split('+'):
        F = F[:, UNIQ]
    return F


def acc(items):
    return 100 * np.concatenate([pr == g for _, g, pr in items]).mean()


def rest_recall(items):
    v = [pr == g for _, g, pr in items if g == S9.REST]
    return 100 * np.concatenate(v).mean()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--days', nargs='+', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--set', default='S7')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    need = set(S9.SETS[a.set])
    base, notched = [], []
    for name in a.days:
        d = S9.load_day(a.dir, name, 4.0, need=need)
        X, _, _ = SA.load_emg(os.path.join(S9.day_folder(a.dir, name), f'{name}_emg.csv'))
        Xn = sosfilt(notch_sos(), X.astype(np.float64), axis=0).astype(np.float32)
        Fn = SA.features(Xn)
        assert Fn.shape == d['F'].shape
        base.append(d)
        notched.append(dict(d, F=Fn))
    rows = []
    lines = [f'R16 (35.97), set {a.set}, days {a.days}; notch {NH} harmonics of {F0} Hz, {BW} Hz wide\n']
    res = {}
    for cond in CONDS:
        src = notched if cond.startswith('N') else base
        days = [dict(d, F=transform(d['F'], cond)) for d in src]
        A, R, C = [], [], []
        for d in days:
            mdl = S9.Model(d['F'], d['cal_rows'], d['cal_lab'], S9.SETS[a.set])
            probes, cmd = S9.run_day(d, S9.SETS[a.set], mdl, False)
            items = [it for p in probes for it in p]
            A.append(acc(items)); R.append(rest_recall(items)); C.append(100 * cmd['ok'] / max(cmd['trials'], 1))
        X12 = []
        for i in range(len(days)):
            for j in range(len(days)):
                if i != j:
                    probes, _ = S9.replay_fixed([days[i], days[j]], a.set)[0]
                    X12.append(acc([it for p in probes for it in p]))
        res[cond] = dict(A=A, R=R, C=C, X=X12)
        lines.append(f'{cond:7s} A per day {np.round(A, 1)} mean {np.mean(A):.1f} | Rest recall {np.round(R, 1)} | '
                     f'task command acc {np.round(C, 1)} | cross-day fixed {np.round(X12, 1)} mean {np.mean(X12):.1f}')
        for k, v in enumerate(A):
            rows.append(dict(cond=cond, day=a.days[k], A=v, rest=R[k], cmd=C[k]))
    lines.append('\nDecision (PREREG_R16): candidate if mean dA >= +2 and dA > 0 on every day')
    b = np.array(res['B0']['A'])
    for cond in CONDS[1:]:
        dA = np.array(res[cond]['A']) - b
        ok = dA.mean() >= 2 and (dA > 0).all()
        lines.append(f'  {cond:7s} dA {np.round(dA, 1)} mean {dA.mean():+.1f}  dCross {np.mean(res[cond]["X"]) - np.mean(res["B0"]["X"]):+.1f}'
                     f'  -> {"CANDIDATE" if ok else "not adopted"}')
    txt = '\n'.join(lines)
    print(txt)
    open(os.path.join(a.out, f'r16_{a.set}.txt'), 'w').write(txt + '\n')
    import csv
    with open(os.path.join(a.out, f'r16_{a.set}.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


if __name__ == '__main__':
    main()
