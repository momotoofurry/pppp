"""Tests of the robot side of task labels (report 35.26). Run in the container from the repository root:
  python src/pc/test_task_labels.py
1. task_labels.PickPlace gives the same expected gesture, valid set and validity as the simulation's World
   (src/task_sim.py) for 20,000 random commands (70 % the expected one, else random).
2. The whole chain without hardware, every piece the real code: the C real-time loop (src/c/rt_lda.c through
   ctypes, as check_rt_lda.py) gets recorded EMG of subject 0 (day-1 calibration, one cued pass, then the gestures
   of two pick-and-place cycles from block 1 plus one wrong gesture); every COMMAND it sends goes as the
   TrignoBridge UDP line to kinova_bridge.py (a separate process, --sim, --task-labels); its label datagram goes
   to trigno_bridge.task_forwarder (thread), whose packet is fed back into rt_lda.c; rtl_idle() does the update.
   Checked: one label per command the robot took while idle, labels equal those of an independent PickPlace,
   the invalid command is not executed, every label gives RTL_EV_TASK >= 0 on the MCU.
"""
import ctypes
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import protocol as PR  # noqa: E402
import task_labels as TL  # noqa: E402
import trigno_bridge as TB  # noqa: E402


def test_model():
    import task_sim as T
    rng = np.random.default_rng(0)
    m, w = TL.PickPlace(), T.World()
    for _ in range(20000):
        w.advance()
        want_e = w.intent()
        c = want_e if (want_e != T.REST and rng.random() < 0.7) else int(rng.integers(5))
        want_mask = sum(1 << k for k in range(5) if w.valid(k))
        want_ok = w.valid(c)
        if want_ok:
            w.execute(c)
        e, mask, ok = m.label(c)
        assert (e, mask, ok) == (None if want_e == T.REST else want_e, want_mask, want_ok), (e, mask, ok, want_e)
        assert (m.loc, m.hold, m.obj, m.step, m.cycles) == (w.loc, w.hold, w.obj, w.step, w.cycles)
    print(f'PASS model: 20000 commands, {w.cycles} cycles, same labels and states as task_sim.World')


class FakeLink:
    def __init__(self):
        self.buf, self.lock = bytearray(), threading.Lock()

    def write(self, b):
        with self.lock:
            self.buf += b

    def take(self):
        with self.lock:
            b, self.buf = bytes(self.buf), bytearray()
        return b


def test_chain(ros=None):
    """ros = 'host:port' of src/pc/sim/ros_relay.py: the simulated Gen3 in RViz instead of --sim (arm moves take
    seconds at 20 deg/s, so the user rests ROS_REST_S after every gesture; the robot.csv end events are checked)"""
    import check_features_c as FC
    import check_rt_lda as R
    FC.lib()
    lib = R.build()
    status, cmds = [], []
    dec = PR.Decoder()

    def tx(ptr, n):
        for t, _, p in dec.feed(ctypes.string_at(ptr, n)):
            if t == PR.COMMAND:
                w, _, code, cls, _ = struct.unpack('<IIBBH', p[:12])
                cmds.append((w, code, cls))
            elif t == PR.STATUS:
                status.append(struct.unpack('<B3xi', p[:8]))
    txcb = R.TX(tx)
    cfg = R.Config(txcb, R.NOW(0), 9, 0, 0, 3)
    lib.rtl_init(ctypes.byref(cfg))
    enc = PR.Encoder()

    def send(b):
        lib.rtl_rx(ctypes.c_char_p(b), len(b))

    def label(q, lab):
        for rec, y in zip(q, lab):
            send(R.ctl(enc, PR.STREAM_RESET) + R.ctl(enc, R.LABEL_START, bytes([int(y)])) + R.sample_bytes(enc, rec)
                 + R.ctl(enc, R.LABEL_END))
        send(R.ctl(enc, R.FIT))
        lib.rtl_idle()
        assert lib.rtl_counters().contents.fit_result == 0

    q, lab = R.recordings(0, 'calibration')
    label(q, lab)
    q, lab = R.recordings(0, 'testing_block1')
    first = [int(np.flatnonzero(lab == c)[0]) for c in range(6)]
    label(q[first], lab[first])
    pools = {c: [int(i) for i in np.flatnonzero(lab == c) if i not in first] for c in range(6)}
    order = [0, 2, 3, 4, 1] * 2 + [2]              # two cycles, then Tripod (grip) at home with an empty hand

    tmp = tempfile.mkdtemp()
    p_cmd, p_task = 50656, 50659
    out_csv = os.path.join(tmp, 'robot.csv')
    robot = ['--ros', ros, '--speed', '20'] if ros else ['--sim', '--sim-s', '0.5']
    rest_s, seconds = (ROS_REST_S, 200) if ros else (0.6, 45)
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, 'kinova_bridge.py'), 'run'] + robot +
                            ['--udp', str(p_cmd), '--task-labels', f'127.0.0.1:{p_task}', '--out', out_csv,
                             '--poses', os.path.join(HERE, 'sim', 'poses_sim.json'),
                             '--seconds', str(seconds)], stdout=subprocess.DEVNULL)
    link, stop, got = FakeLink(), threading.Event(), []
    fw = threading.Thread(target=TB.task_forwarder, args=(p_task, link, PR.Encoder(), threading.Lock(), stop, got),
                          daemon=True)
    fw.start()
    time.sleep(1.5)                                  # the bridge process binds its port
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    task_ev, n_cmd = [], 0

    def pump():
        """forward new board commands to the robot side; feed returned labels to the MCU"""
        nonlocal n_cmd
        while n_cmd < len(cmds):
            w, code, cls = cmds[n_cmd]
            n_cmd += 1
            line = f'{time.time() * 1000:.1f},command,{w},0,{PR.GESTURES[cls]},{PR.COMMANDS[code]},,,,,'
            u.sendto(line.encode(), ('127.0.0.1', p_cmd))
        b = link.take()
        if b:
            s0 = len(status)
            send(b)
            lib.rtl_idle()
            task_ev.extend(v for kk, v in status[s0:] if kk == 18)

    try:
        for k, g in enumerate(order):                # real time: 20 frames (10 ms) per packet, 2 s per gesture
            rec = q[pools[g][k % len(pools[g])]]
            send(R.ctl(enc, PR.STREAM_RESET))
            frames = np.ascontiguousarray(rec.T)
            t0 = time.time()
            for i in range(0, len(frames), PR.FRAMES_PER_PACKET):
                send(enc.packet(PR.SAMPLES, frames[i:i + PR.FRAMES_PER_PACKET].tobytes()))
                pump()
                time.sleep(max(0.0, t0 + (i + PR.FRAMES_PER_PACKET) / 2000.0 - time.time()))
            t1 = time.time() + rest_s                # rest: the robot finishes, late labels arrive
            while time.time() < t1:
                pump()
                time.sleep(0.01)
    finally:
        stop.set()
        proc.wait(timeout=seconds + 30)
    # the reference: an independent PickPlace fed with the commands the robot side took while idle (robot.csv)
    rows = [r.split(',') for r in open(out_csv).read().splitlines()[1:]]
    ref, want, j = TL.PickPlace(), [], 0
    while j < len(rows):
        if rows[j][1] == 'received':
            nxt = rows[j + 1][1] if j + 1 < len(rows) else ''
            if nxt not in ('busy', 'ignored_estop'):
                e, mask, ok = ref.label(rows[j][2])
                want.append((rows[j][2], int(rows[j][3]), e, mask, ok))
        j += 1
    assert proc.returncode == 0, f'kinova_bridge.py exited with {proc.returncode}'
    assert want, 'the robot side took no command'
    labels_sent = [(e, m, w) for _, w, e, m, _ in want if e is not None]
    assert got == labels_sent, (got, labels_sent)
    assert len(task_ev) == len(labels_sent), (task_ev, labels_sent)
    applied, stale = sum(v >= 0 for v in task_ev), sum(v == -5 for v in task_ev)
    assert applied + stale == len(task_ev), task_ev
    invalid = [r[2] for r in rows if r[1] == 'invalid']
    started = [r[2] for r in rows if r[1] == 'start']
    busy = [r[2] for r in rows if r[1] == 'busy']
    assert invalid == [n for n, _, _, _, ok in want if not ok], (invalid, want)
    assert started == [n for n, _, _, _, ok in want if ok], (started, want)
    ends = [r for r in rows if r[1] in ('end', 'abort')]
    durations = []
    for r in rows:
        if r[1] == 'start':
            t_start = float(r[0])
        elif r[1] in ('end', 'abort'):
            durations.append((r[2], r[1], round((float(r[0]) - t_start) / 1000, 2)))
    assert len(ends) == len(started) and all(r[1] == 'end' for r in ends), ends
    # a late label: a new command is kept on the MCU, a label for an older window must be refused, the right one taken
    c0 = len(cmds)
    for g in (3, 0, 2):
        send(R.ctl(enc, PR.STREAM_RESET) + R.sample_bytes(enc, q[pools[g][0]]))
        if len(cmds) > c0:
            break
    assert len(cmds) > c0, 'no command for the late-label check'
    w_new = cmds[-1][0]
    late = []
    for w in (w_new - 1, w_new):
        s0 = len(status)
        send(TL.packet(enc, 0, 0b11111, w))
        lib.rtl_idle()
        late += [v for kk, v in status[s0:] if kk == 18]
    assert late[0] == -5 and late[1] >= 0, late
    print(f'PASS late label: window {w_new - 1} refused (-5), window {w_new} applied ({late[1]})')
    print(f'PASS chain: {len(cmds)} commands from the C loop in real time; robot side took {len(want)} while idle '
          f'({", ".join(n for n, *_ in want)}), {len(busy)} arrived while it moved; {len(labels_sent)} labels '
          f'kinova_bridge.py -> UDP -> trigno_bridge forwarder -> rt_lda.c: {applied} applied, {stale} refused as '
          f'late for an older command; {len(started)} executed, {len(invalid)} not valid in the task and not executed')
    print('robot actions (command, event, seconds):', durations)
    return want


ROS_REST_S = 5.0

if __name__ == '__main__':
    if '--ros' in sys.argv:
        test_chain(sys.argv[sys.argv.index('--ros') + 1])
    else:
        test_model()
        test_chain()
