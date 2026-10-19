"""One-shot confusion matrix (window level, no self-calibration, no rejection) of the recommended model
(100 trees / depth 10 / int16), 20 subjects x 11 test blocks, seed = subject. Gesture names and order from
Jiang et al. 2026 (J. Neural Eng. 23 016011) figure 1; label 5 = Rest is confirmed by the lowest RMS in all
20 subjects. Writes results/confusion_oneshot_N100_d10_int16.csv. Usage (in the container):
python src/confusion_oneshot.py
"""
import copy, os, sys
import numpy as np
sys.path.insert(0, '/work/src')
import pipeline as P, rf_size
from pipeline import emg_functions
NAMES = ['Power', 'Lateral', 'Tripod', 'Pointer', 'Open', 'Rest']
C = np.zeros((6, 6), int)
pre = P.load_pretrain()
for s in range(20):
    np.random.seed(s)
    Xc, yc, blocks = P.load_subject(s)
    pruned = P.prune(rf_size.truncate_depth(copy.deepcopy(pre), 10), Xc, yc)
    app = P.train_rf(Xc, yc, 50, 10, None)
    mdl = emg_functions.append(P.subset(pruned, range(50)), app)
    for X, y in blocks:
        p = P.predict(mdl, X, 'int16')
        for t, q in zip(y.astype(int), p.astype(int)):
            C[t, q] += 1
R = C / C.sum(1, keepdims=True) * 100
print('acc %.2f' % (np.trace(C) / C.sum() * 100))
print('true/pred   ' + ' '.join(f'{n[:7]:>8}' for n in NAMES))
for i, n in enumerate(NAMES):
    print(f'{n:>11} ' + ' '.join(f'{v:8.1f}' for v in R[i]))
np.savetxt('/work/results/confusion_oneshot_N100_d10_int16.csv', C, fmt='%d', delimiter=',', header=','.join(NAMES))
