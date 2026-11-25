"""35.98 part 2: is each class's covariance = shared covariance + ONE class-specific direction?
Space: L + U (log RMS/WL/MAV, 40 distinct features), session z-score. Whiten with the pooled within-class covariance
(OAS-shrunk, as the board), then per class C_c = W^T S_c W. Shared covariance (LDA) => C_c ~ I. Model 'shared + rank 1'
=> one eigenvalue clearly above the Marchenko-Pastur edge (1 + sqrt(d/n))^2 of pure sampling noise, the rest not.
No classifier, no accuracy."""
import pickle, numpy as np
D = pickle.load(open('/sp/days.pkl', 'rb'))
GN = ['Ext', 'Flex', 'Rad', 'Uln', 'Point', 'Thumb', 'Open', 'Fist', 'Rest']
S7 = [0, 1, 2, 3, 6, 7, 8]
UNIQ = [k * 8 + c for k in range(10) for c in range(4)]
def LU(F):
    F = F.copy()
    for k in (0, 1, 4):
        F[:, k * 8:(k + 1) * 8] = np.log(np.maximum(F[:, k * 8:(k + 1) * 8], 1e-12))
    return F[:, UNIQ]
np.set_printoptions(precision=2, suppress=True, linewidth=160)
for name, d in D.items():
    for fk in ('F', 'Fn'):
        X, y = LU(d[fk][d['cal_rows']]), d['cal_lab']
        k = np.isin(y, S7); X, y = X[k], y[k]
        Z = (X - X.mean(0)) / X.std(0)
        dd = Z.shape[1]
        R = np.vstack([Z[y == g] - Z[y == g].mean(0) for g in S7]); N = len(R)
        Sw = R.T @ R / N
        mu = np.trace(Sw) / dd; al = np.mean(Sw ** 2)
        rho = min((al + mu ** 2) / ((N + 1) * (al - mu ** 2 / dd)), 1)
        Sh = (1 - rho) * Sw + rho * mu * np.eye(dd)
        w, V = np.linalg.eigh(Sh); W = V / np.sqrt(w)
        print(f'== {name} {"notched" if fk == "Fn" else "raw"} (d {dd}, OAS rho {rho:.3f})')
        for g in S7:
            Zg = (Z[y == g] - Z[y == g].mean(0)) @ W; n = len(Zg)
            ev = np.sort(np.linalg.eigvalsh(Zg.T @ Zg / n))[::-1]
            mp = (1 + np.sqrt(dd / n)) ** 2 * np.mean(ev[1:])     # MP edge, scaled to the class's bulk level
            print(f'  {GN[g]:5s} n {n}  top eig {ev[0]:6.2f}  2nd {ev[1]:5.2f}  3rd {ev[2]:5.2f}  bulk mean {np.mean(ev[1:]):.2f}'
                  f'  MP edge {mp:5.2f}  above edge: {int((ev > mp).sum())}')
