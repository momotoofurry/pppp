"""35.97: cache the self-test days' features and labels (selftest9_analysis.load_day) for the structure study"""
import pickle, sys, os
sys.path.insert(0, '/work/src')
import selftest9_analysis as S9
out = {}
for name in sys.argv[1:]:
    d = S9.load_day('/sd/T00', name, 4.0)
    out[name] = dict(F=d['F'], cal_rows=d['cal_rows'], cal_lab=d['cal_lab'], probes=d['probes'],
                     trials=[e[2] for e in d['events'] if e[1] == 'trial'], rate=d['rate'])
    print(name, d['F'].shape, 'cal', len(d['cal_rows']), 'probes', [len(p) for p in d['probes']], 'trials', d['trials'])
pickle.dump(out, open('/sp/days.pkl', 'wb'))
