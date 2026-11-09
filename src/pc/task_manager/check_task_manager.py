"""Check for fsm.py: scripted sessions with known answers. Usage: python src/pc/task_manager/check_task_manager.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fsm import POWER, LATERAL, TRIPOD, POINTER, OPEN, REST, S, TaskManager  # noqa: E402


def feed(tm, cls, n, accepted=True):
    out = []
    for _ in range(n):
        out += tm.window(cls, accepted)
    return out


def main():
    n = 0
    # 1. full task: voice -> reach -> down -> grip -> up -> open -> home
    tm = TaskManager(['杯子', '水瓶'])
    assert feed(tm, POWER, 5) == [] and tm.state == S.WAIT_VOICE           # sEMG ignored before voice
    assert tm.voice('手機') == [] and tm.voice('杯子') == [('reach', '杯子')]
    assert tm.state == S.REACHING and tm.event('reach_done') == [] and tm.state == S.MANUAL
    assert feed(tm, POINTER, 5) == [('move', 'down')] * 3                   # moves from the k-th window
    assert feed(tm, REST, 1) == [('halt', None)]
    assert feed(tm, POWER, 6) == [('grip', None)] and tm.holding            # once per hold
    assert feed(tm, TRIPOD, 4) == [('move', 'up')] * 2
    assert feed(tm, OPEN, 3) == [('halt', None), ('open', None)] and not tm.holding
    assert feed(tm, LATERAL, 3) == [('home', None)] and tm.state == S.HOMING
    assert tm.event('home_done') == [] and tm.state == S.WAIT_VOICE
    n += 1
    # 2. a rejected window breaks the run; direction change halts first
    tm = TaskManager(['杯子']); tm.voice('杯子'); tm.event('reach_done')
    assert feed(tm, POINTER, 2) + feed(tm, POINTER, 1, False) + feed(tm, POINTER, 2) == []
    assert feed(tm, POINTER, 1) == [('move', 'down')]
    assert feed(tm, TRIPOD, 3) == [('halt', None), ('move', 'up')]
    n += 1
    # 3. stopping while reaching: a held non-Rest gesture, the stop word, estop
    for how in ('gesture', 'voice', 'estop'):
        tm = TaskManager(['杯子']); tm.voice('杯子')
        out = feed(tm, OPEN, 3) if how == 'gesture' else tm.voice('停') if how == 'voice' else tm.estop()
        assert out == [('stop', how)] and tm.state == S.STOPPED, (how, out)
        n += 1
    tm = TaskManager(['杯子']); tm.voice('杯子')
    assert feed(tm, REST, 10) == [] and tm.state == S.REACHING              # Rest never stops
    # 4. from STOPPED only Lateral (home) leaves
    assert tm.estop() == [('stop', 'estop')]
    assert feed(tm, POWER, 5) + feed(tm, POINTER, 5) == [] and tm.state == S.STOPPED
    assert feed(tm, LATERAL, 3) == [('home', None)] and tm.state == S.HOMING
    n += 1
    # 5. open while holding needs k_open windows
    tm = TaskManager(['杯子'], k_open=6); tm.voice('杯子'); tm.event('reach_done')
    feed(tm, POWER, 3); feed(tm, REST, 1)
    assert feed(tm, OPEN, 5) == [] and feed(tm, OPEN, 1) == [('open', None)]
    n += 1
    print(f'task manager: {n} scripted sessions ok')


if __name__ == '__main__':
    main()
