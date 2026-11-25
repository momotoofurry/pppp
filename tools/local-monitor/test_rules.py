"""rules.py on synthetic rows: every rule fires on its pattern and stays quiet on normal data (report 35.108)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules as RU  # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(('ok   ' if cond else 'FAIL ') + name)
    ok &= bool(cond)


def steps(n, t0=1000.0, dt=0.1, te=0.001, state='mode1'):
    return [dict(t=f'{i * 0.1:.1f}', command='up', state=state, track_err=str(te), wall=str(t0 + i * dt)) for i in range(n)]


def run(rows):
    d = RU.Detector()
    out = []
    for kind, r in rows:
        out += d.feed(kind, r)
    return out


normal = [('assist', r) for r in steps(600)]
check('normal 60 s of control: no alert', run(normal) == [])
s = steps(20)
s[10]['wall'] = str(float(s[9]['wall']) + 0.5)
for r in s[11:]:
    r['wall'] = str(float(r['wall']) + 0.4)
al = run([('assist', r) for r in s])
check('0.5 s gap: one loop_stall warn', [x['rule'] for x in al] == ['loop_stall'] and al[0]['severity'] == 'warn')
s = steps(20)
for r in s[10:]:
    r['wall'] = str(float(r['wall']) + 1.5)
check('1.6 s gap: loop_stall high', run([('assist', r) for r in s])[0]['severity'] == 'high')
s = steps(30)
for i, r in enumerate(s):                 # 35.109: wall stepped +0.8 s (time sync) while the monotonic clock is steady
    r['mono'] = str(500 + 0.1 * i)
    if i >= 15:
        r['wall'] = str(float(r['wall']) + 0.8)
check('wall-clock step with a steady mono column: no stall (35.109)', run([('assist', r) for r in s]) == [])
for r in s[20:]:
    r['mono'] = str(float(r['mono']) + 0.6)
al = run([('assist', r) for r in s])
check('a real 0.7 s stop on the mono column: one stall, marked monotonic',
      [x['rule'] for x in al] == ['loop_stall'] and al[0]['data']['clock'] == 'monotonic')
s = steps(30)
s[10]['wall'] = str(float(s[9]['wall']) + 0.85)
s[11]['wall'] = str(float(s[10]['wall']) + 1.02)
for i, r in enumerate(s[12:], 12):
    r['wall'] = str(float(s[11]['wall']) + 0.1 * (i - 11))
check('one pause seen as two slow steps: one alert (35.108 replay)', len(run([('assist', r) for r in s])) == 1)
s = steps(30)
rs = float(s[9]['wall']) + 3.3
for r in s[10:]:
    r['wall'] = str(float(r['wall']) + 3.3)
check('3.3 s gap with a reset_done inside: planned, no alert',
      run([('assist', r) for r in s[:10]] + [('task', dict(unix_ms=str(rs * 1000), event='reset_done', a='2'))]
          + [('assist', r) for r in s[10:]]) == [])
check('3.3 s gap without a reset: high', run([('assist', r) for r in s])[0]['severity'] == 'high')
s = steps(30)
for r in s[10:14]:
    r['track_err'] = '0.06'
check('4 steps over 4 cm: no tracking alert', run([('assist', r) for r in s]) == [])
for r in s[10:20]:
    r['track_err'] = '0.06'
al = run([('assist', r) for r in s])
check('10 steps over 4 cm: exactly one tracking_hold', [x['rule'] for x in al] == ['tracking_hold'])
check('deadman event', run([('board', dict(recv_unix_ms='1', command='deadman', applied='rest'))])[0]['rule'] == 'deadman_stop')
check('packets lost status (assist_ros)', run([('board', dict(recv_unix_ms='1', command='status', gesture='packets lost'))])[0]['rule'] == 'packets_lost')
mcu = lambda ev, v, t: ('mcu', dict(unix_ms=str(t), kind='status', event=ev, value=str(v)))  # noqa: E731
check('UART errors 1 at start then unchanged: quiet (35.96)', run([mcu('UART errors', 1, 1), mcu('UART errors', 1, 2)]) == [])
check('UART errors rising: warn', [x['rule'] for x in run([mcu('UART errors', 1, 1), mcu('UART errors', 3, 2)])] == ['uart_errors_rising'])
check('packets lost baseline at start then unchanged: quiet', run([mcu('packets lost', 29575, 1), mcu('packets lost', 29575, 2)]) == [])
check('bytes dropped rising: high', run([mcu('UART bytes dropped', 0, 1), mcu('UART bytes dropped', 5, 2)])[0]['severity'] == 'high')
task = lambda ev, a='', b='', d='': ('task', dict(unix_ms='1000', event=ev, a=a, b=b, detail=d))  # noqa: E731
check('air grasp', run([task('grip_empty', '3', '', '0.800')])[0]['rule'] == 'air_grasp')
check('reset refused', run([task('reset_refused', '4', '', 'mode2')])[0]['rule'] == 'reset_refused')
check('put down on a shelf: quiet', run([task('putdown', '3', '4')]) == [])
check('put down off every shelf: warn', run([task('putdown', '3', '')])[0]['rule'] == 'putdown_off_shelf')
check('2 locks: quiet', run([task('lock_obj', '1'), task('lock_shelf', '3')]) == [])
check('3 locks: repeated_locks once',
      [x['rule'] for x in run([task('lock_obj', '1'), task('lock_obj', '2'), task('lock_shelf', '3'), task('lock_shelf', '4')])] == ['repeated_locks'])
check('locks reset at a put-down', run([task('lock_obj', '1'), task('lock_obj', '2'), task('putdown', '2', '4'), task('lock_obj', '1')]) == [])
d = RU.Detector()
d.feed('assist', steps(1)[0])
check('quiet: no alert within 3 s, one after', d.quiet(1001.0) == [] and len(d.quiet(1004.5)) == 1 and d.quiet(1009) == [])
print('ALL OK' if ok else 'SOME FAILED')
sys.exit(0 if ok else 1)
