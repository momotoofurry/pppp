"""Board vs PC commands for a board replay (pilot-freeze-5: Lateral = home).

The board's COMMAND packets (rx.bin of a serial_replay.ps1 run, board_replay.py make stream) against the commands of
the PC build of rt.c on the same stream (board_replay.run_stream, its commands collected here): window number,
command and top class must be equal one by one. Writes results/board_commands<tag>.csv (both lists side by side).
Usage (in the container): PYTHONPATH=src python src/check_commands_board.py --dir build/board_replay_freeze5 --tag _freeze5
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board_replay as B  # noqa: E402

PR = B.PR


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--tag', default='')
    ap.add_argument('--blocks', type=int, default=2)
    ap.add_argument('--delay', type=int, default=1)
    a = ap.parse_args()
    d = os.path.join(B.P.ROOT, a.dir)
    dec, board = PR.Decoder(), []
    for t, _, p in dec.feed(open(os.path.join(d, 'rx.bin'), 'rb').read()):
        m = PR.parse_mcu(t, p)
        if m['kind'] == 'command':
            board.append(m)
    pc, orig = [], PR.parse_mcu

    def spy(t, p):
        m = orig(t, p)
        if m['kind'] == 'command':
            pc.append(m)
        return m
    PR.parse_mcu = spy
    B.run_stream(B.packets(a.blocks)[0], a.delay)
    PR.parse_mcu = orig
    n = max(len(board), len(pc))
    rows = []
    for i in range(n):
        b = board[i] if i < len(board) else {}
        c = pc[i] if i < len(pc) else {}
        rows.append(dict(i=i, board_window=b.get('window'), board_command=b.get('command'), board_top=b.get('top'),
                         pc_window=c.get('window'), pc_command=c.get('command'), pc_top=c.get('top'),
                         same=(b.get('window'), b.get('command')) == (c.get('window'), c.get('command'))))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(B.P.ROOT, 'results', f'board_commands{a.tag}.csv'), index=False)
    print(df.to_string(index=False))
    print(f'board {len(board)} commands, PC {len(pc)}, identical {int(df.same.sum())}; per command (board):',
          pd.Series([m["command"] for m in board]).value_counts().to_dict())


if __name__ == '__main__':
    main()
