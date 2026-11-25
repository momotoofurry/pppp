"""35.97 part 4: split every 200 ms window into mains hum (least-squares fit of 60k Hz sinusoids, k = 1..8) and the rest"""
import pickle, sys, numpy as np
from scipy.signal import sosfilt, butter
sys.path.insert(0, '/work/src')
import selftest_analysis as SA
D = pickle.load(open('/sp/days.pkl', 'rb'))
GN = ['Ext', 'Flex', 'Rad', 'Uln', 'Point', 'Thumb', 'Open', 'Fist', 'Rest']
S7 = [0, 1, 2, 3, 6, 7, 8]
FS, WIN, STEP = 2000, 400, 200
np.set_printoptions(precision=1, suppress=True, linewidth=170)
sos = butter(4, (10 / 1000, 500 / 1000), btype='bandpass', output='sos')
t = np.arange(WIN) / FS
out = {}
for name, d in D.items():
    X, t0, rate = SA.load_emg(f'/sd/T00/{name}/{name}_emg.csv')
    x = sosfilt(sos, X[:, :4].astype(np.float64), axis=0)
    nw = d['F'].shape[0]
    # best mains frequency: scan 59.8..60.2 on the rest windows
    def fit(f0, idx):
        H = np.column_stack([fn(2 * np.pi * f0 * k * t) for k in range(1, 9) for fn in (np.sin, np.cos)])
        P = H @ np.linalg.pinv(H)
        hum = np.zeros((len(idx), 4)); res = np.zeros((len(idx), 4))
        for j, i in enumerate(idx):
            seg = x[i * STEP:i * STEP + WIN]
            h = P @ seg
            hum[j] = np.sqrt((h ** 2).mean(0)); res[j] = np.sqrt(((seg - h) ** 2).mean(0))
        return hum, res
    rest = d['cal_rows'][d['cal_lab'] == 8]
    fbest = max(np.arange(59.8, 60.21, 0.02), key=lambda f: fit(f, rest[:60])[0].sum())
    hum, res = fit(fbest, np.arange(nw))
    out[name] = dict(hum=hum, res=res, f0=fbest)
    print(f'===== {name}: mains {fbest:.2f} Hz')
    y = d['cal_lab']
    for g in S7:
        r = d['cal_rows'][y == g]
        print(f'{GN[g]:5s} hum RMS uV {np.median(hum[r],0)*1e6}   rest-of-signal RMS uV {np.median(res[r],0)*1e6}')
    q = np.percentile(hum, [10, 50, 90], axis=0) * 1e6
    print('whole recording hum RMS uV p10/p50/p90 per ch:\n', q)
    # hum over time: in 10 blocks
    B = np.array_split(np.arange(nw), 10)
    print('hum RMS uV median per tenth of the recording (rows=block):\n', np.array([np.median(hum[b], 0) * 1e6 for b in B]).T)
pickle.dump(out, open('/sp/hum.pkl', 'wb'))
