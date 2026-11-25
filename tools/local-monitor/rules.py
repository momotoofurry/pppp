"""Detection rules of the local monitor (report 35.108). Deterministic, no AI: every alert comes from a rule here.
The LLM (explain.py) only turns an alert and its context into a Chinese explanation.

Input rows (dicts from csv.DictReader) of four session logs:
  assist_board.csv   assist_ros.py, every 100 ms: t, command, state, track_err, wall (unix s)
  board_events.csv   assist_ros.py board: command events, deadman, 'packets lost'
  task_events.csv    assist_ros.py: grasp / putdown / lock_obj / lock_shelf / reset_* / grip_result / grip_empty
  *_mcu.csv          TrignoBridge: the board's status reports (UART errors, bytes dropped, packets lost)
Rules (id, severity, what):
  loop_stall         warn/high  two control steps more than 0.3 s apart (> 1.0 s: high): the control loop stopped;
                                one alert per episode (slow steps within 2 s); not after a reset_done (the new
                                trial's planned 3 s move to the start)
  tracking_hold      high       5 steps in a row with the arm > 4 cm from the command (assist_ros holds there too)
  deadman_stop       warn       no heartbeat from the board for 0.5 s while moving: the arm was stopped
  packets_lost       high       the board / bridge lost packets (assist_ros stops)
  uart_errors_rising warn       the board's UART error count went up after its first report
  bytes_dropped      high       the board dropped received UART bytes
  air_grasp          warn       the gripper closed on air (assist_ros --grip-check)
  reset_refused      info       a new trial could not start (arm in mode 2 / still holding)
  putdown_off_shelf  warn       an object was put down but stands on no shelf
  repeated_locks     info       3 or more locks since the last put-down / trial start: the user struggles to lock
  no_new_steps       high       (live only) assist_board.csv stopped growing for 3 s while it was being written
"""

STALL_S, STALL_HIGH_S = 0.3, 1.0
EPISODE_S = 2.0             # slow steps within 2 s of the last one belong to the same stall
TRACK_M, TRACK_N = 0.04, 5
LOCKS_N = 3
QUIET_S = 3.0

TITLE = {
    'loop_stall': '控制迴圈停頓', 'tracking_hold': '手臂沒跟上指令（追蹤保護）', 'deadman_stop': '板子心跳中斷，手臂停下',
    'packets_lost': '封包遺失', 'uart_errors_rising': '板子 UART 錯誤增加', 'bytes_dropped': '板子丟失 UART 資料',
    'air_grasp': '空抓', 'reset_refused': '新試驗無法開始', 'putdown_off_shelf': '物體沒放在架子上',
    'repeated_locks': '反覆鎖定', 'no_new_steps': '手臂程式沒有在寫紀錄',
}
MEANING = {
    'loop_stall': '控制程式兩步之間隔太久，可能是電腦（WSL）暫停。手臂會停在原地或被 deadman 停下。',
    'tracking_hold': '手臂實際位置和指令差超過 4 cm 連續 5 步，可能被擋住、控制器停了、或按了急停。程式已停住，放鬆一次才繼續。',
    'deadman_stop': '0.5 秒沒收到板子的心跳，手臂已停；要做新的手勢才會再動。可能是橋接程式、USB 或電腦卡頓。',
    'packets_lost': '板子或橋接程式掉了封包，手臂已停。可能是 USB 線鬆、序列埠被占用或電腦負載太高。',
    'uart_errors_rising': '板子收到的序列資料有錯誤，而且在增加。可能是 USB 線、接頭或干擾。',
    'bytes_dropped': '板子的接收緩衝溢出，丟了資料。',
    'air_grasp': '夾爪閉合到底，沒有夾到物體，已自動打開。',
    'reset_refused': '協助者要開始新試驗，但手臂還在架子裡（模式 2）或夾著物體。',
    'putdown_off_shelf': '物體被放下了，但位置不在任何架子上。',
    'repeated_locks': '同一個試驗裡鎖定了很多次，可能一直鎖錯目標、或停的位置不準。',
    'no_new_steps': '手臂控制程式超過 3 秒沒有新的紀錄，可能已經停止或卡住。',
}


def num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class Detector:
    """feed(kind, row) -> list of alerts; an alert is a dict(rule, severity, time (unix s), title, meaning, data)"""

    def __init__(self):
        self.prev_wall = None
        self.prev_mono = None
        self.last_reset_t = None        # a new trial's 3 s move back to the start: a planned gap, not a stall
        self.stall_end = None           # one pause shows as 2-3 slow steps: one alert per episode
        self.track_n = 0
        self.track_on = False
        self.locks = 0
        self.mcu_last = {}
        self.last_step_wall = None

    def alert(self, rule, sev, t, **data):
        return dict(rule=rule, severity=sev, time=t, title=TITLE[rule], meaning=MEANING[rule], data=data)

    def feed(self, kind, r):
        if kind == 'assist':
            return self._assist(r)
        if kind == 'board':
            return self._board(r)
        if kind == 'task':
            return self._task(r)
        if kind == 'mcu':
            return self._mcu(r)
        return []

    def _assist(self, r):
        out = []
        wall, te = num(r.get('wall')), num(r.get('track_err'), 0.0)
        mono = num(r.get('mono'))           # 35.109: the monotonic clock (logs since 35.109); the wall clock is
        if wall is not None:                # stepped by the time sync and gave false stalls (WSL tick 5 % off)
            self.last_step_wall = wall
            if mono is not None and self.prev_mono is not None:
                gap = mono - self.prev_mono
                clock = 'monotonic'
            else:
                gap = wall - self.prev_wall if self.prev_wall is not None else 0.0
                clock = 'wall (no mono column: may be a clock step, report 35.109)'
            self.prev_mono = mono
            if self.prev_wall is not None and gap > STALL_S:
                planned = self.last_reset_t is not None and self.prev_wall < self.last_reset_t <= wall + 0.5
                same = self.stall_end is not None and self.prev_wall - self.stall_end < EPISODE_S
                if not planned and not same:
                    out.append(self.alert('loop_stall', 'high' if gap > STALL_HIGH_S else 'warn', wall,
                                          gap_s=round(gap, 2), step_t=r.get('t'), state=r.get('state'), clock=clock))
                if not planned:
                    self.stall_end = wall
            self.prev_wall = wall
        self.track_n = self.track_n + 1 if te > TRACK_M else 0
        if self.track_n >= TRACK_N and not self.track_on:
            self.track_on = True
            out.append(self.alert('tracking_hold', 'high', wall, track_err_m=te, step_t=r.get('t'), state=r.get('state')))
        if self.track_n == 0:
            self.track_on = False
        return out

    def _board(self, r):
        t = (num(r.get('recv_unix_ms'), 0.0) or 0.0) / 1000
        cmd = (r.get('command') or '').strip()
        if cmd == 'deadman':
            return [self.alert('deadman_stop', 'warn', t)]
        if cmd == 'status' and 'packets lost' in (r.get('gesture') or ''):
            return [self.alert('packets_lost', 'high', t, source='assist_ros')]
        return []

    def _task(self, r):
        t = (num(r.get('unix_ms'), 0.0) or 0.0) / 1000
        ev = (r.get('event') or '').strip()
        if ev in ('lock_obj', 'lock_shelf'):
            self.locks += 1
            if self.locks == LOCKS_N:
                return [self.alert('repeated_locks', 'info', t, locks=self.locks, last=f'{ev} {r.get("a")}')]
            return []
        if ev in ('putdown', 'reset_done'):
            self.locks = 0
            if ev == 'reset_done':
                self.last_reset_t = t
            if ev == 'putdown' and (r.get('b') or '') == '':
                return [self.alert('putdown_off_shelf', 'warn', t, obj=r.get('a'), where=r.get('detail'))]
            return []
        if ev == 'grip_empty':
            return [self.alert('air_grasp', 'warn', t, obj=r.get('a'), position=r.get('detail'))]
        if ev == 'reset_refused':
            return [self.alert('reset_refused', 'info', t, trial=r.get('a'), reason=r.get('detail'))]
        return []

    def _mcu(self, r):
        if (r.get('kind') or '') != 'status':
            return []
        t = (num(r.get('unix_ms'), 0.0) or 0.0) / 1000
        ev, v = (r.get('event') or '').strip(), num(r.get('value'))
        if v is None or ev not in ('UART errors', 'UART bytes dropped', 'packets lost'):
            return []
        prev = self.mcu_last.get(ev)
        self.mcu_last[ev] = v
        if prev is None or v <= prev:
            return []            # the first report is the baseline (e.g. 1 UART error from the reset, 35.96)
        rule = {'UART errors': 'uart_errors_rising', 'UART bytes dropped': 'bytes_dropped', 'packets lost': 'packets_lost'}[ev]
        sev = 'warn' if rule == 'uart_errors_rising' else 'high'
        return [self.alert(rule, sev, t, before=prev, now=v, source='board status')]

    def quiet(self, now):
        """live mode: the control log stopped growing (None if it never started)"""
        if self.last_step_wall is not None and now - self.last_step_wall > QUIET_S:
            t = self.last_step_wall
            self.last_step_wall = None           # once per silence
            return [self.alert('no_new_steps', 'high', now, silent_s=round(now - t, 1))]
        return []
