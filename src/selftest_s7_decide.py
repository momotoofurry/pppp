"""S7 decision-rule sweep on the two self-test donnings (offline, cue model = cued pass only, never updated).

Rule = (K, P, M): per window, the LDA posterior (softmax of the discriminants); a window whose top posterior < P is
treated as Rest (rejected); optional majority vote over the last M windows (M = 1: none); a command = the first run of
K equal non-Rest (smoothed) labels. Baseline = (3, 0, 1) = selftest9_analysis.decide.

Tests, per donning:
  probe   every S7 non-Rest probe cue (3 probes x 2 s cues): windows from cue_on to cue_off + 0.5 s; first command:
          right / wrong / none, latency cue_on -> end of the K-th window.
  rest    false commands per minute: task rest periods (rest_on + SKIP s .. rest_off) and Rest probe cues
          (cue_on + 0.5 .. cue_off); a new command each time a K-run of one non-Rest label starts.
  task    task trials as in selftest9 (cut short: a trial ends when the board's own command came) - reference only.
Selection (fixed before looking at the test donning): on the tuning donning, among rules with rest false commands
<= 1.0 / min, the largest (right - wrong) % on probe; if none, the fewest false commands. Then report it on the other
donning (both directions).
"""
import os, sys, itertools
import numpy as np, pandas as pd
sys.path.insert(0, '/work/src')
import selftest_analysis as SA
import selftest9_analysis as S9

D, SKIP = sys.argv[1], 0.5
CL = S9.SETS['S7']
REST = S9.REST
WMS, SMS = SA.WIN / SA.FS * 1000, SA.STEP / SA.FS * 1000


def load(name):
    day = S9.load_day(D, name, 4.0)
    folder = S9.day_folder(D, name)
    X, t0, _ = SA.load_emg(os.path.join(folder, f'{name}_emg.csv'))
    nw = len(day['F'])
    # activity of each window: mean over ch1-4 of the window RMS, relative to the median of the cued Rest windows
    # (window mean removed: the raw signal carries a DC offset much larger than rest EMG)
    c1 = np.vstack([np.zeros((1, 4)), np.cumsum(X[:, :4], 0)])
    c2 = np.vstack([np.zeros((1, 4)), np.cumsum(X[:, :4] ** 2, 0)])
    st = np.arange(nw) * SA.STEP
    m1 = (c1[st + SA.WIN] - c1[st]) / SA.WIN
    rms = np.sqrt(np.maximum((c2[st + SA.WIN] - c2[st]) / SA.WIN - m1 ** 2, 0)).mean(1)
    # reference = median of the cued S7 gesture windows (day 1's cued Rest carried 60 Hz noise, so Rest is no anchor)
    gl = np.isin(day['cal_lab'], CL) & (day['cal_lab'] != REST)
    act = rms / np.median(rms[day['cal_rows'][gl]])
    task = pd.read_csv(os.path.join(folder, f'{name}_task.csv'), dtype=str, keep_default_na=False)
    task['t'] = task.unix_ms.astype(float)
    cues, rests, on = [], [], {}
    for r in task.itertuples():
        if r.segment == 'labelled' and r.event == 'cue_on':
            on[('c', r.step)] = r
        elif r.segment == 'labelled' and r.event == 'cue_off' and ('c', r.step) in on:
            a = on.pop(('c', r.step))
            g = S9.G[r.target]
            if g == REST:
                rests.append(SA.inside(t0, nw, a.t + 500, r.t))
            elif g in CL:
                cues.append((SA.inside(t0, nw, a.t, r.t + 500), g, a.t))
        elif r.segment == 'task' and r.event == 'rest_on':
            on[('r', r.step)] = r
        elif r.segment == 'task' and r.event == 'rest_off' and ('r', r.step) in on:
            a = on.pop(('r', r.step))
            rests.append(SA.inside(t0, nw, a.t + SKIP * 1000, r.t))
    trials = [pay for _, k, pay in day['events'] if k == 'trial' and pay[1] in CL]
    mdl = S9.Model(day['F'], day['cal_rows'], day['cal_lab'], CL)
    return dict(name=name, F=day['F'], t0=t0, cues=cues, rests=[w for w in rests if len(w)], trials=trials, mdl=mdl,
                act=act)


def labels(d, w, P, M, A):
    mdl = d['mdl']
    s = mdl.scores(d['F'][w])
    p = np.exp(s - s.max(1, keepdims=True)); p /= p.sum(1, keepdims=True)
    lab = np.array(mdl.classes)[p.argmax(1)]
    lab[p.max(1) < P] = REST
    lab[d['act'][w] < A] = REST
    if M > 1:
        out = lab.copy()
        for i in range(len(lab)):
            v = np.bincount(lab[max(0, i - M + 1):i + 1], minlength=9)
            out[i] = v.argmax()
        lab = out
    return lab


def first(lab, K):
    for i in range(len(lab) - K + 1):
        if lab[i] != REST and (lab[i:i + K] == lab[i]).all():
            return int(lab[i]), i + K - 1
    return None, None


def count(lab, K):
    n, i = 0, 0
    while i <= len(lab) - K:
        if lab[i] != REST and (lab[i:i + K] == lab[i]).all():
            n += 1
            j = i + K
            while j < len(lab) and lab[j] == lab[i]:
                j += 1
            i = j
        else:
            i += 1
    return n


def evaluate(d, K, P, M, A):
    ok = wr = no = 0; lat = []
    for w, g, ton in d['cues']:
        c, j = first(labels(d, w, P, M, A), K)
        if c is None:
            no += 1
        else:
            ok += c == g; wr += c != g
            lat.append(d['t0'] + w[j] * SMS + WMS - ton)
    n = len(d['cues'])
    fc = sum(count(labels(d, w, P, M, A), K) for w in d['rests'])
    mins = sum(len(w) for w in d['rests']) * SMS / 60000
    tok = twr = 0
    for w, g in d['trials']:
        c, _ = first(labels(d, w, P, M, A), K)
        tok += c == g if c is not None else 0; twr += (c is not None and c != g)
    nt = len(d['trials'])
    return dict(ok=100 * ok / n, wr=100 * wr / n, no=100 * no / n, lat=np.median(lat) if lat else np.nan,
                fpm=fc / mins, tok=100 * tok / nt, twr=100 * twr / nt)


def main():
    days = [load(n) for n in ('T00_d1_G', 'T00_d2_G')]
    for d in days:
        print(f"{d['name']}: S7 probe cues {len(d['cues'])}, rest {sum(len(w) for w in d['rests']) * SMS / 60000:.2f} min "
              f"({len(d['rests'])} stretches), task trials {len(d['trials'])}")
    for d in days:
        cue_act = np.concatenate([d['act'][w] for w, _, _ in d['cues']])
        rest_act = np.concatenate([d['act'][w] for w in d['rests']])
        print(f"{d['name']}: activity (x cued gestures) percentiles 10/50/90: gesture cues "
              f"{np.percentile(cue_act, [10, 50, 90]).round(2)}, rest stretches {np.percentile(rest_act, [10, 50, 90]).round(2)}")
    grid = list(itertools.product((3, 4, 5, 6, 8, 10), (0.0, 0.7, 0.9, 0.99), (1, 3),
                                  (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6)))
    res = {key: [evaluate(d, *key) for d in days] for key in grid}
    hdr = '  K     P  M    A | ' + ' | '.join(f"{d['name'][4:6]}: right wrong none  lat ms  rest/min  task r/w" for d in days)
    def row(key):
        return f'{key[0]:3d} {key[1]:5.2f} {key[2]:2d} {key[3]:4.1f} | ' + ' | '.join(
            f"{r['ok']:9.1f} {r['wr']:5.1f} {r['no']:4.1f} {r['lat']:7.0f} {r['fpm']:9.2f} {r['tok']:5.1f}/{r['twr']:4.1f}"
            for r in res[key])
    print('\nbaseline (K 3, P 0, M 1, A 0 = selftest9 decide)\n' + hdr + '\n' + row((3, 0.0, 1, 0.0)))
    print('\nall rules\n' + hdr)
    for key in grid:
        print(row(key))
    print('\ncross-donning selection (tune on one, test on the other): rest <= 1.0 / min, then max right - wrong')
    for a, b in ((0, 1), (1, 0)):
        ok = [k for k in grid if res[k][a]['fpm'] <= 1.0]
        pick = max(ok, key=lambda k: (res[k][a]['ok'] - res[k][a]['wr'], -res[k][a]['lat'])) if ok else \
            min(grid, key=lambda k: res[k][a]['fpm'])
        print(f"tune {days[a]['name']} -> K {pick[0]} P {pick[1]} M {pick[2]} A {pick[3]}" + ('' if ok else ' (none met 1.0/min)'))
        print(hdr + '\n' + row(pick))
    print('\nrules good on both donnings (rest <= 1.0 / min on both), by mean right - wrong, top 10')
    both = [k for k in grid if all(r['fpm'] <= 1.0 for r in res[k])]
    for k in sorted(both, key=lambda k: -np.mean([r['ok'] - r['wr'] for r in res[k]]))[:10]:
        print(row(k))


main()
