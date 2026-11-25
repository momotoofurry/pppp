"""Local monitor for real-arm sessions (report 35.108): rules detect, a local LLM explains. Windows Python, standard
library only; reads the session's logs (they may sit in WSL: \\\\wsl.localhost\\Ubuntu-22.04\\...) and Ollama on this PC.
Read-only: it never sends anything to the arm or the board.

  python tools\\local-monitor\\monitor.py --dir <session folder>            live: follows the logs, Ctrl-C to stop
  python tools\\local-monitor\\monitor.py --dir <folder> --replay           a finished session, all at once
  options: --no-llm (rule texts only), --model <ollama model>, --out <folder> (alerts.jsonl, report.md; default: --dir)
Files it looks for in --dir (any prefix): *assist_board.csv, *board_events.csv, *task_events.csv, *_mcu.csv.
Severity: high = the arm or the data path is affected now; warn = worth a look; info = context for the summary."""
import argparse
import collections
import csv
import glob
import io
import json
import os
import queue
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import explain as EX  # noqa: E402
import rules as RU    # noqa: E402

KINDS = (('assist', '*assist_board.csv'), ('board', '*board_events.csv'), ('task', '*task_events.csv'), ('mcu', '*_mcu.csv'))
COLOR = {'high': '\033[91m', 'warn': '\033[93m', 'info': '\033[96m'}


class Tail:
    """new complete rows of a growing CSV (re-reads from the top if the file was rewritten)"""

    def __init__(self, path):
        self.path, self.pos, self.header = path, 0, None

    def rows(self):
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return []
        if size < self.pos:
            self.pos, self.header = 0, None
        with open(self.path, 'rb') as f:
            f.seek(self.pos)
            data = f.read()
        if not data:
            return []
        cut = data.rfind(b'\n') + 1
        if cut == 0:
            return []
        self.pos += cut
        lines = data[:cut].decode('utf-8', errors='replace').splitlines()
        if self.header is None:
            self.header, lines = lines[0], lines[1:]
        return list(csv.DictReader(io.StringIO('\n'.join([self.header] + lines))))


class Context:
    """the last seconds, summarised for the LLM"""

    def __init__(self):
        self.steps = collections.deque(maxlen=100)       # 10 s of control steps
        self.events = collections.deque(maxlen=12)

    def add(self, kind, r):
        if kind == 'assist':
            self.steps.append(r)
        elif kind in ('task', 'board') and (r.get('event') or r.get('command')) not in (None, '', 'grip_result'):
            ev = r.get('event') or r.get('command')
            self.events.append(f'{ev} {r.get("a", "") or r.get("applied", "")}'.strip())

    def text(self):
        if self.steps:
            st = [s.get('state', '') for s in self.steps]
            seq = [st[0]] + [b for a, b in zip(st, st[1:]) if a != b]
            cmds = collections.Counter(s.get('command', '') for s in self.steps)
            te = max(RU.num(s.get('track_err'), 0) for s in self.steps)
            s = (f'最近 {len(self.steps) / 10:.0f} 秒：狀態 {" → ".join(seq[-6:])}；指令次數 {dict(cmds)}；'
                 f'最大追蹤誤差 {100 * te:.1f} cm')
        else:
            s = '沒有手臂控制紀錄'
        return s + '；最近事件：' + ('、'.join(self.events) if self.events else '無')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--replay', action='store_true')
    ap.add_argument('--no-llm', action='store_true')
    ap.add_argument('--model', default=EX.MODEL)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    out = a.out or a.dir
    os.makedirs(out, exist_ok=True)
    det, ctx = RU.Detector(), Context()
    tails = {}
    alerts = []
    jq = queue.Queue()
    log = open(os.path.join(out, 'alerts.jsonl'), 'a', encoding='utf-8')
    use_llm = not a.no_llm

    def worker():
        while True:
            al, c = jq.get()
            if al is None:
                return
            # info alerts keep the rule's own text (no LLM: they are frequent and only context)
            text, ok = EX.explain(al, c, a.model) if use_llm and al['severity'] != 'info' else (EX.fallback(al), False)
            al['explanation'], al['by_llm'] = text, ok
            log.write(json.dumps(al, ensure_ascii=False) + '\n')
            log.flush()
            print(f'{COLOR[al["severity"]]}[{al["severity"]}] {time.strftime("%H:%M:%S", time.localtime(al["time"] or 0))} '
                  f'{al["title"]}\033[0m  {json.dumps(al["data"], ensure_ascii=False)}\n  ' +
                  text.replace('\n', '\n  ') + ('' if ok else '') + '\n', flush=True)
    th = threading.Thread(target=worker, daemon=True)
    th.start()

    def scan():
        new = []
        for kind, pat in KINDS:
            for p in glob.glob(os.path.join(a.dir, pat)):
                if p not in tails:
                    tails[p] = (kind, Tail(p))
        batch = []
        for p, (kind, t) in tails.items():
            for r in t.rows():
                batch.append((kind, r))
        def key(kr):
            k, r = kr
            return RU.num(r.get('wall')) or (RU.num(r.get('unix_ms')) or RU.num(r.get('recv_unix_ms')) or 0) / 1000
        for kind, r in sorted(batch, key=key):
            ctx.add(kind, r)
            for al in det.feed(kind, r):
                new.append(al)
                jq.put((al, ctx.text()))
        return new

    print(f'local monitor: {a.dir} ({"replay" if a.replay else "live"}, LLM {"off" if a.no_llm else a.model})', flush=True)
    try:
        if a.replay:
            alerts += scan()
        else:
            while True:
                alerts += scan()
                for al in det.quiet(time.time()):
                    alerts.append(al)
                    jq.put((al, ctx.text()))
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    jq.put((None, None))
    th.join()
    n = collections.Counter(al['rule'] for al in alerts)
    rep = [f'# 監看摘要：{a.dir}', '', f'警示 {len(alerts)} 則：' + ('、'.join(f'{RU.TITLE[k]} {v}' for k, v in n.items()) or '無'), '']
    for al in alerts:
        rep.append(f'- [{al["severity"]}] {time.strftime("%H:%M:%S", time.localtime(al["time"] or 0))} {al["title"]} '
                   f'{json.dumps(al["data"], ensure_ascii=False)}')
    open(os.path.join(out, 'report.md'), 'w', encoding='utf-8').write('\n'.join(rep) + '\n')
    print('\n'.join(rep[:3]))


if __name__ == '__main__':
    main()
