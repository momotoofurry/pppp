"""Label-free channel layout check for the Kyranou 2025 data (src/external_check.py): correlation of the 50 ms
log-RMS envelope between the 16 channels, day 1 session 1 of the 8 subjects, pooled. No labels, no classifier.
Result (2026-11-02): zig-zag ring 9-1-10-2-11-3-12-4-13-5-14-6-15-7-16-8-(9) -> channels 1-8 and 9-16 are the two
rings of 8, each in file order, half a position apart.
Usage (in the container, data mounted read-only): python src/external_channels.py --data /data
"""
import argparse
import os

import h5py
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default='/data')
    args = ap.parse_args()
    np.set_printoptions(linewidth=200, precision=2, suppress=True)
    pooled = []
    for p in range(1, 9):
        path = os.path.join(args.data, 'data', f'participant_{p}', f'participant{p}_day1_block1', 'emg_data.hdf5')
        env = []
        with h5py.File(path, 'r') as f:
            for key in f:
                x = np.asarray(f[key], dtype=np.float64)
                x = x[:, :x.shape[1] // 100 * 100].reshape(16, -1, 100)
                env.append(np.log(np.sqrt((x ** 2).mean(2)) + 1e-12))
        pooled.append(np.corrcoef(np.concatenate(env, 1)))
    pc = np.mean(pooled, 0)
    print(pc)
    for i in range(16):
        o = np.argsort(-pc[i])[1:4]
        print(f'ch{i + 1:2d} closest:', [f'{j + 1}({pc[i, j]:.2f})' for j in o])


if __name__ == '__main__':
    main()
