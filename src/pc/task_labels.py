"""Task labels for the LDA main line (report 35.26): the robot side's half of RTL_TASK_LABEL (src/c/rt_lda.h).
Standard library only.

The pick-and-place task of the simulation (src/task_sim.py, World): a cycle is  pose_A -> grip -> pose_B -> release
-> home; the object starts at A. Robot state = location (home / A / B), holding, where the object is. A command is
VALID only if it can do something now: pose X when not at X, home when not at home, grip when the gripper is empty and
the object is here, release when holding. The EXPECTED gesture is the one that brings the state towards the target
of the current step (same rule as the simulated user, without the user's deviations).
For every command the board sends while the robot is idle, the robot side calls label(command) BEFORE acting on it:
  -> (expected class 0-4, valid mask, command valid?)  expected None when the task has nothing to do (cycles done).
The command is executed only if it is valid (an invalid one is labelled, not executed), as in the simulation.
Classes: 0 Power = pose_A, 1 Lateral = home, 2 Tripod = grip, 3 Pointer = pose_B, 4 Open = release, 5 Rest.

  packet(enc, expected, mask)  the PK_CONTROL packet RTL_TASK_LABEL (sub-command 12, two bytes)
  datagram / parse_datagram    "task,<expected>,<mask>,<window>" between kinova_bridge.py and the serial bridge
                               (UDP); window = the window number of the board's COMMAND packet, so the MCU can
                               refuse a label that is late for an older command
"""
POWER, LATERAL, TRIPOD, POINTER, OPEN, REST = range(6)
CLASS = {'pose_A': POWER, 'home': LATERAL, 'grip': TRIPOD, 'pose_B': POINTER, 'release': OPEN}
COMMAND = {v: k for k, v in CLASS.items()}
GOTO = {'A': POWER, 'B': POINTER, 'home': LATERAL}
TARGET = [('A', 0), ('A', 1), ('B', 1), ('B', 0), ('home', 0)]
TASK_LABEL = 12


class PickPlace:
    def __init__(self, cycles=None):
        self.loc, self.hold, self.obj, self.step, self.cycles = 'home', 0, 'A', 0, 0
        self.max_cycles = cycles

    def valid(self, c):
        return {POWER: self.loc != 'A', POINTER: self.loc != 'B', LATERAL: self.loc != 'home',
                TRIPOD: (not self.hold) and self.loc == self.obj, OPEN: bool(self.hold)}.get(c, False)

    def execute(self, c):
        if c in (POWER, POINTER, LATERAL):
            self.loc = {POWER: 'A', POINTER: 'B', LATERAL: 'home'}[c]
        elif c == TRIPOD:
            self.hold, self.obj = 1, 'gripper'
        else:
            self.hold, self.obj = 0, self.loc

    def intent(self):
        tl, th = TARGET[self.step]
        if self.step == 3 and not self.hold and self.obj != 'B':
            return TRIPOD if self.loc == self.obj else GOTO[self.obj]
        if th and not self.hold:
            return TRIPOD if self.loc == self.obj else GOTO[self.obj]
        if not th and self.hold:
            return OPEN if (self.loc == tl or self.step != 3) else GOTO[tl]
        return GOTO[tl] if self.loc != tl else REST

    def advance(self):
        while True:
            tl, th = TARGET[self.step]
            if (self.loc, self.hold) != (tl, th) or (self.step == 3 and self.obj != 'B'):
                return
            self.step += 1
            if self.step == len(TARGET):
                self.step, self.cycles, self.obj = 0, self.cycles + 1, 'A'

    def done(self):
        return self.max_cycles is not None and self.cycles >= self.max_cycles

    def label(self, command):
        """label for a command the board sent while the robot is idle; executes it in the model if valid"""
        c = CLASS[command] if isinstance(command, str) else int(command)
        self.advance()
        expected = None if self.done() else self.intent()
        if expected == REST:
            expected = None
        mask = sum(1 << k for k in range(5) if self.valid(k))
        ok = self.valid(c)
        if ok:
            self.execute(c)
        return expected, mask, ok


def payload(expected, mask, window=None):
    b = bytes([TASK_LABEL, expected & 0xFF, mask & 0xFF])
    return b if window is None else b + int(window).to_bytes(4, 'little')


def packet(enc, expected, mask, window=None):
    import protocol as PR
    return enc.packet(PR.CONTROL, payload(expected, mask, window))


def datagram(expected, mask, window):
    return f'task,{expected},{mask},{window}'.encode('ascii')


def parse_datagram(b):
    f = b.decode('ascii', 'replace').strip().split(',')
    if len(f) != 4 or f[0] != 'task':
        return None
    e, m, w = int(f[1]), int(f[2]), int(f[3])
    if not (0 <= e <= 4 and 0 <= m <= 31 and 0 <= w < 2 ** 32):
        return None
    return e, m, w
