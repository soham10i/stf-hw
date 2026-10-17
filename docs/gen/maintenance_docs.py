"""
The preventive-maintenance chapter (docs/maintenance/README.md): the mathematics of the health
model, the preventive policy and the service schedule, written from the code and the exports the
dashboard runs on - every equation with the line it is computed on, every number from the model:

  stf-cad/hbw/health.py            the wear law, noise, EWMA, health index, warnings (U6)
  stf-cad/hbw/health_theory.py     the closed forms and the false-alarm margins
  stf-cad/hbw/lifecycle.py         the maintenance plan and the spare parts (U7)
  web/public/hbw_parts_up12.json   health + lifecycle: what the dashboard reads
  web/public/health/theory.json    each part's law, noise and margins
  web/src/shared/health.ts         a part at a machine age, with or without preventive service
  web/src/dashboard/Maintenance.tsx  the service schedule

Equations are LaTeX ($...$ inline, $$...$$ display): the Docs page and the copilot render them.

    python3 docs/gen/maintenance_docs.py          (or `make maintenance-docs`)
"""

from __future__ import annotations

import json
import math
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "docs", "maintenance", "README.md")
EXPORT = "web/public/hbw_parts_up12.json"
THEORY = "web/public/health/theory.json"
HEALTH = "stf-cad/hbw/health.py"
THEORY_PY = "stf-cad/hbw/health_theory.py"
LIFE = "stf-cad/hbw/lifecycle.py"
AGE_TS = "web/src/shared/health.ts"
SCHED = "web/src/dashboard/Maintenance.tsx"
GEN = "docs/gen/maintenance_docs.py"
AGE = 140.0  # the dashboard's default machine age, shifts (the worked example)


def line(path: str, pattern: str) -> str:
    """`path:line` of the first line matching `pattern` - so the sources follow the code."""
    for i, text in enumerate(open(os.path.join(ROOT, path), encoding="utf-8"), 1):
        if re.search(pattern, text):
            return f"`{path}:{i}`"
    raise SystemExit(f"{GEN}: '{pattern}' is no longer in {path} - update the chapter")


def at(c: dict, shifts: float, pm: bool) -> dict:
    """A part at a machine age, as web/src/shared/health.ts compAt and tools._comp_at compute it."""
    n = shifts * c["per_shift"]
    k = 0
    if pm and c["warn"]:
        k = int(n // c["warn"])
        n -= k * c["warn"]
    p = next((pt for pt in c["curve"] if pt[0] >= n), c["curve"][-1])
    status = "fail" if n >= c["fail"] else "warn" if n >= c["warn"] else "ok"
    return {
        "n": n,
        "k": k,
        "hi": 0 if status == "fail" else p[2],
        "z": p[1],
        "status": status,
        "warn_in": (c["warn"] - n) / c["per_shift"],
        "fail_in": max(0.0, (c["fail"] - n) / c["per_shift"]),
    }


def num(x: float, d: int = 0) -> str:
    return f"{x:,.{d}f}"


def tex_commas(md: str) -> str:
    """Inside $...$ and $$...$$ a thousands comma is punctuation (TeX spaces after it): `{,}`."""
    fix = lambda m: re.sub(r"(?<=\d),(?=\d{3})", "{,}", m.group(0))  # noqa: E731
    return re.sub(r"\$\$.+?\$\$|\$[^$\n]+\$", fix, md, flags=re.S)


def main() -> None:
    doc = json.load(open(os.path.join(ROOT, EXPORT), encoding="utf-8"))
    th = json.load(open(os.path.join(ROOT, THEORY), encoding="utf-8"))
    health, life = doc["health"], doc["lifecycle"]
    rules, laws = th["rules"], {r["id"]: r for r in th["components"]}
    comps = health["components"]
    lam, s, W = rules["lambda"], rules["soft"], rules["window"]
    ops = health["orders_per_shift"]
    belt = next(c for c in comps if c["id"] == "belt")
    lb = laws["belt"]
    ex = at(belt, AGE, True)
    exo = at(belt, AGE, False)
    visit = next(p["every_shifts"] for p in life["plan"] if p["trigger"].startswith("detect-only"))
    spare = next(r for r in life["spares"] if r["item"] == f"wear: {belt['name']}")

    rows = []
    for c in comps:
        lw = laws[c["id"]]
        rows.append(
            f"| {c['name']} | {c['kind']} | {lw['p']:g} | {num(c['life'])} | {c['r_fail']:.3f} | "
            f"{lw['sigma'] * 100:.2f} % | {num(c['per_shift'], 1)} | {num(lw['n_soft_theory'])} | "
            f"{num(c['warn'])} | {c['lead_shifts']} | {num(c['pm_interval'])} ({c['pm_shifts']}) |"
        )
    margins = [
        f"| {c['name']} | {laws[c['id']]['soft_margin_sigma']} | {laws[c['id']]['trend_margin_sigma']} |"
        for c in comps
    ]
    spares = [
        f"| {r['item'].removeprefix('wear: ')} | {r['per_year']} | {r['stock']} |"
        for r in life["spares"]
        if r["wear"]
    ]

    md = f"""# Preventive maintenance: the mathematics

How the twin decides when a part needs service: what is measured, how wear is modelled, how the
noise is smoothed, how the health index and the remaining life are computed, when the two warnings
fire, how preventive service changes a part's state, and how the service schedule and the spare
parts follow from it. Every equation below is the one the code computes, with the line it is on;
every number comes from the health model the dashboard reads. Everything is simulated: the wear
laws and lives are assumptions, flagged as such in the model.

## Symbols

| Symbol | Meaning | Value |
|---|---|---|
| $n$ | uses of the part (cycles) since it was new | |
| $m$ | uses per shift: uses per order x orders per shift | orders per shift: {ops} |
| $L$ | the part's life in uses (assumed) | per part, table below |
| $p$ | the wear law's exponent | per part |
| $r_f$ | the signal at which the part fails | per part |
| $\\sigma$ | cycle-to-cycle noise of the signal | per part |
| $\\lambda$ | EWMA smoothing factor | {lam} |
| $s$ | soft limit: share of the margin used before a warning | {s} |
| $W$ | trend window, uses | {W} |
| $m_{{\\text{{rul}}}}$ | trend warning horizon | {rules["rul_warn_shifts"]:g} shifts |

A shift is {health["shift_h"]:g} h. The machine's age on the dashboard is in shifts; a part's
state is in uses, $n = A \\cdot m$ for a machine age of $A$ shifts.

## 1. The measured signal

Each part is watched through one signal the PLC already has: a step time (a cylinder's
reed-to-reed travel, the vacuum build-up, the belt's transit), a motor current, the compressor's
duty cycle, or the colour sensor's margin. It is divided by its healthy baseline $\\bar b$:

$$r_n = \\frac{{y_n}}{{\\bar b}}$$

so $r = 1$ is as new and $r > 1$ is worse. *Source: {line(HEALTH, r"def _baseline")}.*

## 2. The wear law

A part wears along a power law in its uses:

$$r(n) = 1 + (r_f - 1)\\left(\\frac{{n}}{{L}}\\right)^{{p}}$$

$p = 1$ is linear wear (abrasion), $p > 1$ accelerates (fatigue, a seal hardening), and a large $p$
(the gearbox's $p = 10$) is sudden onset. The part fails at $r(n) = r_f$, that is at $n = L$.
*Source: {line(HEALTH, r"wear = \(r_fail - 1\)")}.*

## 3. Where it fails

For a step time, the part fails when its tightest step reaches the PLC's watchdog $W_k$ on that
step (the line then stops with an alarm):

$$r_f = \\min_k \\frac{{W_k}}{{b_k}}$$

For the spindle it is the electronic breaker's trip ({health["rules"]["ecb_trip"]} x the nominal
current); for the air supply, a compressor duty of 1 (healthy duty
{health["air_duty0"]}); for the colour sensor, $r_f = 2$: the first flavour's reading crossing into
its neighbour's band. *Source: {line(HEALTH, r"r_fail = min\(lim / b")}.*

## 4. The noise

What the PLC reads is the wear times a random spread:

$$y_n = r(n)\\,(1 + \\varepsilon_n), \\qquad \\varepsilon_n \\sim \\mathcal{{N}}(0, \\sigma^2), \\qquad
\\sigma^2 = \\sigma_p^2 + \\frac{{(\\Delta / \\bar b)^2}}{{12}}$$

$\\sigma_p = {health["rules"]["noise"]}$ is the assumed 2 % cycle-to-cycle spread of a physical
step, and the second term is the PLC scan's quantisation (scan time $\\Delta$: a uniform error of
one scan has variance $\\Delta^2/12$). *Source: {line(HEALTH, r"sig = math.sqrt\(NOISE")},
{line(HEALTH, r"obs = r_true")}.*

## 5. Smoothing: the EWMA

One reading is too noisy to act on. The exponentially weighted moving average moves a step
$\\lambda$ towards each new reading:

$$z_n = z_{{n-1}} + \\lambda\\,(y_n - z_{{n-1}}), \\qquad z_0 = y_0$$

On a healthy machine its spread is

$$\\sigma_z = \\sigma\\sqrt{{\\frac{{\\lambda}}{{2 - \\lambda}}}}$$

which for $\\lambda = {lam}$ is a tenth of $\\sigma$; the price is a lag: a ramp is followed
$(1 - \\lambda)/\\lambda = {rules["ewma_lag"]:g}$ uses late. *Source: {line(HEALTH, r"ew = obs if n == 0")},
{line(THEORY_PY, r"sig_z = sig")}.*

## 6. The health index

The share of the margin to failure that is left:

$$\\mathrm{{HI}}_n = 100 \\cdot \\operatorname{{clip}}\\!\\left(\\frac{{r_f - z_n}}{{r_f - 1}},\\ 0,\\ 1\\right)$$

100 = as new, 0 = failing now. A part that has failed shows 0. *Source:
{line(HEALTH, r"hi = max\(0.0, min")}.*

## 7. Warning 1: the soft limit

Warn when the share $s = {s}$ of the margin is used (half of it):

$$z_n \\ge 1 + s\\,(r_f - 1)$$

For the belt: $z_n \\ge 1 + {s} \\times ({belt["r_fail"]} - 1) = {belt["soft"]}$. ($s$ is a share of the
margin, not the EWMA's lag of {rules["ewma_lag"]:g} uses.)

Solving the wear law for it and adding the EWMA's lag gives where it fires:

$$n_s \\approx L\\, s^{{1/p}} + \\frac{{1-\\lambda}}{{\\lambda}}$$

The simulation agrees with this closed form within 1 % for every part (checked by
`health_theory.py`). *Source: {line(HEALTH, r"soft = 1 \+ SOFT")}, {line(THEORY_PY, r"n_soft = L")}.*

## 8. Warning 2: the trend (remaining useful life)

The slope of the smoothed signal over the last $W$ uses, extrapolated to the failure limit:

$$\\hat\\beta_n = \\frac{{z_n - z_{{n-W}}}}{{W}}, \\qquad
\\widehat{{\\mathrm{{RUL}}}}_n = \\frac{{r_f - z_n}}{{\\hat\\beta_n}}$$

over the window $W = {W}$ uses, and warn when fewer than {rules["rul_warn_shifts"]:g} shifts of
uses are left:
$\\widehat{{\\mathrm{{RUL}}}}_n < {rules["rul_warn_shifts"]:g}\\,m$. This catches sudden onset
(large $p$) before the soft limit does. *Source: {line(HEALTH, r"slope = \(y1 - y0\)")},
{line(HEALTH, r"rul = \(r_fail - y1\)")}.*

## 9. No false alarms

A healthy machine must never warn. Its distance to each warning, in standard deviations:

$$\\frac{{s\\,(r_f - 1)}}{{\\sigma_z}} \\qquad\\text{{and}}\\qquad
\\frac{{\\beta^*}}{{\\sigma_\\beta}}, \\quad \\beta^* = \\frac{{r_f - 1}}{{3m}}, \\quad
\\sigma_\\beta = \\frac{{\\sqrt 2\\,\\sigma_z}}{{W}}$$

The model requires at least 6 for both, and runs {num(rules["healthy_cycles"])} healthy uses per
part to confirm no warning comes. *Source: {line(THEORY_PY, r"sig_beta = math.sqrt")}.*

| Part | Soft-limit margin ($\\sigma$) | Trend margin ($\\sigma$) |
|---|---|---|
{chr(10).join(margins)}

## 10. Lead time

Every warning must leave at least one shift to renew the part:

$$\\Delta_{{\\text{{lead}}}} = \\frac{{T_f - n_{{\\text{{warn}}}}}}{{m}} \\ \\ge\\ 1\\ \\text{{shift}}$$

*Source: {line(HEALTH, r"lead_sh = None if lead")}.*

## Every part

| Part | Signal | $p$ | $L$ (uses) | $r_f$ | $\\sigma$ | $m$ (uses/shift) | $n_s$ theory | Warns at (sim) | Lead (shifts) | Preventive interval (uses, shifts) |
|---|---|---|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

*Source: `{EXPORT}` (health), `{THEORY}`.*

## The preventive policy

Two triggers renew a wear part, whichever comes first:

- **Predictive**: its warning (soft limit or trend) fires.
- **Preventive interval**: $0.7\\,L$ uses, $\\frac{{0.7\\,L}}{{m}}$ shifts
  ({line(HEALTH, r'"pm_interval": int\(0.7')}).

Failures with no gradual precursor (a reed switch that breaks, a dirty light barrier, a broken
encoder cable) cannot be predicted: a PM visit every {visit:g} shifts tests and cleans them
({line(LIFE, r'"every_shifts": 40.0')}).

### A part at a machine age

The dashboard (Health, Maintenance) and the copilot's `machine_health` tool place each part at
the machine age $A$ the same way. With preventive maintenance on, the part is renewed each time
its warning comes, so after $k$ renewals it is $n'$ uses into its current life:

$$n = A\\,m, \\qquad k = \\left\\lfloor \\frac{{n}}{{n_{{\\text{{warn}}}}}} \\right\\rfloor, \\qquad
n' = n - k\\,n_{{\\text{{warn}}}}$$

With it off, $k = 0$ and $n' = n$. Then

$$\\text{{status}} = \\begin{{cases}} \\text{{failed}} & n' \\ge T_f \\\\ \\text{{service due}} & n' \\ge
n_{{\\text{{warn}}}} \\\\ \\text{{healthy}} & \\text{{otherwise}} \\end{{cases}} \\qquad
\\text{{warns in}} = \\frac{{n_{{\\text{{warn}}}} - n'}}{{m}}, \\qquad
\\text{{fails in}} = \\max\\!\\left(0, \\frac{{T_f - n'}}{{m}}\\right)$$

and the health index is read from the part's simulated curve at $n'$. *Source:
{line(AGE_TS, r"serviced = Math.floor")}, {line("services/api/tools.py", r"serviced = int\(n // warn\)")}.*

### Worked example: the HBW belt at {AGE:g} shifts

The belt runs {belt["per_order"]} uses per order, so
$m = {belt["per_order"]} \\times {ops} \\approx {num(belt["per_shift"], 1)}$ uses per shift. Its law:
$p = {lb["p"]:g}$, $L = {num(belt["life"])}$, $r_f = {belt["r_fail"]}$, and the simulation warns at
$n_{{\\text{{warn}}}} = {num(belt["warn"])}$ (by the {belt["warn_by"]}; the closed form gives
$L\\,s^{{1/p}} + {rules["ewma_lag"]:g} = {num(lb["n_soft_theory"])}$).

$$n = {AGE:g} \\times {belt["per_shift"]} = {num(AGE * belt["per_shift"])}, \\qquad
k = \\left\\lfloor \\frac{{{num(AGE * belt["per_shift"])}}}{{{num(belt["warn"])}}} \\right\\rfloor = {ex["k"]}, \\qquad
n' = {num(ex["n"])}$$

$$\\text{{warns in}} = \\frac{{{num(belt["warn"])} - {num(ex["n"])}}}{{{belt["per_shift"]}}} = {ex["warn_in"]:.1f}\\ \\text{{shifts}},
\\qquad \\mathrm{{HI}} = {ex["hi"]:g}$$

So with preventive maintenance on, the belt has been renewed {ex["k"]} times and its next warning
is {ex["warn_in"]:.1f} shifts away: this is the dashboard's "Next: HBW belt warns in
{ex["warn_in"]:.1f} shifts". With it off, the same belt is {num(exo["n"])} uses old, past its
life of {num(belt["life"])}: **{ {"fail": "failed", "warn": "service due", "ok": "healthy"}[exo["status"]] }**.

### The service schedule

The Maintenance page plans the next 90 shifts. For a healthy part the first service is due at the
earlier of its preventive interval and its remaining life, then every interval after it:

$$t_{{\\text{{due}}}} = \\max\\!\\left(0,\\ \\min\\!\\left(\\frac{{0.7\\,L - n'}}{{m}},\\ \\text{{fails in}}\\right)\\right),
\\qquad t_j = t_{{\\text{{due}}}} + j\\,\\frac{{0.7\\,L}}{{m}}$$

A part that is warned or failed is due now ($t_{{\\text{{due}}}} = 0$). *Source:
{line(SCHED, r"const due = kind")}.*

For the belt at {AGE:g} shifts: $\\frac{{0.7\\,L - n'}}{{m}} = \\frac{{{num(belt["pm_interval"])} - {num(ex["n"])}}}{{{belt["per_shift"]}}}
= {(belt["pm_interval"] - ex["n"]) / belt["per_shift"]:.2f}$ shifts, then every {belt["pm_shifts"]} shifts.

## Spare parts

Wear parts used per year at two shifts a day, 250 days:

$$\\text{{per year}} = \\frac{{m \\cdot 500}}{{L}}, \\qquad
\\text{{stock}} = \\max\\!\\left(1,\\ \\left\\lceil \\frac{{2\\cdot\\text{{per year}}}}{{52}} \\right\\rceil + 1\\right)$$

(two weeks of use, plus one). For the belt:
$\\frac{{{belt["per_shift"]} \\times 500}}{{{num(belt["life"])}}} = {spare["per_year"]}$ per year,
stock {spare["stock"]}. *Source: {line(LIFE, r"per_year = h\[")}.*

| Wear part | Used per year | Stock |
|---|---|---|
{chr(10).join(spares)}

## Limits

- The wear laws, the lives $L$, the 2 % noise, the breaker trip and the air figures are
  assumptions; the model flags them. With a real machine they are fitted from its own history.
- The age model renews a part at its warning; the schedule also shows the preventive interval
  $0.7\\,L$, which for a part whose warning comes later than $0.7\\,L$ is the earlier of the two.
- Failures without a gradual precursor are only covered by the PM visit and the PLC's watchdogs.

## References

- ISO 13374-1:2003, condition monitoring and diagnostics of machines: data processing.
- Lu, C.J., Meeker, W.Q. (1993). Using degradation measures to estimate a time-to-failure
  distribution. Technometrics 35(2). [doi:10.1080/00401706.1993.10485038](https://doi.org/10.1080/00401706.1993.10485038)
- Lucas, J.M., Saccucci, M.S. (1990). Exponentially weighted moving average control schemes.
  Technometrics 32(1). [doi:10.1080/00401706.1990.10484583](https://doi.org/10.1080/00401706.1990.10484583)
- Si, X.-S. et al. (2011). Remaining useful life estimation: a review on the statistical data
  driven approaches. EJOR 213(1). [doi:10.1016/j.ejor.2010.11.018](https://doi.org/10.1016/j.ejor.2010.11.018)
- Saxena, A. et al. (2008). Metrics for evaluating performance of prognostic techniques. PHM 2008.
  [doi:10.1109/PHM.2008.4711436](https://doi.org/10.1109/PHM.2008.4711436)

The same model runs live in the dashboard: **Docs > Hardware degradation**.

*Generated by `{GEN}` from `{EXPORT}` and `{THEORY}`; edit the generator, not this file.*
"""
    assert math.isfinite(ex["warn_in"])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(tex_commas(md))
    print(
        f"wrote {os.path.relpath(OUT, ROOT)}: belt at {AGE:g} shifts warns in {ex['warn_in']:.1f}"
    )


if __name__ == "__main__":
    main()
