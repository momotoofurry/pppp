"""35.97 part 3: why is Rest louder than gestures on day 1? peak frequency / mean frequency per class"""
import pickle, numpy as np
D = pickle.load(open('/sp/days.pkl', 'rb'))
GN = ['Ext', 'Flex', 'Rad', 'Uln', 'Point', 'Thumb', 'Open', 'Fist', 'Rest']
S7 = [0, 1, 2, 3, 6, 7, 8]
np.set_printoptions(precision=1, suppress=True, linewidth=160)
for name, d in D.items():
    F, y = d['F'][d['cal_rows']], d['cal_lab']
    print('=====', name)
    for g in S7:
        Xg = F[y == g]
        pk = Xg[:, [9 * 8 + c for c in range(4)]]
        mnf = Xg[:, [8 * 8 + c for c in range(4)]]
        rms = Xg[:, [c for c in range(4)]]
        f60 = (np.abs(pk - 60) < 4).mean(0)
        print(f'{GN[g]:5s} RMS(uV) {rms.mean(0)*1e6}  MNF {np.median(mnf,0)}  share of windows with PSD peak at 60 Hz {f60.round(2)}  median peak {np.median(pk,0)}')
    # whole recording: fraction of windows peak at 60
    pk = d['F'][:, [9 * 8 + c for c in range(4)]]
    print('whole recording, windows with PSD peak at 60+-4 Hz per channel:', (np.abs(pk - 60) < 4).mean(0).round(2))
