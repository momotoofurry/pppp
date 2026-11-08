"""Check src/rejection_summary.py on a hand-made session whose answers are known (no hardware, standard library).

One PRED row every 100 ms. Condition 'A' has: a labelled run (pre), an aborted labelled run (must be ignored), a
second labelled run (post) and a task run. Every cue lasts 2 s; with skip 0.9 s the windows at +0.9 .. +1.9 s count
(11 per cue). Inside the pre cues of an active gesture: 5 windows right + accepted (ratio 0.8), 3 right + rejected
(0.4), 3 'Rest' + rejected (0.4). Rest cues: 8 'Rest' accepted + 3 'Power' accepted. Post cues: all right, accepted.
Outside the cues every window is 'Power' accepted (must not count). Task: 10 windows, 5 rejected.
  python src/check_rejection_summary.py
"""
import csv
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rejection_summary as RS  # noqa: E402

T0 = 1_800_000_000_000.0
G = RS.GESTURES


def main():
    d = tempfile.mkdtemp()
    preds = {}                                    # t -> (top, accepted, ratio)
    task = [dict(event='session', segment='', unix_ms=T0, target='', trial='')]

    def ev(t, seg, e, target='', trial=''):
        task.append(dict(unix_ms=t, segment=seg, event=e, target=target, trial=trial))

    t = T0 + 1000
    for run, kind in (('pre', 'lab'), ('aborted', 'lab'), ('post', 'lab')):
        ev(t, 'labelled', 'seg_start')
        for g in G:
            t += 3000                             # gap
            ev(t, 'labelled', 'cue_on', g)
            for i in range(11):
                tt = t + 900 + 100 * i
                if run == 'pre' and g != 'Rest':
                    preds[tt] = (g, 1, 0.8) if i < 5 else (g, 0, 0.4) if i < 8 else ('Rest', 0, 0.4)
                elif run == 'pre':
                    preds[tt] = ('Rest', 1, 0.8) if i < 8 else ('Power', 1, 0.8)
                elif run == 'aborted':
                    preds[tt] = ('Open', 1, 0.9)
                else:
                    preds[tt] = (g, 1, 0.9)
            t += 2000
            if run == 'aborted' and g == 'Tripod':
                ev(t, 'labelled', 'seg_abort')
                break
        else:
            ev(t + 3000, 'labelled', 'seg_end')
        t += 5000
    ev(t, 'task', 'seg_start')
    ev(t + 150, 'task', 'trial_on', 'grip', '0')            # between two 100 ms slots
    for i in range(10):
        preds[t + 200 + 100 * i] = ('Tripod', i % 2, 0.6 if i % 2 else 0.3)
    ev(t + 1150, 'task', 'trial_end', 'grip', '0')
    ev(t + 2000, 'task', 'seg_end')
    # every other 100 ms slot: 'Power' accepted (outside the scored windows)
    tt = T0
    while tt < t + 3000:
        preds.setdefault(tt, ('Power', 1, 0.95))
        tt += 100

    with open(os.path.join(d, 'X_d1_mcu.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow('unix_ms,kind,window,t_us,gesture,command,accepted,ratio,pushed,event,value'.split(','))
        w.writerow([T0, 'status', '', '', '', '', '', '', '', 'calibrated (0 = ok)', 0])
        for k, (tt, (top, acc, q)) in enumerate(sorted(preds.items())):
            w.writerow([f'{tt:.1f}', 'pred', k, 0, top, '', acc, f'{q:.3f}', 1, '', ''])
    keys = ['unix_ms', 'segment', 'event', 'step', 'trial', 'target', 'command', 'command_gesture', 'window', 'phase',
            'result', 'latency_ms', 'text']
    with open(os.path.join(d, 'X_d1_A_task.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=keys, restval='')
        w.writeheader()
        w.writerows(task)

    out = os.path.join(d, 'rej.csv')
    assert RS.main(['--dir', d, '--name', 'X_d1', '--out', out, '--taus', '0.5,0.6,0.9']) == 0
    rows = {(r['block'], r['group']): r for r in csv.DictReader(open(out))}
    sw = {(r['block'], r['tau']): r for r in csv.DictReader(open(os.path.splitext(out)[0] + '_tau.csv'))}
    checks = [
        (rows['pre', 'Power']['n'], '11'), (rows['pre', 'Power']['rejected_pct'], '54.55'),
        (rows['pre', 'Power']['acc_pct'], '72.73'), (rows['pre', 'Power']['acc_accepted_pct'], '100.0'),
        (rows['pre', 'active']['n'], '55'), (rows['pre', 'active']['rejected_pct'], '54.55'),
        (rows['pre', 'Rest']['rejected_pct'], '0.0'), (rows['pre', 'Rest']['acc_pct'], '72.73'),
        (rows['pre', 'Rest']['rest_cmd_pct'], '27.27'),
        (rows['post', 'active']['n'], '55'), (rows['post', 'active']['rejected_pct'], '0.0'),
        (rows['post', 'active']['acc_pct'], '100.0'),
        (rows['task', 'all']['n'], '10'), (rows['task', 'all']['rejected_pct'], '50.0'),
        (sw['pre', '0.5']['coverage_pct'], '45.45'), (sw['pre', '0.5']['acc_covered_pct'], '100.0'),
        (sw['pre', '0.9']['coverage_pct'], '0.0'), (sw['post', '0.9']['coverage_pct'], '100.0'),
    ]
    bad = [(i, got, want) for i, (got, want) in enumerate(checks) if got != want]
    for i, got, want in bad:
        print(f'check {i}: got {got}, want {want}')
    print(f'{len(checks) - len(bad)}/{len(checks)} checks passed')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
