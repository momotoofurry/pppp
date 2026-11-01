"""Start-up alignment and the R3 block end through the real-time loop (rt.c over the serial protocol, PC build),
firmware of 2026-10-30 (report 20): RT_ALIGN_MIN, RT_EV_ALIGN_SHORT, RT_RESCALE.

Subject 0 (as board_replay.py): SET_REPORT 1, the 6 calibration recordings, CALIBRATE; then, with every test
recording rotated by r channels (np.roll of the 8 raw channels: sensor c now records what sensor c - r recorded):
  align   STREAM_RESET, ALIGN_START, the first n recordings of test block 0 back to back (one continuous stream,
          no reset in between, as a real start-up), ALIGN_END
  test    blocks 1 and 2, per recording STREAM_RESET + samples (2 self-calibration blocks)
Cases: n = 1 (10 windows: must give ALIGN_SHORT and keep the rotation), n = 8 (71 windows) for r = 0, 1, 2, -1;
r = 1 without alignment; r = 0 with RT_RESCALE = 0 (firmware v2 block end); blocks 1-4 with only Rest, Tripod and Open (the update must be
skipped: RT_MIN_CLASSES, report 22). Accuracy from the PRED packets.
2026-11-02 (report 25): with the alignment confidence rule r = 2 must give ALIGN_UNSURE 2 and rotation 0 (only
+-1 is corrected); column 'unsure' = the rejected estimate (0 = none).
Writes results/align_rt_check.csv. Usage (in the container): python src/check_align_rt.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pc'))
import board_replay as BR  # noqa: E402
import check_rt as R  # noqa: E402
import protocol as PR  # noqa: E402

OUT = os.path.join(BR.P.ROOT, 'results')


def stream(r, n_align, blocks=(1, 2), keep=None):
    enc = PR.Encoder()
    pk, labels = [(enc.control(PR.SET_REPORT, 1), 0.0)], []

    def samples(frames):
        for i in range(0, len(frames), PR.FRAMES_PER_PACKET):
            pk.append((enc.packet(PR.SAMPLES, frames[i:i + PR.FRAMES_PER_PACKET].tobytes()), 0.0))
    recs, lab = R.recordings(BR.SUBJECT, 'calibration')
    for frames, y in zip(recs, lab):
        pk += [(enc.control(PR.STREAM_RESET), 0.0), (enc.control(PR.CAL_START, int(y)), 0.0)]
        samples(frames)
        pk.append((enc.control(PR.CAL_END), 0.0))
    pk.append((enc.control(PR.CALIBRATE), 0.0))
    if n_align:
        recs, _ = R.recordings(BR.SUBJECT, 'testing_block0')
        pk += [(enc.control(PR.STREAM_RESET), 0.0), (enc.control(PR.ALIGN_START), 0.0)]
        samples(np.ascontiguousarray(np.roll(np.concatenate(recs[:n_align]), r, axis=1)))
        pk.append((enc.control(PR.ALIGN_END), 0.0))
    for b in blocks:
        recs, lab = R.recordings(BR.SUBJECT, f'testing_block{b}')
        for frames, y in zip(recs, lab):
            if keep is not None and int(y) not in keep:
                continue
            pk.append((enc.control(PR.STREAM_RESET), 0.0))
            samples(np.ascontiguousarray(np.roll(frames, r, axis=1)))
            labels += [int(y)] * ((len(frames) - 400) // 200 + 1 - BR.WARMUP)
    return pk, np.array(labels)


def main():
    cases = [(0, 1, 1, None), (0, 8, 1, None), (1, 8, 1, None), (2, 8, 1, None), (-1, 8, 1, None), (1, 0, 1, None),
             (0, 8, 0, None), (0, 8, 1, (5, 2, 4))]
    rows = []
    for r, n, rescale, keep in cases:
        pk, y = stream(r, n, (1, 2, 3, 4) if keep else (1, 2), keep)
        lib = os.path.join(BR.P.ROOT, 'build', 'c', f'librt_align_{rescale}.so')
        preds, status = BR.run_stream(pk, 1, lib, [f'-DRT_RESCALE={rescale}'])
        assert len(preds) == len(y), (len(preds), len(y))
        ev = [(m['event'], m['value']) for m in status]
        al = [v for e, v in ev if e in (PR.EV_ALIGNED, PR.EV_ALIGN_SHORT)]
        hit = preds.class_id.values == y
        acc = [hit[k * 300:(k + 1) * 300].mean() * 100 for k in range(max(2, len(y) // 300))]
        rows.append(dict(rotation=r, align_recordings=n, rt_rescale=rescale, gestures='5,2,4' if keep else 'all',
                         skipped=sum(e == PR.EV_SC_SKIP for e, _ in ev),
                         align_event={PR.EV_ALIGNED: 'aligned', PR.EV_ALIGN_SHORT: 'short'}.get(
                             next((e for e, _ in ev if e in (PR.EV_ALIGNED, PR.EV_ALIGN_SHORT)), None), 'none'),
                         align_value=al[0] if al else None, unsure=dict(ev).get(PR.EV_ALIGN_UNSURE, 0),
                         calibrated=dict(ev).get(PR.EV_CALIBRATED),
                         selfcal_blocks=max([v for e, v in ev if e == PR.EV_SELFCAL], default=0),
                         acc_block1=acc[0], acc_block2=acc[1]))
        print(rows[-1])
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, 'align_rt_check.csv'), index=False, float_format='%.3f')
    print(df.to_string(index=False))


if __name__ == '__main__':
    main()
