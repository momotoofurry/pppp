"""35.101: kinova_trials.py logic without ROS: a scripted fake assist_ros answers the resets and plays task events.
python3 src/pc/sim/kinova_trials_test.py"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kinova_trials as KT  # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(('ok   ' if cond else 'FAIL ') + name)
    ok &= bool(cond)


class Fake:
    """reset answers (a list per trial, one per reset message) then the events after a reset_done"""

    def __init__(self, answers, after):
        self.answers, self.after, self.q, self.sent = answers, after, [], []

    def send(self, line):
        self.sent.append(line)
        p = line.split(',')
        ans = self.answers.pop(0)
        now = time.time() * 1000
        if ans == 'done':
            self.q.append(dict(ms=now, ev='reset_done', a=p[1], b='', detail=''))
            for ev, a, b in self.after:
                self.q.append(dict(ms=now + 10, ev=ev, a=str(a), b='' if b is None else str(b), detail='0.7 0.2 0.3'))
        else:
            self.q.append(dict(ms=now, ev='reset_refused', a=p[1], b='', detail=ans))

    def read(self):
        out, self.q = self.q, []
        return out


names = KT.SC.names(*KT.SC.load('crowded'))


def run(answers, after, obj=3, shelf=4, limit=90.0, lines=(), auto=False, helper='y'):
    f = Fake(list(answers), after)
    L = list(lines)
    s = KT.Session(f.send, f, limit=limit, auto=auto,
                   ask=lambda p: 'drop' if '原因' in p else helper if 'y／n' in p else '',
                   line=lambda: L.pop(0) if L else None, say=lambda *a: None)
    return s.trial(7, 0, obj, shelf, names), f


r, f = run(['done'], [('lock_obj', 2, None), ('lock_obj', 3, None), ('grasp', 3, None), ('lock_shelf', 5, None),
                      ('lock_shelf', 4, None), ('putdown', 3, 4)])
check('success: target object on the target shelf', r['outcome'] == 'success')
check('wrong locks counted (object 1, shelf 1)', r['wrong_lock_obj'] == 1 and r['wrong_lock_shelf'] == 1)
check('reset message sent with the trial id', f.sent == ['reset,7'])
r, _ = run(['done'], [('grasp', 3, None), ('putdown', 3, 5)])
check('wrong shelf', r['outcome'] == 'wrong_shelf' and r['put_shelf'] == 5)
r, _ = run(['done'], [('grasp', 2, None), ('putdown', 2, 4)])
check('wrong object (and a wrong grasp counted)', r['outcome'] == 'wrong_object' and r['wrong_grasp'] == 1)
r, _ = run(['done'], [('grasp', 3, None), ('putdown', 3, None)])
check('put down but not standing on a shelf', r['outcome'] == 'not_on_shelf')
r, _ = run(['done'], [], limit=0.3)
check('timeout', r['outcome'] == 'timeout')
r, f = run(['mode2', 'done'], [('putdown', 3, 4)])
check('refused in mode 2, retried after the helper: then success', r['outcome'] == 'success' and f.sent == ['reset,7', 'reset,7'])
r, f = run(['holding', 'done'], [('putdown', 3, 4)])
check('refused while holding: forced after the helper', f.sent == ['reset,7', 'reset,7,force'] and r['outcome'] == 'success')
r, _ = run(['done'], [], lines=[None, 'x'])
check('helper abort with a reason', r['outcome'] == 'abort:drop')
r, _ = run(['done'], [('grasp', 3, None), ('putdown', 3, 4)], helper='n')
check('software success but the helper says no: failed_physical', r['outcome'] == 'failed_physical' and r['helper_ok'] == 'n')
r, _ = run(['done'], [('grasp', 3, None), ('putdown', 3, 4)], helper='y')
check('helper confirms: success, recorded', r['outcome'] == 'success' and r['helper_ok'] == 'y')
r, _ = run(['done'], [('grasp', 3, None), ('putdown', 3, 4)], auto=True)
check('auto (rehearsal): no helper question', r['outcome'] == 'success' and r['helper_ok'] == '')

rows = KT.make_list('crowded', 24, 2, 101)
sc = [x for x in rows if not x[1]]
check('list: 2 practice + 24 scored', len(rows) == 26 and len(sc) == 24 and all(x[1] for x in rows[:2]))
check('list: every object 4 times', sorted({o: sum(1 for x in sc if x[2] == o) for o in range(6)}.values()) == [4] * 6)
check('list: put-down shelves only the empty ones, 8 each', {s: sum(1 for x in sc if x[3] == s) for s in (3, 4, 5)} == {3: 8, 4: 8, 5: 8})
check('list: same seed, same list', KT.make_list('crowded', 24, 2, 101) == rows)

# the events file reader: only new lines, a restart of assist_ros (shorter file) starts over
d = tempfile.mkdtemp()
p = os.path.join(d, 'ev.csv')
open(p, 'w').write('unix_ms,step,event,a,b,detail\n1,0,ready,6,6,crowded\n')
E = KT.Events(p)
check('events: lines before the logger started are skipped', E.read() == [])
open(p, 'a').write('2,5,grasp,3,,\n3,9,putdown,3,4,0.7 0.2 0.3\n')
got = E.read()
check('events: new lines read', [g['ev'] for g in got] == ['grasp', 'putdown'] and got[1]['b'] == '4')
open(p, 'w').write('unix_ms,step,event,a,b,detail\n4,0,ready,6,6,crowded\n')
check('events: restarted file read from the start', [g['ev'] for g in E.read()] == ['ready'])
open(p, 'a').write('5,1,grasp,1')
check('events: a half-written line waits', E.read() == [])
print('ALL OK' if ok else 'SOME FAILED')
sys.exit(0 if ok else 1)
