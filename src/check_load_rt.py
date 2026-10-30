"""Reboot and power-loss behaviour of the route-B firmware (PC build of rt.c, as board_replay.py; report 23).

  A  normal: SET_REPORT 1, calibration (6 recordings), CALIBRATE, test blocks 0-1
  B  as A, but after CALIBRATE the MCU reboots (rt_init again: RAM state lost, the Flash image kept), then
     SET_REPORT 1 + RT_LOAD: the day-1 state comes back from Flash. The predictions must be identical to A.
  C  as B, but the image header is wiped before the reboot (as when the power is cut before the header, which is
     written last, reaches Flash): RT_LOAD must answer -1 and nothing may be classified.
  D  as A, then RT_LOAD after the test blocks and the same two blocks again: restarts from the day-1 model (adapted
     trees are not kept), so the second pass must equal the first.
  E  the fixed-model condition: after CALIBRATE, RT_SET_ADAPT 0 and the test blocks: no self-calibration, block 0 as in
     A (no update has happened there yet); then RT_LOAD + RT_SET_ADAPT 1 and the blocks again must equal A (the full
     condition after the fixed one starts from the same day-1 model).
Writes results/load_rt_check.csv. Usage (in the container): python src/check_load_rt.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pc'))
import board_replay as BR  # noqa: E402
import protocol as PR  # noqa: E402

OUT = os.path.join(BR.P.ROOT, 'results')


def control(sub, *args):
    return PR.build(PR.CONTROL, 0, PR.control_payload(sub, *args))


def main():
    pk, _ = BR.packets(2)
    cal = next(i for i, (b, _) in enumerate(pk) if b[2] == PR.CONTROL and b[7] == PR.CALIBRATE)
    head, tail = pk[:cal + 1], pk[cal + 1:]
    load = [(control(PR.SET_REPORT, 1), 0.0), (control(PR.LOAD), 0.0)]
    cases = {'A': pk,
             'B': head + [(BR.REBOOT, 0.0)] + load + tail,
             'C': head + [(BR.WIPE_HEADER, 0.0), (BR.REBOOT, 0.0)] + load + tail,
             'D': pk + [(BR.IDLE, 0.0), (control(PR.LOAD), 0.0)] + tail,
             'E': head + [(control(PR.SET_ADAPT, 0), 0.0)] + tail + [(BR.IDLE, 0.0), (control(PR.LOAD), 0.0),
                                                                    (control(PR.SET_ADAPT, 1), 0.0)] + tail}
    res, rows = {}, []
    for name, stream in cases.items():
        preds, status = BR.run_stream(stream, 1)
        res[name] = preds
        ev = [(m['event'], m['value']) for m in status]
        loaded = [v for e, v in ev if e == PR.EV_LOADED]
        rows.append(dict(case=name, preds=len(preds), loaded=loaded[0] if loaded else None,
                         selfcal=sum(e == PR.EV_SELFCAL for e, _ in ev)))
        print(name, rows[-1], ev[:8])
    a = res['A'].class_id.values
    rows[1]['same_as_A'] = bool(len(res['B']) == len(a) and (res['B'].class_id.values == a).all())
    rows[2]['same_as_A'] = None
    d = res['D'].class_id.values
    rows[3]['same_as_A'] = bool(len(d) == 2 * len(a) and (d[:len(a)] == a).all() and (d[len(a):] == a).all())
    e = res['E'].class_id.values
    rows[4]['same_as_A'] = bool(len(e) == 2 * len(a) and (e[:300] == a[:300]).all() and (e[len(a):] == a).all())
    rows[4]['fixed_differs_from_A'] = int((e[300:len(a)] != a[300:]).sum())
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, 'load_rt_check.csv'), index=False)
    print(df.to_string(index=False))
    assert rows[1]['same_as_A'] and rows[3]['same_as_A'] and rows[2]['loaded'] == -1 and rows[2]['preds'] == 0
    assert rows[4]['same_as_A'] and rows[4]['selfcal'] == 1        # only the full pass self-calibrates


if __name__ == '__main__':
    main()
