"""Stage 2.1/2.2: structure and raw byte size of the two pre-trained RF models.

Writes results/model_stats.csv (one row per model) and results/model_stats_trees.csv
(one row per tree).

Usage: .venv/Scripts/python src/model_stats.py
"""
import os
import sys

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rf_size  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.join(ROOT, 'external', 'self-calibrating-rf')
OUT = os.path.join(ROOT, 'results')
MODELS = {'38 participants (demo)': 'model_pretrain.joblib',
          '66 participants (arm_position)': 'model_pretrain_with_66_participants.joblib'}


def main():
    rows, tree_rows = [], []
    for name, f in MODELS.items():
        m = joblib.load(os.path.join(REPO, 'model_pretrain', f))
        stats = []
        for i, e in enumerate(m.estimators_):
            t = e.tree_
            s = rf_size.tree_stats(t.children_left, t.children_right)
            assert s['nodes'] == t.node_count and s['depth'] == t.max_depth
            stats.append(s)
            tree_rows.append(dict(model=name, tree=i, **s))
        df = pd.DataFrame(stats)
        row = dict(model=name, file=f, n_trees=len(stats), n_features=m.n_features_in_,
                   n_classes=len(m.classes_), max_samples=m.max_samples, max_depth_param=m.max_depth,
                   nodes_per_tree_mean=df.nodes.mean(), nodes_per_tree_max=df.nodes.max(),
                   depth_mean=df.depth.mean(), depth_max=df.depth.max(),
                   mean_leaf_depth=df.mean_leaf_depth.mean(),
                   total_nodes=df.nodes.sum(), total_internal=df.internal.sum(), total_leaves=df.leaves.sum())
        for thr in ['float32', 'int16']:
            b = rf_size.forest_bytes(stats, thr)
            row[f'naive_{thr}_KB'] = b['naive'] / 1024
            row[f'compact_{thr}_KB'] = b['compact'] / 1024
        # what sklearn itself keeps per node (for reference): Node struct + value array (float64 x 6)
        row['sklearn_in_memory_KB'] = sum(e.tree_.node_count * (64 + 8 * len(m.classes_))
                                          for e in m.estimators_) / 1024
        row['joblib_file_KB'] = os.path.getsize(os.path.join(REPO, 'model_pretrain', f)) / 1024
        rows.append(row)

    res = pd.DataFrame(rows).set_index('model')
    res.to_csv(os.path.join(OUT, 'model_stats.csv'), float_format='%.2f')
    pd.DataFrame(tree_rows).to_csv(os.path.join(OUT, 'model_stats_trees.csv'), index=False, float_format='%.3f')
    pd.set_option('display.width', 200)
    print(res.T.to_string())


if __name__ == '__main__':
    main()
