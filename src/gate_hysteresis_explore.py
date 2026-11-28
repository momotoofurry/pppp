#!/usr/bin/env python3
"""Exploratory Schmitt-trigger (hysteresis) activity gate sweep on 11/23 S7 recordings (T00_d1_G, T00_d2_G).

Baseline (rtl_task_s7f): single threshold k_on = k_off = 0.50 (mode 2: median activity of active non-Rest cued windows).
Hysteresis (inspired by NeuroCommitSSM dwell/hysteresis):
  - When currently gated (Rest), require activity >= k_on * thr to leave Rest.
  - When currently active (non-Rest), stay active until activity < k_off * thr.
  (k_on >= k_off). Evaluated with the exact decision.c rule (k=5, k_rest=2) on probe cues and rest stretches.

Usage (container): python src/gate_hysteresis_explore.py --dir /sd/T00 --days T00_d1_G T00_d2_G
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_rt_s7 as S7  # noqa: E402
import selftest_analysis as SA  # noqa: E402
import selftest9_analysis as S9  # noqa: E402

CL = S9.SETS['S7']
REST = S9.REST
K, K_REST = 5, 2
PAIRS = [
    (0.50, 0.50),   # baseline rtl_task_s7f
    (0.55, 0.40),
    (0.55, 0.45),
    (0.60, 0.40),
    (0.60, 0.45),
    (0.60, 0.50),
    (0.65, 0.40),
    (0.65, 0.45),
    (0.70, 0.45),
]


def apply_hysteresis_gate(act, thr, k_on, k_off):
    """Returns boolean array gated[i]: True -> forced Rest."""
    gated = np.empty(len(act), dtype=bool)
    hi = np.float32(k_on) * thr
    lo = np.float32(k_off) * thr
    is_gated = True
    for i, a in enumerate(act):
        if is_gated:
            if a >= hi:
                is_gated = False
        else:
            if a < lo:
                is_gated = True
        gated[i] = is_gated
    return gated


def eval_day(root, name):
    day = S9.load_day(root, name, 4.0, frozenset(CL))
    folder = S9.day_folder(root, name)
    X, t0, _ = SA.load_emg(os.path.join(folder, f'{name}_emg.csv'))
    q = np.clip(np.round(X.astype(np.float64) / 2.5e-7), -32768, 32767).astype(np.int16)
    Fq = SA.features(q.astype(np.float32) * np.float32(2.5e-7))
    nw = len(Fq)
    mdl = S9.Model(Fq, day['cal_rows'], day['cal_lab'], CL)
    act = np.zeros(nw, np.float32)
    for ch in range(8):
        act = act + Fq[:, 4 * 8 + ch].astype(np.float32)
    gl = np.isin(day['cal_lab'], CL) & (day['cal_lab'] != REST)
    v = np.sort(act[day['cal_rows'][gl]])
    m = len(v)
    thr = v[m // 2] if m & 1 else np.float32(0.5) * (v[m // 2 - 1] + v[m // 2])
    raw_top = mdl.predict(Fq)
    fit_after = int(day['cal_rows'].max())

    S7.A = type('A', (), {'dir': root})()
    cues, rests, _ = S7.spans(name, t0, nw)
    probe_cues = [c for c in cues if c[0][0] > fit_after]
    rest_w = set(np.concatenate([r for r in rests if r[0] > fit_after]).tolist())
    rest_min = len(rest_w) * 0.1 / 60.0

    rows = []
    for k_on, k_off in PAIRS:
        gated = apply_hysteresis_gate(act, thr, k_on, k_off)
        top = raw_top.copy()
        top[gated] = REST
        # Decision rule on run-mode windows (after fit_after)
        run_top = top[fit_after + 1:]
        S7.FAST = (0, 0)
        cmds_rel, _ = S7.ref_decision(run_top)
        cmds = [(fit_after + 1 + wi, cls) for wi, cls in cmds_rel]

        right = wrong = none = 0
        lats = []
        for w_arr, g, t_on in probe_cues:
            ws = set(w_arr.tolist())
            hit = [(wi, cls) for wi, cls in cmds if wi in ws]
            if not hit:
                none += 1
            elif hit[0][1] == g:
                right += 1
                t_cmd = t0 + hit[0][0] * 100.0 + 200.0
                lats.append(t_cmd - t_on)
            else:
                wrong += 1
        rest_cmds = sum(1 for wi, cls in cmds if wi in rest_w)
        n_c = len(probe_cues)
        rows.append((k_on, k_off, 100.0 * right / n_c, 100.0 * wrong / n_c, 100.0 * none / n_c,
                     float(np.median(lats)) if lats else np.nan, rest_cmds, rest_cmds / rest_min))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default='/sd/T00')
    ap.add_argument('--days', nargs='+', default=['T00_d1_G', 'T00_d2_G'])
    ap.add_argument('--out', default='results/assist/gate_hysteresis_1123.txt')
    a = ap.parse_args()
    lines = ['Exploratory Schmitt-trigger activity gate sweep on 11/23 S7 recordings (k=5, k_rest=2)']
    all_res = {}
    for d in a.days:
        all_res[d] = eval_day(a.dir, d)
        lines.append(f'\n== {d} ==')
        lines.append(f'{"k_on":>5} {"k_off":>5} | {"right%":>6} {"wrong%":>6} {"none%":>6} | {"med_ms":>6} | {"rest_n":>6} {"rest/m":>6}')
        lines.append('-' * 62)
        for r in all_res[d]:
            lines.append(f'{r[0]:5.2f} {r[1]:5.2f} | {r[2]:6.1f} {r[3]:6.1f} {r[4]:6.1f} | {r[5]:6.0f} | {r[6]:6d} {r[7]:6.2f}')
    lines.append('\n== Mean over days ==')
    lines.append(f'{"k_on":>5} {"k_off":>5} | {"right%":>6} {"none%":>6} | {"med_ms":>6} | {"rest/m":>6}')
    lines.append('-' * 48)
    for i in range(len(PAIRS)):
        k_on, k_off = PAIRS[i]
        mr = np.mean([all_res[d][i][2] for d in a.days])
        mn = np.mean([all_res[d][i][4] for d in a.days])
        ml = np.mean([all_res[d][i][5] for d in a.days])
        mrm = np.mean([all_res[d][i][7] for d in a.days])
        lines.append(f'{k_on:5.2f} {k_off:5.2f} | {mr:6.1f} {mn:6.1f} | {ml:6.0f} | {mrm:6.2f}')
    txt = '\n'.join(lines) + '\n'
    print(txt)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(txt)


if __name__ == '__main__':
    main()
