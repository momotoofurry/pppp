"""Check for decision_robot_map.py.

1. hold_runs() on hand-made votes with known answers: the run starts moving at k, a rejected window and a new trial
   reset it, another class stops it.
2. The discrete part equals decision_home_rate.py on the same recorded votes: per model and gesture, first_<gesture>
   in results/decision_robot_map_discrete.csv equals 'correct' in results/decision_home_rate.csv.
Usage (in the container, after decision_robot_map.py): PYTHONPATH=src python src/check_decision_robot_map.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_decision as E  # noqa: E402
import decision_robot_map as R  # noqa: E402


def votes(seq):
    """seq: class index, or None for a rejected window (top share 0.2 < tau)."""
    v = np.zeros((len(seq), 6), np.uint16)
    for i, c in enumerate(seq):
        if c is None:
            v[i] = [20, 20, 20, 20, 10, 10]
        else:
            v[i, c] = E.TREES
    return v


def main():
    P, T = R.P, R.T
    got = R.hold_runs(votes([P] * 5 + [None] + [P] * 3 + [T] * 4), np.zeros(13, np.int32))
    assert list(got) == [-1, -1, P, P, P, -1, -1, -1, P, -1, -1, T, T], got
    got = R.hold_runs(votes([P] * 6), np.array([0, 0, 0, 1, 1, 1], np.int32))
    assert list(got) == [-1, -1, P, -1, -1, P], got
    disc = pd.read_csv(os.path.join(E.OUT, 'decision_robot_map_discrete.csv'))
    home = pd.read_csv(os.path.join(E.OUT, 'decision_home_rate.csv')).dropna(subset=['correct'])
    for _, r in home.iterrows():
        row = disc[(disc.votes == r.votes) & (disc.true == r.gesture)].iloc[0]
        assert abs(row['first_' + r.gesture] - r.correct) < 0.05, (r.votes, r.gesture)
    print(f'hold_runs: 2 hand-made cases ok; discrete part equals decision_home_rate.csv on {len(home)} rows')


if __name__ == '__main__':
    main()
