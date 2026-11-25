"""35.98: add the notched features (structure_r16.notch_sos) to the cache"""
import pickle, sys, numpy as np
from scipy.signal import sosfilt
sys.path.insert(0, '/work/src')
import selftest_analysis as SA, structure_r16 as R
D = pickle.load(open('/sp/days.pkl', 'rb'))
for name, d in D.items():
    X, _, _ = SA.load_emg(f'/sd/T00/{name}/{name}_emg.csv')
    d['Fn'] = SA.features(sosfilt(R.notch_sos(), X.astype(np.float64), axis=0).astype(np.float32))
    print(name, d['Fn'].shape)
pickle.dump(D, open('/sp/days.pkl', 'wb'))
