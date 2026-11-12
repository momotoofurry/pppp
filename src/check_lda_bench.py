"""PC reference for the on-board timing of the LDA re-calibration (src/c/lda_bench.c; exploratory, report 35.10).

Uses build/leaf_bench/leaf_rows.h (run src/check_leaf_bench.py first). Builds lda_bench.c with bench_pc.c
(gcc -O2, and -ffp-contract=off) and writes results/lda_bench_pc.txt; the board must print the same counts.
--export <dir>: copies the files a CubeMX project needs into <dir>.
Usage (in the container): python src/check_lda_bench.py [--export build/lda_bench/emg]
"""
import argparse
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as P  # noqa: E402

C = os.path.join(P.ROOT, 'src', 'c')
ROWS = os.path.join(P.ROOT, 'build', 'leaf_bench')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--export', default=None)
    args = ap.parse_args()
    assert os.path.exists(os.path.join(ROWS, 'leaf_rows.h')), 'run src/check_leaf_bench.py first'
    outs = {}
    for name, extra in (('lda_bench_pc', []), ('lda_bench_pc_nofma', ['-ffp-contract=off'])):
        exe = os.path.join(P.ROOT, 'build', 'c', name)
        os.makedirs(os.path.dirname(exe), exist_ok=True)
        subprocess.run(['gcc', '-O2', '-std=gnu11', '-Wall', *extra, f'-I{ROWS}', '-o', exe] +
                       [os.path.join(C, f) for f in ('bench_pc.c', 'lda_bench.c', 'ldacal.c')] + ['-lm'], check=True)
        outs[name] = subprocess.run([exe], check=True, capture_output=True, text=True).stdout.replace('\r\n', '\n')
    with open(os.path.join(P.ROOT, 'results', 'lda_bench_pc.txt'), 'w', newline='\n') as fh:
        fh.write(outs['lda_bench_pc'])
    print(outs['lda_bench_pc'])
    print('identical with -ffp-contract=off:', outs['lda_bench_pc'] == outs['lda_bench_pc_nofma'])
    if args.export:
        os.makedirs(args.export, exist_ok=True)
        for f in ('lda_bench.c', 'ldacal.c', 'ldacal.h', 'bench.h', 'board.h', 'board_hal.c', 'app_rt.h'):
            shutil.copy2(os.path.join(C, f), args.export)
        shutil.copy2(os.path.join(ROWS, 'leaf_rows.h'), args.export)
        print('exported to', args.export, sorted(os.listdir(args.export)))


if __name__ == '__main__':
    main()
