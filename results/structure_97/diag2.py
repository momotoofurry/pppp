"""35.97 structure study, part 2: what changes between the two donnings? (S7 classes, cued windows)"""
import pickle, numpy as np
D = pickle.load(open('/sp/days.pkl', 'rb'))
GN = ['Ext', 'Flex', 'Rad', 'Uln', 'Point', 'Thumb', 'Open', 'Fist', 'Rest']
S7 = [0, 1, 2, 3, 6, 7, 8]
np.set_printoptions(precision=2, suppress=True, linewidth=160)
idx = [k * 8 + c for k in range(10) for c in range(4)]
def amp(d):
    X = d['F'][d['cal_rows']][:, idx]; y = d['cal_lab']; k = np.isin(y, S7)
    return X[k], y[k]
(X1, y1), (X2, y2) = amp(D['T00_d1_G']), amp(D['T00_d2_G'])
R1, R2 = np.log(X1[:, :4]), np.log(X2[:, :4])        # log RMS, ch1-4
print('log RMS class means (rows class, cols ch1-4); day1 | day2 | diff')
M1 = np.array([R1[y1 == g].mean(0) for g in S7]); M2 = np.array([R2[y2 == g].mean(0) for g in S7])
for i, g in enumerate(S7):
    print(f'{GN[g]:5s}', M1[i], '|', M2[i], '|', M2[i] - M1[i])
Dl = M2 - M1
b = Dl.mean(0)
print('common per-channel offset b (mean over classes):', b)
res = Dl - b
print('share of shift energy explained by common offset b:', round(1 - (res ** 2).sum() / (Dl ** 2).sum(), 3))
# effort: per class, mean over channels of log RMS above Rest (pattern magnitude)
e1 = (M1 - M1[-1]).mean(1); e2 = (M2 - M2[-1]).mean(1)
print('log-effort above rest per class  day1', e1, '\n                                 day2', e2)
# residual after common offset: is it explained by per-class effort scalar (x along (1,1,1,1))?
res2 = res - res.mean(1, keepdims=True)
print('after removing per-channel offset AND per-class common level: residual share', round((res2 ** 2).sum() / (Dl ** 2).sum(), 3))
# pattern similarity: direction of (class mean - rest mean) in linear amplitude, day1 vs day2
A1 = np.array([X1[y1 == g, :4].mean(0) for g in S7]); A2 = np.array([X2[y2 == g, :4].mean(0) for g in S7])
P1 = A1[:-1] - A1[-1]; P2 = A2[:-1] - A2[-1]
P1n = P1 / np.linalg.norm(P1, axis=1, keepdims=True); P2n = P2 / np.linalg.norm(P2, axis=1, keepdims=True)
print('cos(pattern day1, pattern day2) per active class (RMS above rest):', (P1n * P2n).sum(1))
print('pattern magnitude ratio day2/day1:', np.linalg.norm(P2, axis=1) / np.linalg.norm(P1, axis=1))
print('cos between classes day1 (how separable are directions):\n', P1n @ P1n.T)
# noise floor vs active: rest RMS / class RMS per channel
print('rest RMS / class RMS (day1), channel near 1 = channel at noise floor for that class:\n', A1[-1] / A1[:-1])
