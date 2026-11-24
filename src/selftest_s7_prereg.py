"""S7 confirmation recordings (report 35.81, DRAFT rules until the user confirms them before the first S7 recording):
the board's REAL-TIME commands as TaskScreen logged them (firmware rtl_task_s7b with TrignoBridge --preset s7, panel
set S7, files <subj>_d<day>_S_*). No offline re-decoding: what the arm would have received.

Per donning (from <name>_task.csv):
  M1 task success     trial_end 'success' / all task trials (first command within the timeout is the target)
  M2 rest commands    commands in the task rest periods (phase 'rest' of the task segments) per minute of rest
  M3 probe commands   per labelled cue of an S7 non-Rest gesture: the first command during the cue (phase 'cue'):
                      right / wrong / none
  M4 latency          cue -> command of the successful task trials (median, quartiles)
  M5 labelled rest    commands while resting in the labelled segments (phase 'rest', and Rest cues) per minute
Decision (draft, see report 35.81): over all donnings,
  P1  mean M1 >= 80 %      and   P2  mean M2 <= 2.0 per minute   ->  GO to the Kinova closed loop with S7
  otherwise                                                     ->  revise (placement / gestures / gate) first
  reported only: M3, M4, M5; per-donning values; the soft-label and accumulation numbers of
  selftest9_analysis.py --sets S7 (rules 2 and 3 as reports).

usage: python src/selftest_s7_prereg.py --dir D:/selftest_data/T00 --days T00_d1_S [T00_d2_S ...] [--out <folder>]
  (also runs on 9-gesture days for testing; then the numbers are the S9 board's and not a decision)
"""
import argparse
import os

import numpy as np
import pandas as pd

S7 = {'WristExt', 'WristFlex', 'RadialDev', 'UlnarDev', 'HandOpen', 'Fist'}
P1_MIN, P2_MAX = 80.0, 2.0


def folder(d, name):
    sub = os.path.join(d, name)
    return sub if os.path.isfile(os.path.join(sub, f'{name}_task.csv')) else d


def day(d, name):
    f = folder(d, name)
    t = pd.read_csv(os.path.join(f, f'{name}_task.csv'), dtype=str, keep_default_na=False)
    t['t'] = t.unix_ms.astype(float)
    ops = pd.read_csv(os.path.join(f, f'{name}_ops.csv'), dtype=str, keep_default_na=False)
    s7fw = any(c.strip() == 'preset s7' for c in ops.command)
    task = t[t.segment == 'task']
    ends = task[task.event == 'trial_end']
    m1 = 100 * (ends.result == 'success').mean() if len(ends) else float('nan')
    rest_ms, on = 0.0, None
    for r in task.itertuples():
        if r.event == 'rest_on':
            on = r.t
        elif r.event == 'rest_off' and on is not None:
            rest_ms += r.t - on
            on = None
    rc = ((task.event == 'command') & (task.phase == 'rest')).sum()
    m2 = rc / (rest_ms / 60000) if rest_ms else float('nan')
    lab = t[t.segment == 'labelled']
    ok = wr = no = 0
    cue, got = None, False
    lrest_ms, lon, lrc = 0.0, None, 0
    for r in lab.itertuples():
        if r.event == 'cue_on':
            cue, got = r.target, False
            if lon is not None:
                lrest_ms += r.t - lon
                lon = None
            if r.target == 'Rest':
                lon = r.t
        elif r.event == 'cue_off':
            if cue in S7 and not got:
                no += 1
            if cue != 'Rest':
                lon = r.t
            cue = None
        elif r.event == 'seg_end':
            if lon is not None:
                lrest_ms += r.t - lon
                lon = None
        elif r.event == 'command':
            if cue in S7 and not got and r.phase == 'cue':
                got = True
                ok += r.command_gesture == cue
                wr += r.command_gesture != cue
            elif lon is not None:
                lrc += 1
    n3 = ok + wr + no
    lat = ends[ends.result == 'success'].latency_ms.astype(float).to_numpy()
    return dict(name=name, s7fw=s7fw, trials=len(ends), m1=m1, rest_min=rest_ms / 60000, rest_cmd=int(rc), m2=m2,
                cues=n3, ok=ok, wr=wr, no=no, lat=lat, lrest_min=lrest_ms / 60000, lrest_cmd=lrc,
                m5=lrc / (lrest_ms / 60000) if lrest_ms else float('nan'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--days', nargs='+', required=True)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    lines = []

    def p(s=''):
        print(s, flush=True)
        lines.append(s)

    ds = [day(a.dir, n) for n in a.days]
    p('S7 confirmation (report 35.81, draft rules): the board\'s real-time commands as TaskScreen logged them')
    for d in ds:
        q = (f'{np.median(d["lat"]):.0f} ms ({np.percentile(d["lat"], 25):.0f}-{np.percentile(d["lat"], 75):.0f})'
             if len(d['lat']) else '-')
        p(f"\n== {d['name']}  ({'S7 firmware settings (preset s7)' if d['s7fw'] else 'NOT an S7 recording: no preset s7 in ops'})")
        p(f"M1 task success        {d['m1']:5.1f} %  ({d['trials']} trials)")
        p(f"M2 task-rest commands  {d['m2']:5.2f} / min  ({d['rest_cmd']} in {d['rest_min']:.2f} min)")
        p(f"M3 probe cues (S7)     right {d['ok']}, wrong {d['wr']}, none {d['no']} of {d['cues']}"
          + (f"  ({100 * d['ok'] / d['cues']:.1f} % right)" if d['cues'] else ''))
        p(f"M4 latency (success)   {q}")
        p(f"M5 labelled-rest cmds  {d['m5']:5.2f} / min  ({d['lrest_cmd']} in {d['lrest_min']:.2f} min)")
    m1 = float(np.mean([d['m1'] for d in ds]))
    m2 = float(np.mean([d['m2'] for d in ds]))
    allS7 = all(d['s7fw'] for d in ds)
    ok1, ok2 = m1 >= P1_MIN, m2 <= P2_MAX
    p(f'\nmean over {len(ds)} donning(s): M1 {m1:.1f} % (P1 needs >= {P1_MIN:g}), M2 {m2:.2f} / min (P2 needs <= {P2_MAX:g})')
    verdict = 'GO to the Kinova closed loop with S7' if ok1 and ok2 else 'revise placement / gestures / gate first'
    if allS7:
        p(f'DECISION (rules of 35.81): P1 {"pass" if ok1 else "fail"}, P2 {"pass" if ok2 else "fail"} -> {verdict}')
    else:
        p(f'(not a decision: not all days are S7 recordings) P1 {"pass" if ok1 else "fail"}, P2 {"pass" if ok2 else "fail"}')
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, 's7_prereg_' + '_'.join(a.days) + '.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
