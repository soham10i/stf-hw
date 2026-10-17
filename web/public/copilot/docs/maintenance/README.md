# Preventive maintenance: the mathematics

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
| $m$ | uses per shift: uses per order x orders per shift | orders per shift: 67.0 |
| $L$ | the part's life in uses (assumed) | per part, table below |
| $p$ | the wear law's exponent | per part |
| $r_f$ | the signal at which the part fails | per part |
| $\sigma$ | cycle-to-cycle noise of the signal | per part |
| $\lambda$ | EWMA smoothing factor | 0.02 |
| $s$ | soft limit: share of the margin used before a warning | 0.5 |
| $W$ | trend window, uses | 400 |
| $m_{\text{rul}}$ | trend warning horizon | 3 shifts |

A shift is 8 h. The machine's age on the dashboard is in shifts; a part's
state is in uses, $n = A \cdot m$ for a machine age of $A$ shifts.

## 1. The measured signal

Each part is watched through one signal the PLC already has: a step time (a cylinder's
reed-to-reed travel, the vacuum build-up, the belt's transit), a motor current, the compressor's
duty cycle, or the colour sensor's margin. It is divided by its healthy baseline $\bar b$:

$$r_n = \frac{y_n}{\bar b}$$

so $r = 1$ is as new and $r > 1$ is worse. *Source: `stf-cad/hbw/health.py:68`.*

## 2. The wear law

A part wears along a power law in its uses:

$$r(n) = 1 + (r_f - 1)\left(\frac{n}{L}\right)^{p}$$

$p = 1$ is linear wear (abrasion), $p > 1$ accelerates (fatigue, a seal hardening), and a large $p$
(the gearbox's $p = 10$) is sudden onset. The part fails at $r(n) = r_f$, that is at $n = L$.
*Source: `stf-cad/hbw/health.py:175`.*

## 3. Where it fails

For a step time, the part fails when its tightest step reaches the PLC's watchdog $W_k$ on that
step (the line then stops with an alarm):

$$r_f = \min_k \frac{W_k}{b_k}$$

For the spindle it is the electronic breaker's trip (1.5 x the nominal
current); for the air supply, a compressor duty of 1 (healthy duty
0.094); for the colour sensor, $r_f = 2$: the first flavour's reading crossing into
its neighbour's band. *Source: `stf-cad/hbw/health.py:72`.*

## 4. The noise

What the PLC reads is the wear times a random spread:

$$y_n = r(n)\,(1 + \varepsilon_n), \qquad \varepsilon_n \sim \mathcal{N}(0, \sigma^2), \qquad
\sigma^2 = \sigma_p^2 + \frac{(\Delta / \bar b)^2}{12}$$

$\sigma_p = 0.02$ is the assumed 2 % cycle-to-cycle spread of a physical
step, and the second term is the PLC scan's quantisation (scan time $\Delta$: a uniform error of
one scan has variance $\Delta^2/12$). *Source: `stf-cad/hbw/health.py:75`,
`stf-cad/hbw/health.py:177`.*

## 5. Smoothing: the EWMA

One reading is too noisy to act on. The exponentially weighted moving average moves a step
$\lambda$ towards each new reading:

$$z_n = z_{n-1} + \lambda\,(y_n - z_{n-1}), \qquad z_0 = y_0$$

On a healthy machine its spread is

$$\sigma_z = \sigma\sqrt{\frac{\lambda}{2 - \lambda}}$$

which for $\lambda = 0.02$ is a tenth of $\sigma$; the price is a lag: a ramp is followed
$(1 - \lambda)/\lambda = 49$ uses late. *Source: `stf-cad/hbw/health.py:178`,
`stf-cad/hbw/health_theory.py:46`.*

## 6. The health index

The share of the margin to failure that is left:

$$\mathrm{HI}_n = 100 \cdot \operatorname{clip}\!\left(\frac{r_f - z_n}{r_f - 1},\ 0,\ 1\right)$$

100 = as new, 0 = failing now. A part that has failed shows 0. *Source:
`stf-cad/hbw/health.py:190`.*

## 7. Warning 1: the soft limit

Warn when the share $s = 0.5$ of the margin is used (half of it):

$$z_n \ge 1 + s\,(r_f - 1)$$

For the belt: $z_n \ge 1 + 0.5 \times (1.535 - 1) = 1.267$. ($s$ is a share of the
margin, not the EWMA's lag of 49 uses.)

Solving the wear law for it and adding the EWMA's lag gives where it fires:

$$n_s \approx L\, s^{1/p} + \frac{1-\lambda}{\lambda}$$

The simulation agrees with this closed form within 1 % for every part (checked by
`health_theory.py`). *Source: `stf-cad/hbw/health.py:170`, `stf-cad/hbw/health_theory.py:47`.*

## 8. Warning 2: the trend (remaining useful life)

The slope of the smoothed signal over the last $W$ uses, extrapolated to the failure limit:

$$\hat\beta_n = \frac{z_n - z_{n-W}}{W}, \qquad
\widehat{\mathrm{RUL}}_n = \frac{r_f - z_n}{\hat\beta_n}$$

over the window $W = 400$ uses, and warn when fewer than 3 shifts of
uses are left:
$\widehat{\mathrm{RUL}}_n < 3\,m$. This catches sudden onset
(large $p$) before the soft limit does. *Source: `stf-cad/hbw/health.py:183`,
`stf-cad/hbw/health.py:184`.*

## 9. No false alarms

A healthy machine must never warn. Its distance to each warning, in standard deviations:

$$\frac{s\,(r_f - 1)}{\sigma_z} \qquad\text{and}\qquad
\frac{\beta^*}{\sigma_\beta}, \quad \beta^* = \frac{r_f - 1}{3m}, \quad
\sigma_\beta = \frac{\sqrt 2\,\sigma_z}{W}$$

The model requires at least 6 for both, and runs 60,000 healthy uses per
part to confirm no warning comes. *Source: `stf-cad/hbw/health_theory.py:50`.*

| Part | Soft-limit margin ($\sigma$) | Trend margin ($\sigma$) |
|---|---|---|
| VGR suction cup seal | 519.8 | 121.9 |
| oven door cylinder | 352.5 | 27.6 |
| Sauger lowering cylinder | 430.2 | 33.6 |
| Auswerfer cylinder | 430.2 | 67.3 |
| HBW belt | 133.0 | 20.8 |
| RFID read heads | 940.2 | 147.0 |
| HBW travel spindle + nut | 124.1 | 12.5 |
| VGR swivel gearbox (sudden-onset wear) | 147.4 | 8.6 |
| air supply (leaks) | 1600.4 | 4504.2 |
| colour sensor A4 (LED ageing) | 303.5 | 94.9 |

## 10. Lead time

Every warning must leave at least one shift to renew the part:

$$\Delta_{\text{lead}} = \frac{T_f - n_{\text{warn}}}{m} \ \ge\ 1\ \text{shift}$$

*Source: `stf-cad/hbw/health.py:204`.*

## Every part

| Part | Signal | $p$ | $L$ (uses) | $r_f$ | $\sigma$ | $m$ (uses/shift) | $n_s$ theory | Warns at (sim) | Lead (shifts) | Preventive interval (uses, shifts) |
|---|---|---|---|---|---|---|---|---|---|---|
| VGR suction cup seal | time | 3 | 150,000 | 3.243 | 2.15 % | 804.1 | 119,104 | 118,880 | 38.7 | 105,000 (130.6) |
| oven door cylinder | time | 2 | 400,000 | 2.439 | 2.03 % | 2,412.3 | 282,892 | 281,838 | 49.0 | 280,000 (116.1) |
| Sauger lowering cylinder | time | 2 | 400,000 | 2.800 | 2.08 % | 2,412.3 | 282,892 | 281,840 | 49.0 | 280,000 (116.1) |
| Auswerfer cylinder | time | 2 | 400,000 | 2.800 | 2.08 % | 1,206.1 | 282,892 | 281,840 | 98.0 | 280,000 (232.2) |
| HBW belt | time | 2 | 60,000 | 1.535 | 2.00 % | 1,206.1 | 42,475 | 42,401 | 14.6 | 42,000 (34.8) |
| RFID read heads | time | 4 | 500,000 | 6.429 | 2.87 % | 1,206.1 | 420,497 | 419,789 | 66.5 | 350,000 (290.2) |
| HBW travel spindle + nut | current | 2 | 300,000 | 1.500 | 2.00 % | 1,876.2 | 212,181 | 210,585 | 47.7 | 210,000 (111.9) |
| VGR swivel gearbox (sudden-onset wear) | time | 10 | 200,000 | 1.594 | 2.01 % | 3,216.4 | 186,656 | 182,800 | 5.3 | 140,000 (43.5) |
| air supply (leaks) | duty | 1.5 | 2,000 | 10.651 | 3.00 % | 67.0 | 1,309 | 1,307 | 10.3 | 1,400 (20.9) |
| colour sensor A4 (LED ageing) | margin | 1 | 40,000 | 2.000 | 1.64 % | 603.1 | 20,049 | 19,843 | 33.4 | 28,000 (46.4) |

*Source: `web/public/hbw_parts_up12.json` (health), `web/public/health/theory.json`.*

## The preventive policy

Two triggers renew a wear part, whichever comes first:

- **Predictive**: its warning (soft limit or trend) fires.
- **Preventive interval**: $0.7\,L$ uses, $\frac{0.7\,L}{m}$ shifts
  (`stf-cad/hbw/health.py:213`).

Failures with no gradual precursor (a reed switch that breaks, a dirty light barrier, a broken
encoder cable) cannot be predicted: a PM visit every 40 shifts tests and cleans them
(`stf-cad/hbw/lifecycle.py:203`).

### A part at a machine age

The dashboard (Health, Maintenance) and the copilot's `machine_health` tool place each part at
the machine age $A$ the same way. With preventive maintenance on, the part is renewed each time
its warning comes, so after $k$ renewals it is $n'$ uses into its current life:

$$n = A\,m, \qquad k = \left\lfloor \frac{n}{n_{\text{warn}}} \right\rfloor, \qquad
n' = n - k\,n_{\text{warn}}$$

With it off, $k = 0$ and $n' = n$. Then

$$\text{status} = \begin{cases} \text{failed} & n' \ge T_f \\ \text{service due} & n' \ge
n_{\text{warn}} \\ \text{healthy} & \text{otherwise} \end{cases} \qquad
\text{warns in} = \frac{n_{\text{warn}} - n'}{m}, \qquad
\text{fails in} = \max\!\left(0, \frac{T_f - n'}{m}\right)$$

and the health index is read from the part's simulated curve at $n'$. *Source:
`web/src/shared/health.ts:15`, `services/api/tools.py:107`.*

### Worked example: the HBW belt at 140 shifts

The belt runs 18 uses per order, so
$m = 18 \times 67.0 \approx 1{,}206.1$ uses per shift. Its law:
$p = 2$, $L = 60{,}000$, $r_f = 1.535$, and the simulation warns at
$n_{\text{warn}} = 42{,}401$ (by the soft limit; the closed form gives
$L\,s^{1/p} + 49 = 42{,}475$).

$$n = 140 \times 1206.1 = 168{,}854, \qquad
k = \left\lfloor \frac{168{,}854}{42{,}401} \right\rfloor = 3, \qquad
n' = 41{,}651$$

$$\text{warns in} = \frac{42{,}401 - 41{,}651}{1206.1} = 0.6\ \text{shifts},
\qquad \mathrm{HI} = 51.7$$

So with preventive maintenance on, the belt has been renewed 3 times and its next warning
is 0.6 shifts away: this is the dashboard's "Next: HBW belt warns in
0.6 shifts". With it off, the same belt is 168,854 uses old, past its
life of 60,000: **failed**.

### The service schedule

The Maintenance page plans the next 90 shifts. For a healthy part the first service is due at the
earlier of its preventive interval and its remaining life, then every interval after it:

$$t_{\text{due}} = \max\!\left(0,\ \min\!\left(\frac{0.7\,L - n'}{m},\ \text{fails in}\right)\right),
\qquad t_j = t_{\text{due}} + j\,\frac{0.7\,L}{m}$$

A part that is warned or failed is due now ($t_{\text{due}} = 0$). *Source:
`web/src/dashboard/Maintenance.tsx:31`.*

For the belt at 140 shifts: $\frac{0.7\,L - n'}{m} = \frac{42,000 - 41,651}{1206.1}
= 0.29$ shifts, then every 34.8 shifts.

## Spare parts

Wear parts used per year at two shifts a day, 250 days:

$$\text{per year} = \frac{m \cdot 500}{L}, \qquad
\text{stock} = \max\!\left(1,\ \left\lceil \frac{2\cdot\text{per year}}{52} \right\rceil + 1\right)$$

(two weeks of use, plus one). For the belt:
$\frac{1206.1 \times 500}{60{,}000} = 10.05$ per year,
stock 2. *Source: `stf-cad/hbw/lifecycle.py:189`.*

| Wear part | Used per year | Stock |
|---|---|---|
| VGR suction cup seal | 2.68 | 2 |
| oven door cylinder | 3.02 | 2 |
| Sauger lowering cylinder | 3.02 | 2 |
| Auswerfer cylinder | 1.51 | 2 |
| HBW belt | 10.05 | 2 |
| HBW travel spindle + nut | 3.13 | 2 |
| VGR swivel gearbox (sudden-onset wear) | 8.04 | 2 |

## Limits

- The wear laws, the lives $L$, the 2 % noise, the breaker trip and the air figures are
  assumptions; the model flags them. With a real machine they are fitted from its own history.
- The age model renews a part at its warning; the schedule also shows the preventive interval
  $0.7\,L$, which for a part whose warning comes later than $0.7\,L$ is the earlier of the two.
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

*Generated by `docs/gen/maintenance_docs.py` from `web/public/hbw_parts_up12.json` and `web/public/health/theory.json`; edit the generator, not this file.*
