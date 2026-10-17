"""Shared helpers: flat tree representation, depth truncation, compaction and byte-size model.

A forest is the upstream dict format ({'left','right','feature','threshold','value','classes'},
lists with one numpy array per tree, as produced by emg_functions.get_sklearn_rf_parameters).
Leaves have left == right == -1. Pruned nodes stay in the arrays but become unreachable,
so all size numbers here count only nodes reachable from the root.
"""
import numpy as np

# bytes per field
FEAT_B = 1          # uint8 feature index (80 features)
CHILD_B = 2         # uint16 child index (largest tree < 1000 nodes)
CLASS_B = 1         # uint8 class label
THR_B = {'float32': 4, 'int16': 2}
TREE_HDR_B = 4      # per-tree offset into the node pool (uint32)


def reachable(left, right):
    """Indices of nodes reachable from root, in DFS pre-order, plus their depths."""
    order, depth = [], []
    stack = [(0, 0)]
    while stack:
        n, d = stack.pop()
        order.append(n)
        depth.append(d)
        if left[n] >= 0:
            stack.append((right[n], d + 1))
            stack.append((left[n], d + 1))
    return np.array(order), np.array(depth)


def tree_stats(left, right):
    order, depth = reachable(left, right)
    is_leaf = left[order] < 0
    return dict(nodes=len(order), internal=int((~is_leaf).sum()), leaves=int(is_leaf.sum()),
                depth=int(depth.max()), mean_leaf_depth=float(depth[is_leaf].mean()))


def forest_stats(mdl):
    return [tree_stats(l, r) for l, r in zip(mdl['left'], mdl['right'])]


def forest_bytes(stats, thr='float32'):
    """Two storage layouts, in bytes.

    naive   : every node stores feature(u8) + threshold + left(u16) + right(u16) + class(u8)
    compact : only internal nodes are stored; a child index with the top bit set is a leaf and
              its low bits hold the class, so leaves cost nothing (feature + threshold + 2 children)
    Both add a 4-byte per-tree offset table.
    """
    t = THR_B[thr]
    nodes = sum(s['nodes'] for s in stats)
    internal = sum(s['internal'] for s in stats)
    hdr = TREE_HDR_B * len(stats)
    return dict(naive=nodes * (FEAT_B + t + 2 * CHILD_B + CLASS_B) + hdr,
                compact=internal * (FEAT_B + t + 2 * CHILD_B) + hdr)


def compact_tree(left, right, feature, threshold, value):
    """Drop unreachable (pruned) nodes and renumber the rest in DFS pre-order, so every child
    index is larger than its parent's. Returns (left, right, feature, threshold, value)."""
    order, _ = reachable(left, right)
    new = -np.ones(len(left), dtype=np.int64)
    new[order] = np.arange(len(order))
    l, r = left[order], right[order]
    leaf = l < 0
    l = np.where(leaf, -1, new[np.maximum(l, 0)])
    r = np.where(leaf, -1, new[np.maximum(r, 0)])
    f = np.where(leaf, -2, feature[order])
    t = np.where(leaf, -2.0, threshold[order])
    return l, r, f, t, value[order]


def compact_forest(mdl):
    out = {k: [] for k in ['left', 'right', 'feature', 'threshold', 'value']}
    for parts in zip(*(mdl[k] for k in out)):
        for k, a in zip(out, compact_tree(*parts)):
            out[k].append(a)
    out['classes'] = mdl['classes']
    return out


def truncate_depth(mdl, max_depth):
    """Turn every node at depth == max_depth into a leaf (in place). sklearn stores the class
    distribution of every node in 'value', so the new leaf predicts its majority class."""
    if max_depth is None:
        return mdl
    for left, right in zip(mdl['left'], mdl['right']):
        order, depth = reachable(left, right)
        cut = order[depth >= max_depth]
        left[cut] = -1
        right[cut] = -1
    return mdl
