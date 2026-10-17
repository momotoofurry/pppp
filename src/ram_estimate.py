"""Stage 4: RAM estimate for on-MCU feature extraction and self-calibration (a design calculation).

Only the 'measured' rows come from runs (results/arm_size.csv, results/selfcal_sweep_trees.csv);
everything else is bytes = count x element size for a planned C implementation, and is labelled
'estimate'. Writes results/ram_estimate.csv and prints the scenario totals.
Usage: .venv/Scripts/python src/ram_estimate.py
"""
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'results')

N_CH, FS, WIN, NFFT, N_FEAT, N_CLS = 8, 2000, 400, 512, 80, 6
BUF, N_CALIB = 1500, 60                    # buffer size and calibration windows (upstream values)
TSNE_NEIGHBORS = int(3 * 10 + 1)           # sklearn Barnes-Hut: 3 * perplexity + 1, perplexity = 10
NODE_B = 1 + 2 + 2 + 2                     # compact int16 node: feat u8 + thr i16 + left/right u16


def main():
    arm = pd.read_csv(os.path.join(OUT, 'arm_size.csv')).set_index(['config', 'impl'])
    a = arm.loc[('d10_n100_i16', 'table')]
    infer = int(a.static_ram_bytes + a.worst_stack_bytes)

    rows = []

    def add(group, item, n_bytes, basis, kind='estimate'):
        rows.append(dict(group=group, item=item, bytes=int(n_bytes), kind=kind, basis=basis))

    add('inference', 'feature buffers + stack (d10_n100_i16, table)', infer,
        'arm_size.csv: static RAM + worst-case stack', 'measured')
    # feature extraction, streaming every 100 ms over a 200 ms window
    add('feature extraction', 'filtered sample ring buffer', WIN * N_CH * 4, f'{WIN} samples x {N_CH} ch x float32')
    add('feature extraction', 'band-pass IIR state', 4 * 2 * N_CH * 4,
        '4th-order band-pass = 4 biquads x 2 states x 8 ch x float32')
    add('feature extraction', 'FFT in/out buffers', 2 * NFFT * 4, f'2 x {NFFT} float32 (CMSIS arm_rfft_fast_f32)')
    add('feature extraction', 'Welch PSD', (NFFT // 2 + 1) * 4, f'{NFFT // 2 + 1} bins x float32')
    # self-calibration
    for prec, b in [('float32', 4), ('int16', 2)]:
        add(f'self-cal buffer ({prec})', 'buffered feature vectors', BUF * N_FEAT * b, f'{BUF} x {N_FEAT} x {prec}')
        add(f'self-cal buffer ({prec})', 'calibration set', N_CALIB * N_FEAT * b, f'{N_CALIB} x {N_FEAT} x {prec}')
    add('self-cal', 'buffer pseudo-labels', BUF, f'{BUF} x uint8')
    # appended-tree region after self-calibration, measured by src/selfcal_sweep.py:
    # internal nodes of a binary tree = (nodes - 1) / 2, so region = n_app * (mean nodes - 1) / 2 * 7 B,
    # and the RAM pool must hold the largest region seen over all subjects and seeds
    tr = pd.read_csv(os.path.join(OUT, 'selfcal_sweep_trees.csv'))
    for cfg, n_app, label, node_b in [('N100_d10_int16', 50, 'depth 10 int16', NODE_B),
                                      ('N400_d10_int16', 200, 'depth 10 int16', NODE_B),
                                      ('N400_dnone_float32', 200, 'no depth limit float32', NODE_B + 2)]:
        m = tr[tr.config == cfg]
        reg = n_app * (m.app_nodes_mean - 1) / 2 * node_b
        add('self-cal', f'replaceable trees, {n_app} appended, {label} (mean)', reg.mean(),
            f'{cfg}: mean over {len(m)} subject x seed runs (selfcal_sweep_trees.csv)', 'from measured tree size')
        add('self-cal', f'replaceable trees, {n_app} appended, {label} (largest run)', reg.max(),
            f'{cfg}: largest of {len(m)} subject x seed runs (selfcal_sweep_trees.csv)', 'from measured tree size')
    n_train = BUF + N_CALIB
    add('self-cal', 'RF training scratch (one tree at a time)',
        n_train * 2 + n_train * 4 + n_train * 2 + (2 ** 11) * NODE_B,
        f'bootstrap idx u16 + sorted values f32 + sort idx u16 over {n_train} samples + 2^11-node tree build buffer')
    add('pseudo-label: K-Means 80-D', 'assignments + centroids (+ new)', BUF + 2 * N_CLS * N_FEAT * 4,
        f'{BUF} x u8 + 2 x {N_CLS} x {N_FEAT} x float32')
    add('pseudo-label: Barnes-Hut t-SNE 3-D', 'sparse P (neighbour idx u16 + p f32)', BUF * TSNE_NEIGHBORS * 6,
        f'{BUF} x {TSNE_NEIGHBORS} neighbours x 6 B')
    add('pseudo-label: Barnes-Hut t-SNE 3-D', 'embedding, gradient, update, gains', 4 * BUF * 3 * 4,
        f'4 x {BUF} x 3 x float32')
    add('pseudo-label: Barnes-Hut t-SNE 3-D', 'octree', BUF * 40, f'~{BUF} cells x 40 B (centre, mass, children)')
    df = pd.DataFrame(rows)
    df['KB'] = df.bytes / 1024
    df.to_csv(os.path.join(OUT, 'ram_estimate.csv'), index=False, float_format='%.1f')
    pd.set_option('display.width', 200)
    print(df[['group', 'item', 'bytes', 'KB', 'kind']].round(1).to_string(index=False))

    g = df.groupby('group').bytes.sum()
    it = df.set_index('item').bytes
    fe = g['feature extraction']
    common = infer + fe + it['buffer pseudo-labels'] + it['RF training scratch (one tree at a time)']
    tsne = g['pseudo-label: Barnes-Hut t-SNE 3-D']
    scen = {
        'A paper-faithful: float32 buffer, 400 trees (200 appended, no depth limit), t-SNE + K-Means':
            common + g['self-cal buffer (float32)'] + it['replaceable trees, 200 appended, no depth limit float32 (largest run)'] + tsne
            + g['pseudo-label: K-Means 80-D'],
        'B int16 buffer, 100 trees (50 appended), t-SNE + K-Means':
            common + g['self-cal buffer (int16)'] + it['replaceable trees, 50 appended, depth 10 int16 (largest run)'] + tsne
            + g['pseudo-label: K-Means 80-D'],
        'C int16 buffer, 100 trees (50 appended), K-Means only (no t-SNE)':
            common + g['self-cal buffer (int16)'] + it['replaceable trees, 50 appended, depth 10 int16 (largest run)']
            + g['pseudo-label: K-Means 80-D'],
    }
    s = pd.DataFrame({'bytes': scen}).assign(KB=lambda x: x.bytes / 1024)
    s['fits AXI 512 KB'] = s.KB <= 512
    s['fits all SRAM ~1 MB'] = s.KB <= 1024
    s.to_csv(os.path.join(OUT, 'ram_scenarios.csv'), float_format='%.1f')
    print('\n' + s.round(1).to_string())


if __name__ == '__main__':
    main()
