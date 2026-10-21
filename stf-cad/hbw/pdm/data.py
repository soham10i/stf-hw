"""
The fleet the pipeline is fitted and graded on: the same simulated machines as Upgrade 8
(ml/fleet.py) - Upgrade 7 cells with their own wear, disturbances and seeds, run to failure,
every failure logged - so the statistics here and the TCN there are graded on the same unseen
machines (64-79). Machines 0-15 fit the population: the normal-behaviour model, the noise
levels and the decision threshold. Generated once in parallel and cached (.cache/pdm_fleet.npz).
"""
import os
from multiprocessing import Pool

import numpy as np

CACHE = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".cache", "pdm_fleet.npz")
FIT = list(range(0, 16))       # population: fits, never graded
TEST = list(range(64, 80))     # the TCN's test machines (ml/train.py: 64 train, 16 test)


def _one(i):
    os.environ.setdefault("STF_VARIANT", "up7")
    from ml import fleet
    x, f, r = fleet.machine(i)
    return i, x, f, r


def load(ids=None):
    """{machine: (X orders x FEATURES, failures [(order, comp)], rule warnings [(order, comp)])}."""
    ids = sorted(set(ids or FIT + TEST))
    have = {}
    if os.path.exists(CACHE):
        z = np.load(CACHE, allow_pickle=True)
        have = z["fleet"].item()
    todo = [i for i in ids if i not in have]
    if todo:
        with Pool(min(len(todo), os.cpu_count() or 4)) as p:
            for i, x, f, r in p.imap_unordered(_one, todo):
                have[i] = (x, f, r)
                print(f"  machine {i}: {len(x)} orders, {len(f)} failures", flush=True)
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        np.savez_compressed(CACHE, fleet=np.array(have, dtype=object))
    return {i: have[i] for i in ids}
