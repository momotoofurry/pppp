r"""Report 35.97, R16b (results/structure_97/PREREG_R16.md addendum): log of the amplitude features on NinaPro DB6,
db6_sim.py protocol (fixed / cue1 accumulated / within). Usage (container, /db6 = D:\db6_compact):
python src/structure_r16_db6.py"""
import os, sys
import numpy as np
from scipy import stats as sst
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db6_sim as S  # noqa: E402

AMP = (0, 1, 4)


def logamp(F):
    F = F.copy()
    for k in AMP:
        F[:, k * 8:(k + 1) * 8] = np.log(np.maximum(F[:, k * 8:(k + 1) * 8], 1e-12))
    return F


def run(subject, tf):
    sess = [S.trials(os.path.join(S.FEAT, f'S{subject}_D{d}_T{t}.npz')) for d, t in S.SESSIONS]
    sess = [(tf(F), tr, sh) for F, tr, sh in sess]
    F0, tr0, _ = sess[0]
    X0, y0 = S.cat(F0, tr0, range(S.N_REP))
    m0, s0 = X0.mean(0), X0.std(0)
    bad = ~np.isfinite(s0) | (s0 == 0)
    m0[bad], s0[bad] = 0.0, np.inf
    base = S.RunLDA(); base.add((X0 - m0) / s0, y0); base.fit()
    cum = base.copy()
    res = {'fixed': [], 'cue1': [], 'within': []}
    for F, tr, _ in sess[1:]:
        if any(i is None for c in range(S.K) for i in tr[c]) or len(tr[S.REST]) < S.N_REP:
            continue
        Z = (F - m0) / s0
        Z[:, bad] = 0.0
        Zc, yc = S.cat(Z, tr, S.CUE); Zp, yp = S.cat(Z, tr, S.PROBE); Zw, yw = S.cat(Z, tr, range(6))
        res['fixed'].append(S.acc(base, Zp, yp))
        for c in range(S.K):
            cum.learn(Zc[yc == c], c, fit=False)
        cum.fit()
        res['cue1'].append(S.acc(cum, Zp, yp))
        w = S.RunLDA(); w.add(Zw, yw)
        res['within'].append(S.acc(w.fit(), Zp, yp))
    return {k: float(np.mean(v)) for k, v in res.items()}


def main():
    out = {}
    for s in range(1, 11):
        out[s] = (run(s, lambda F: F), run(s, logamp))
        print(s, {k: round(v, 1) for k, v in out[s][0].items()}, {k: round(v, 1) for k, v in out[s][1].items()}, flush=True)
    lines = ['R16b (35.97): NinaPro DB6, 10 people, mean over the later sessions; B0 vs L (log RMS / WL / MAV)']
    for m in ('fixed', 'cue1', 'within'):
        b = np.array([out[s][0][m] for s in out]); l = np.array([out[s][1][m] for s in out]); d = l - b
        h = sst.t.ppf(0.975, len(d) - 1) * d.std(ddof=1) / np.sqrt(len(d))
        lines.append(f'{m:7s} B0 {b.mean():.2f}  L {l.mean():.2f}  diff {d.mean():+.2f} (95% CI {d.mean()-h:+.2f}, {d.mean()+h:+.2f})  better in {(d>0).sum()}/10')
        if m == 'cue1':
            ok = d.mean() >= 1 and d.mean() - h > 0
            lines.append(f'  R16b: {"L GENERALISES" if ok else "not shown to generalise"}')
    txt = '\n'.join(lines); print(txt)
    open(os.path.join(S.OUT, 'structure_97', 'r16b_db6.txt'), 'w').write(txt + '\n')


if __name__ == '__main__':
    main()
