# report 35.86 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
"""Latency parts from the two donnings (rtl_task_s7 rule, check_rt_s7 labels): per S7 probe cue, cue_on -> motor
onset (activity first >= 0.5 x median gesture), onset -> command (the board's decision, k 5), and per release
(cue_off) -> stop (k_rest 2). Windows: 200 ms long, 100 ms step; a window's time = its end."""
import numpy as np
K, KR, REST = 5, 2, 8
for name in ('T00_d1_G', 'T00_d2_G'):
    z = np.load(f'/work/results/selftest_T00/rt_s7_labels_{name}.npz')
    lab, act = z['lab'], z['act_ratio']
    run = np.flatnonzero(lab >= 0)
    cmds, stops, last, rn, lat = {}, {}, -1, 0, -1
    for i in run:
        p = lab[i]
        rn = min(rn + 1, max(K, KR)) if p == last else 1
        last = p
        if rn >= (KR if p == REST else K) and p != lat:
            lat = p
            (stops if p == REST else cmds)[i] = p
    cw = np.array(sorted(cmds)); sw = np.array(sorted(stops))
    on_cmd, cue_on, cue_cmd, rel_stop = [], [], [], []
    for s, n, g in zip(z['cue_starts'], z['cue_lens'], z['cue_cls']):
        seg = np.arange(s, s + n)
        hit = cw[(cw >= s) & (cw < s + n)]
        if not len(hit) or cmds[hit[0]] != g:
            continue
        a = np.flatnonzero(act[seg] >= 0.5)
        if not len(a):
            continue
        onset = s + a[0]
        cue_on.append((onset - s) * 100)                 # cue_on is ~ window s (span starts at cue_on)
        on_cmd.append((hit[0] - onset) * 100)
        cue_cmd.append((hit[0] - s) * 100 + 200)
        off = s + n - 5                                   # cue_off (the span runs to cue_off + 0.5 s)
        st = sw[(sw >= off - 5) & (sw < off + 30)]
        if len(st):
            rel_stop.append((st[0] - off) * 100)
    q = lambda v: f'median {np.median(v):.0f} ms (IQR {np.percentile(v, 25):.0f}-{np.percentile(v, 75):.0f}, n {len(v)})'
    print(name)
    print('  cue on -> motor onset (reaction):     ', q(cue_on))
    print('  motor onset -> command on the board:  ', q(on_cmd))
    print('  cue on -> command (end of window):    ', q(cue_cmd))
    print('  cue off -> stop (release, k_rest 2):  ', q(rel_stop))
