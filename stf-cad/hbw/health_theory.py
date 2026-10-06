"""
The theory behind Upgrade 6's health model, as numbers the dashboard's docs page can show.

    STF_VARIANT=up12 python3 health_theory.py        (from stf-cad/hbw; or `make health-theory`)

health.py simulates each part cycle by cycle. This module writes down what that simulation
should give in closed form, and checks the two agree:
  WEAR      r(n) = 1 + (r_f - 1) (n / L)^p crosses the soft limit at n_s = L s^(1/p) and
            fails at n = L
  EWMA      a ramp is followed with a lag of (1 - lambda) / lambda cycles; the steady-state
            spread of a healthy machine is sigma sqrt(lambda / (2 - lambda))
  FALSE     how many of those spreads separate a healthy machine from each warning: the
            soft limit and the trend (slope) warning
Writes web/public/health/theory.json: every part's law, noise and limits (what the browser's
live simulation runs) and the checks.
"""
import json
import math
import os

import health as H

OUT = os.path.join(os.path.dirname(__file__), "..", "..", "web", "public", "health", "theory.json")


def params(c):
    """(r_fail, sigma) exactly as health.simulate derives them."""
    if c["kind"] in ("time", "current"):
        r_fail, _, sig = H._baseline(H._steps(c["steps"]))
        if c["kind"] == "current":
            r_fail = H.ECB_TRIP
    elif c["kind"] == "duty":
        r_fail, sig = 1.0 / H.air_duty0(), 0.03
    else:
        r_fail, sig = 2.0, 5.0 / H.colour_margin()
    return r_fail, sig


def main():
    lam, s, W = H.EWMA, H.SOFT, H.WINDOW
    lag = (1 - lam) / lam
    rows, fails = [], []
    for c, sim in zip(H.components(), H.run()):
        r_f, sig = params(c)
        L, p = c["life"], c["p"]
        sig_z = sig * math.sqrt(lam / (2 - lam))                 # steady-state EWMA spread
        n_soft = L * s ** (1 / p) + lag                          # the EWMA reaches the soft limit
        rul_warn = H.RUL_WARN_SHIFTS * sim["per_shift"]
        # the trend warning on a healthy machine: slope from two EWMA values W apart
        sig_beta = math.sqrt(2) * sig_z / W
        beta_star = (r_f - 1) / rul_warn                         # slope that predicts < 3 shifts
        row = {"id": c["id"], "p": p, "life": L, "r_fail": round(r_f, 4), "sigma": round(sig, 5),
               "per_shift": sim["per_shift"], "rul_warn": round(rul_warn),
               "sigma_z": round(sig_z, 6), "soft_margin_sigma": round(s * (r_f - 1) / sig_z, 1),
               "trend_margin_sigma": round(beta_star / sig_beta, 1),
               "n_soft_theory": round(n_soft), "warn_sim": sim["warn"], "warn_by": sim["warn_by"],
               "fail_sim": sim["fail"], "lead_shifts": sim["lead_shifts"]}
        rows.append(row)
        # the simulation may warn earlier (the trend warning) but never later than the soft limit
        if sim["warn"] is None or sim["warn"] > n_soft * 1.01:
            fails.append(f"{c['id']}: warned at {sim['warn']}, the soft limit predicts {n_soft:.0f}")
        if sim["fail"] is not None and abs(sim["fail"] - L) > 1:
            fails.append(f"{c['id']}: failed at {sim['fail']}, the wear law predicts {L}")
        if min(row["soft_margin_sigma"], row["trend_margin_sigma"]) < 6:
            fails.append(f"{c['id']}: a healthy machine is within 6 sigma of a warning")
    out = {"rules": {"lambda": lam, "soft": s, "window": W, "rul_warn_shifts": H.RUL_WARN_SHIFTS,
                     "ewma_lag": round(lag, 1), "healthy_cycles": H.HEALTHY_CYCLES},
           "components": rows, "fails": fails}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    for r in rows:
        print(f"  {r['id']:8s} p {r['p']:<4} soft at {r['n_soft_theory']:>7} (sim warns {r['warn_sim']}, {r['warn_by']})"
              f"  false-alarm margin {r['soft_margin_sigma']} / {r['trend_margin_sigma']} sigma")
    print("\n".join(fails) if fails else "THEORY OK (closed form agrees with the simulation)")
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(1 if main() else 0)
