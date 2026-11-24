# report 35.82-35.83 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
"""Rehearsal (report 35.82): did every board command reach the arm, how late, and does the arm stop on 'none'?
Inputs: reh_mcu.csv (TrignoBridge: what the board sent), gz/board_events.csv (assist_ros: what arrived, when),
gz/assist_board.csv (assist_ros: per 100 ms control step: command, tool position)."""
import os
import sys

import numpy as np
import pandas as pd

d = sys.argv[1]
mcu = pd.read_csv(os.path.join(d, 'reh_mcu.csv'), dtype=str, keep_default_na=False)
cm = mcu[mcu.kind == 'command'].copy()
cm['ms'] = cm.unix_ms.astype(float)
ev = pd.read_csv(os.path.join(d, 'gz', 'board_events.csv'))
lg = pd.read_csv(os.path.join(d, 'gz', 'assist_board.csv'))
print(f'board COMMAND packets (bridge mcu.csv): {len(cm)}  by command: {cm.command.value_counts().to_dict()}')
print(f'events that reached assist_ros: {len(ev)}  by command: {ev.command.value_counts().to_dict()}')
same = list(cm.window.astype(int)) == list(ev.window.astype(int))
print(f'same windows in the same order: {same}')
lat_relay = ev.relay_unix_ms - ev.bridge_unix_ms
lat_tcp = ev.recv_unix_ms - ev.relay_unix_ms
q = lambda a: f'median {np.median(a):.1f} ms, p95 {np.percentile(a, 95):.1f}, max {np.max(a):.1f}'  # noqa: E731
print(f'bridge -> relay (UDP): {q(lat_relay)}')
print(f'relay -> assist_ros (TCP into WSL): {q(lat_tcp)}')
# motion per control step
p = lg[['x', 'y', 'z']].to_numpy()
step = np.r_[0.0, np.linalg.norm(np.diff(p, axis=0), axis=1)]
cmd = lg.command.astype(str).to_numpy()
mov = step > 0.0005                                   # 0.5 mm per 100 ms step (V_MAX 8 cm/s = 8 mm / step)
rest = cmd == 'rest'
# a stop takes effect at the next step: count rest steps that still move, excluding the first rest step after a move
first_rest = rest & np.r_[False, ~rest[:-1]]
print(f'control steps {len(lg)} ({len(lg) * 0.1:.0f} s): moving {mov.sum()}, commanded direction {(~rest).sum()}, rest {rest.sum()}')
print(f'rest steps that still moved (not counting the first rest step after a direction): '
      f'{int((mov & rest & ~first_rest).sum())}')
dirs = ~rest
print(f'direction steps without motion: {int((dirs & ~mov).sum())} (refused / at a limit / mode-2 rules)')
print(f'tool range x {p[:, 0].min():.3f}-{p[:, 0].max():.3f}, y {p[:, 1].min():.3f}-{p[:, 1].max():.3f}, '
      f'z {p[:, 2].min():.3f}-{p[:, 2].max():.3f} m; states {lg.state.value_counts().to_dict()}')
