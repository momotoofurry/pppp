"""35.98 part 1: does the noise-floor model hold? Model per channel: P = RMS^2 = e^2 p_c^2 + s2 (s2 = noise floor power).
Prediction: after F (log sqrt(max(P - s2, k s2)), k = 0.1) the within-class effort direction of every class becomes the
common direction (1,1,1,1)/2 and the class spreads become more equal (closer to LDA's shared covariance).
No classifier, no accuracy."""
import pickle, numpy as np
from scipy import stats
D = pickle.load(open('/sp/days.pkl', 'rb'))
GN = ['Ext', 'Flex', 'Rad', 'Uln', 'Point', 'Thumb', 'Open', 'Fist', 'Rest']
ACT = [0, 1, 2, 3, 6, 7]
K = 0.1
np.set_printoptions(precision=2, suppress=True, linewidth=160)
for name, d in D.items():
    for fk in ('F', 'Fn'):
        F = d[fk]; X, y = F[d['cal_rows']], d['cal_lab']
        P = X[:, :4] ** 2
        s2 = np.median(P[y == 8], 0)
        Lg = 0.5 * np.log(P)
        Fl = 0.5 * np.log(np.maximum(P - s2, K * s2))
        print(f'== {name} {"notched" if fk == "Fn" else "raw"}: rest floor RMS uV {np.sqrt(s2)*1e6}')
        for lab, V in (('log ', Lg), ('logF', Fl)):
            cs, sh, sk = [], [], []
            for g in ACT:
                w, v = np.linalg.eigh(np.cov(V[y == g].T))
                u = v[:, -1] * np.sign(v[:, -1].sum()); cs.append(u.sum() / 2); sh.append(w[-1] / w.sum())
                sk.append(np.abs(stats.skew(V[y == g], axis=0)).mean())
            sd = np.array([V[y == g].std(0) for g in ACT])
            floor_share = np.mean([(P[y == g] - s2 < K * s2).mean() for g in ACT])
            print(f'  {lab}: cos(effort dir,(1,1,1,1)) per class {np.array(cs)}  mean {np.mean(cs):.2f} | top-PC share {np.mean(sh):.2f}'
                  f' | class SD max/min per ch {(sd.max(0)/sd.min(0)).round(1)} | |skew| {np.mean(sk):.2f}'
                  + (f' | clipped {floor_share*100:.1f} %' if lab == 'logF' else ''))
