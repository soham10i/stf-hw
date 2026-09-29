"""
A fleet of simulated machine-months for training (Upgrade 8).

Every machine is the Upgrade 7 cell run by month.py, but each has its own
starting wear, its own disturbances and its own random seed, and none gets
maintenance: they run to failure, are repaired, and run on. That is the data a
real operator would have after a year across a few cells - except here we
know every failure, so we can hide most of them (semi-supervised) and still
grade the model honestly on machines it never saw.

  X[i]       orders x FEATURES (month.FEATURES), one row per order
  fails[i]   (order index, component) of every failure on that machine
  rules[i]   (order index, component) of every U6 rule warning (the baseline)
"""
import random

import numpy as np

import month as M

COMPS = list(M.COMP)
DAYS = 45


def scenario(rnd):
    s = {}
    for k in COMPS:
        ev = []
        if rnd.random() < 0.3:
            ev.append((round(rnd.uniform(2, DAYS - 5), 1), round(rnd.uniform(1.5, 6.0), 2), "random disturbance"))
        s[k] = {"w0": round(rnd.uniform(0.0, 0.95), 3), "events": ev}
    return s


def machine(i):
    rnd = random.Random(1000 + i)
    m = M.Month(skip_pm=tuple(COMPS), scenario=scenario(rnd), seed=5000 + i, days=DAYS).run()
    idx = {o["t"]: n for n, o in enumerate(m.orders)}
    rules = []
    for e in m.events:
        if e["kind"] == "warning":
            n = next((j for j, o in enumerate(m.orders) if o["t"] >= e["t"] - 1e-9), len(m.orders) - 1)
            rules.append((n, e["comp"]))
    return np.array(m.feat, dtype=np.float32), m.fail_idx, rules


def build(n=80):
    X, F, R = [], [], []
    for i in range(n):
        x, f, r = machine(i)
        X.append(x)
        F.append(f)
        R.append(r)
    return X, F, R
