"""Task manager for the proposed Kinova extension (2026-11-09 proposal; report.md section 34). Pure logic, no I/O.

Inputs: voice(word) from Vosk, window(cls, accepted) per sEMG window (PK_PRED; cls 0-5 = Power Lateral Tripod
Pointer Open Rest), executor events ('reach_done', 'reach_failed', 'home_done'), estop().
Outputs: list of (action, arg): ('reach', obj), ('move', 'down'|'up'), ('halt', None), ('grip', None), ('open', None),
('home', None), ('stop', reason).
Gesture rule = freeze-5 decision rule on the PC: a rejected window or another class resets the run; a class acts
when its run reaches k. Pointer/Tripod move on every such window (hold-to-move); Power/Open/Lateral fire once per
hold (latched until the run breaks). Open while holding needs k_open windows (default k; value to be tested).
"""
from enum import Enum

POWER, LATERAL, TRIPOD, POINTER, OPEN, REST = range(6)


class S(Enum):
    WAIT_VOICE = 'wait_voice'
    REACHING = 'reaching'
    MANUAL = 'manual'
    HOMING = 'homing'
    STOPPED = 'stopped'


class TaskManager:
    def __init__(self, objects, k=3, k_open=None, stop_word='停'):
        self.objects, self.k, self.k_open, self.stop_word = set(objects), k, k_open or k, stop_word
        self.state, self.holding, self.moving = S.WAIT_VOICE, False, None
        self._last, self._run, self._latched = -1, 0, -1

    # --- gesture stream -------------------------------------------------------------------------------------
    def _update_run(self, cls, accepted):
        if not accepted:
            self._last, self._run, self._latched = -1, 0, -1
            return -1, 0
        if cls == self._last:
            self._run += 1
        else:
            self._last, self._run, self._latched = cls, 1, -1
        return cls, self._run

    def _halt(self, out):
        if self.moving:
            out.append(('halt', None))
            self.moving = None

    def _to_stopped(self, out, reason):
        self._halt(out)
        out.append(('stop', reason))
        self.state = S.STOPPED

    def window(self, cls, accepted):
        out = []
        c, run = self._update_run(cls, accepted)
        if self.state in (S.REACHING, S.HOMING):
            if c not in (-1, REST) and run >= self.k:
                self._to_stopped(out, 'gesture')
            return out
        if self.state == S.STOPPED:
            if c == LATERAL and run >= self.k and self._latched != c:
                self._latched = c
                out.append(('home', None))
                self.state = S.HOMING
            return out
        if self.state != S.MANUAL:
            return out
        direction = {POINTER: 'down', TRIPOD: 'up'}.get(c)
        if direction and run >= self.k:
            if self.moving != direction:
                self._halt(out)
                self.moving = direction
            out.append(('move', direction))
            return out
        self._halt(out)
        need = self.k_open if (c == OPEN and self.holding) else self.k
        if c in (POWER, OPEN, LATERAL) and run >= need and self._latched != c:
            self._latched = c
            if c == POWER:
                out.append(('grip', None))
                self.holding = True
            elif c == OPEN:
                out.append(('open', None))
                self.holding = False
            else:
                out.append(('home', None))
                self.state = S.HOMING
        return out

    # --- other inputs ---------------------------------------------------------------------------------------
    def voice(self, word):
        out = []
        if word == self.stop_word:
            if self.state in (S.REACHING, S.HOMING):
                self._to_stopped(out, 'voice')
            else:
                self._halt(out)
        elif self.state == S.WAIT_VOICE and word in self.objects:
            out.append(('reach', word))
            self.state = S.REACHING
        return out

    def event(self, name):
        out = []
        if self.state == S.REACHING and name == 'reach_done':
            self.state = S.MANUAL
        elif self.state == S.REACHING and name == 'reach_failed':
            self._to_stopped(out, 'reach_failed')
        elif self.state == S.HOMING and name == 'home_done':
            self.state = S.WAIT_VOICE
        return out

    def estop(self):
        out = []
        self._to_stopped(out, 'estop')
        return out
