"""Endpoints of one or more TaskScreen task.csv files (PROTOCOL.md sections 2, 5, 6), standard library only.

Per file (subject x day x condition), from the last completed run of each segment (seg_end; aborted runs left out):
  task:       trials, success rate (primary endpoint), median time cue -> correct command, wrong commands,
              timeouts, commands during the rests between trials ('rest' false commands)
  noncontrol: commands per minute over the items (safety endpoint), per item
  labelled:   cues per gesture (the labels for offline accuracy)
  retry:      with TaskScreen --retry 1: trials whose first command was wrong, and how many of them got the target
              later within the time limit (second-attempt success, secondary)
  tlx:        raw NASA-TLX: the 6 scales (0-100) and their mean (performance: 0 = perfect, 100 = failure)
The trial results are also recomputed from the logged commands (first command time-stamped within the time limit
of the cue) and compared with TaskScreen's own trial_end rows; any difference is printed (e.g. a command that
reached the PC after the 150 ms grace) and counted in 'recomputed_differ'.

  python src/task_summary.py results/study/S01_d2_A_task.csv [...] [--out summary.csv]
"""
import argparse
import csv
import re
import statistics
import sys
from collections import Counter, defaultdict


def runs(rows):
    """segment runs: list of (segment, rows of that run, completed)"""
    out, cur = [], None
    for r in rows:
        if r['event'] == 'seg_start':
            cur = (r['segment'], [])
        if cur is not None:
            cur[1].append(r)
            if r['event'] in ('seg_end', 'seg_abort'):
                out.append((cur[0], cur[1], r['event'] == 'seg_end'))
                cur = None
    return out


def task_stats(rr, timeout_ms):
    trials, ends, cmds = {}, {}, []
    for r in rr:
        if r['event'] == 'trial_on':
            trials[int(r['trial'])] = (float(r['unix_ms']), r['target'])
        elif r['event'] == 'trial_end':
            ends[int(r['trial'])] = r
        elif r['event'] == 'command':
            cmds.append((float(r['unix_ms']), r['command'], r['phase']))
    cmds.sort()
    res, lat, differ = Counter(), [], 0
    retry = Counter(r['result'] for r in rr if r['event'] == 'retry_end')
    for t, (t0, target) in sorted(trials.items()):
        first = next((c for c in cmds if t0 <= c[0] <= t0 + timeout_ms), None)
        mine = 'timeout' if first is None else 'success' if first[1] == target else 'wrong'
        logged = ends[t]['result'] if t in ends else 'missing'
        if mine != logged:
            differ += 1
            print(f'  trial {t}: target {target}, recomputed {mine} ({first}), TaskScreen {logged}', file=sys.stderr)
        res[logged] += 1
        if logged == 'success':
            lat.append(float(ends[t]['latency_ms']))
    n = len(trials)
    targets = [trials[t][1] for t in sorted(trials)]
    return dict(trials=n, success=res['success'], success_rate=round(100 * res['success'] / n, 2) if n else None,
                wrong=res['wrong'], timeout=res['timeout'], aborted=res['aborted'],
                median_latency_ms=round(statistics.median(lat), 1) if lat else None,
                rest_commands=sum(1 for c in cmds if c[2] == 'rest'),
                retry_trials=sum(retry.values()), retry_success2=retry['success2'],
                recomputed_differ=differ, target_counts=' '.join(f'{k}:{v}' for k, v in sorted(Counter(targets).items())),
                repeats=sum(1 for a, b in zip(targets, targets[1:]) if a == b))


def noncontrol_stats(rr):
    on, minutes, per = {}, 0.0, defaultdict(int)
    item_of_step = {}
    for r in rr:
        if r['event'] == 'item_on':
            on[r['step']] = float(r['unix_ms'])
            item_of_step[r['step']] = r['target']
        elif r['event'] == 'item_off' and r['step'] in on:
            minutes += (float(r['unix_ms']) - on[r['step']]) / 60000
        elif r['event'] == 'command' and r['phase'] == 'item':
            per[item_of_step.get(r['step'], '?')] += 1
    n = sum(per.values())
    return dict(nc_minutes=round(minutes, 3), nc_commands=n, nc_per_min=round(n / minutes, 3) if minutes else None,
                nc_per_item=' '.join(f'{k}:{v}' for k, v in sorted(per.items())))


def summarise(path):
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    m = re.search(r'timeout_s (\S+)', rows[0]['text'])
    timeout_ms = 1000 * float(m.group(1))
    out = dict(file=path.replace('\\', '/').split('/')[-1])
    m = re.search(r'subject (\S+) day (\S+)', rows[0]['text'])
    out['subject'], out['day'] = m.group(1), m.group(2)
    done = {}
    lab = []
    for seg, rr, ok in runs(rows):
        if not ok:
            continue
        if seg == 'labelled':
            lab.append(Counter(r['target'] for r in rr if r['event'] == 'cue_on'))
        else:
            done[seg] = rr                                  # the last completed run
    if 'task' in done:
        out.update(task_stats(done['task'], timeout_ms))
    if 'noncontrol' in done:
        out.update(noncontrol_stats(done['noncontrol']))
    if 'tlx' in done:
        tlx = {r['target']: int(r['result']) for r in done['tlx'] if r['event'] == 'tlx'}
        out.update({f'tlx_{k}': v for k, v in tlx.items()})
        if len(tlx) == 6:
            out['tlx_raw'] = round(sum(tlx.values()) / 6, 2)
    out['labelled_blocks'] = len(lab)
    out['labelled_cues'] = ' | '.join(' '.join(f'{k}:{v}' for k, v in sorted(c.items())) for c in lab)
    out['aborted_runs'] = sum(1 for _s, _r, ok in runs(rows) if not ok)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--out')
    args = ap.parse_args()
    res = [summarise(p) for p in args.files]
    keys = list(dict.fromkeys(k for r in res for k in r))
    w = csv.DictWriter(open(args.out, 'w', newline='') if args.out else sys.stdout, keys)
    w.writeheader()
    w.writerows(res)


if __name__ == '__main__':
    main()
