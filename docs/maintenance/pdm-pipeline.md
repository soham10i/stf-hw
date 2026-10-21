# Predictive maintenance: the pre-failure window

How the twin finds the stretch before a part fails in which it can still be serviced in a planned
stop - and how sure it is. The pipeline lives in `stf-cad/hbw/pdm/` and runs with `make pdm`; the
dashboard shows it under **Maintenance → Pre-failure window**. It sits between the two earlier
layers: the rule monitor of [the mathematics](README.md) (EWMA, soft limit, trend) and the
semi-supervised temporal CNN of Upgrade 8 (`ml/`).

The approach is the one industrial condition monitoring uses where the stakes are high (wind
turbines, gas turbines, rail): model what each signal does when the machine is healthy, watch the
residual with statistical control charts, track the degradation with a physics-based state-space
model, give the remaining life as a probability distribution, and decide on cost and risk rather
than on a fixed limit.

## The pipeline

```
 per-order signals (r per component, hall temperature)
        │
 1  normal-behaviour model ── divides out the hall temperature (fitted on the fleet)
        │
 2  physics-informed health state ── w = share of the part's life used, from its own wear law
        │
 3  constrained iterated extended Kalman filter ── state [w, wear rate]; innovations e_t
        │                                   │
 4  remaining life as a distribution        5  change detection on e_t
    first passage of w to 1                    CUSUM (wear faster than normal)
    P10 / P50 / P90, P(fail ≤ H)               BOCPD (when it began)
        │                                      Hotelling T² (across all parts)
 6  decision: open the pre-failure window when P(fail within 2 shifts) ≥ p*
        │
    work order into the next night gap
```

### 1  Normal-behaviour model

Some signals move with the hall temperature, not with wear: a warm belt slips more, a warm manifold
leaks more. Before anything else that effect is removed:

$$r_c = r_{obs} \,/\, e^{\beta\,(T - 21\,^\circ\mathrm{C})}$$

$\beta$ is fitted per component on the population machines by regressing $\log r$ on $T$, both
taken relative to their own slow trend (a 61-order rolling median), so that wear cannot pass for a
temperature effect. It finds $\beta = 0.0040$ per °C for the belt - the simulation's true value -
and $0.0034$ for the air system; zero for the parts temperature does not touch.

### 2  A physics-informed health state

Every part wears along its own law (`health.py`): $r = 1 + (r_f - 1)\,w^{p}$, where $w$ is the
share of its life used. So the state worth tracking is $w$ itself: linear in use, and the part
fails at exactly $w = 1$. A nonlinear signal becomes a linear degradation path whose failure
threshold is known - no threshold has to be learned from failures.

### 3  The filter

A local-linear-trend state $x = [w, \dot w]$ per order, the wear rate a slow random walk (a
disturbance changes it); the measurement is the part's own law with multiplicative noise:

$$w_{t+1} = w_t + \dot w_t, \qquad \dot w_{t+1} = \dot w_t + \eta_t, \qquad
r_t = 1 + (r_f - 1)\,w_t^{\,p}\,(1 + \varepsilon_t)$$

- **Iterated EKF**: the update is relinearised where the state lands (Gauss-Newton), which a steep
  law needs (the gearbox: $p = 10$).
- **Constrained**: after every update $0 \le w \le 1.2$ and $\dot w \ge 0$. Without it a steep law
  pushed the estimate below zero, where the law is flat and the filter never recovered (it missed
  the gearbox failure entirely, with 150-sigma innovations).
- **Where the law is flat** (a sudden-onset part early in life) the measurement carries no
  information, and the filter says so: its uncertainty stays wide.
- **Noise calibrated from the data** (innovation-based adaptive estimation): each component's
  noise is scaled until its standardised innovations have unit spread on the population.

### 4  Remaining life as a distribution

For a Wiener process with drift $\mu$ and diffusion $\sigma_d$, the first passage from $w$ to 1 is
inverse Gaussian:

$$T \sim \mathrm{IG}\!\left(\frac{1 - w}{\mu},\ \frac{(1 - w)^2}{\sigma_d^2}\right)$$

The filter's posterior over $(w, \mu)$ is sampled and the passages mixed: the remaining life's
P10, P50 and P90, and $P(T \le H)$ for the decision. The two uncertainty scales (how fast a rate may
change, how much wear wanders) are calibrated on the population so the P10-P90 interval holds the
true life 80 % of the time.

### 5  Change detection

On the filter's standardised innovations, which are $N(0, 1)$ while the model holds:

- **CUSUM** (Page): $S_t = \max(0, S_{t-1} + e_t - k)$, alarm at $S_t > h$ ($k = 0.5$, $h = 5$) - a
  part wearing faster than its model: a disturbance, the earliest cue to its root cause.
- **Bayesian online change-point detection** (Adams & MacKay): the posterior of the run length
  since the last change - when that faster wear began.
- **Hotelling's $T^2$** across all ten parts against its $\chi^2_{10}$ limit - behaviour no single
  part's model explains (a new fault mode, a sensor gone wrong).

### 6  The decision

The pre-failure window opens when $P(\text{failure within } H = 90 \text{ orders}) \ge p^*$ for three
orders running. $p^*$ is chosen on the population machines: the threshold with the fewest false
alarms among those that open at least 95 % of windows a shift ahead. In cost terms, $p^*$ is the
break-even ratio of a planned renewal's cost to an unplanned failure's (renewal-reward theory):
a cheap night-gap job against hours of a stopped line justifies acting at a low probability.

## How it is graded

On the same 16 machines the TCN was graded on (64-79; never used for fitting), with the TCN's own
decision rule (`ml/train.py decisions`): a failure is warned in time when the window opened at
least a shift (45 orders) ahead; alarms after a part's last failure with no failure following are
false, at most one per shift. The population machines 0-15 fit everything.

| Method | In time | Missed | Late | Median lead (orders) | False / 1000 orders | RUL error (orders) | P10-P90 holds |
|---|---|---|---|---|---|---|---|
| U6 rules | 100.0 % | 0 | 0 | 687.0 | 0.77 | – | – |
| Statistical pipeline (this) | 97.9 % | 0 | 2 | 119.0 | 0.86 | 26.9 | 81 % |
| TCN: semi-supervised | 55.2 % | 32 | 11 | 100.5 | 0.57 | 75.0 | – |
| TCN: supervised-only | 58.3 % | 30 | 10 | 99.0 | 0.53 | 81.5 | – |
| TCN: oracle | 54.2 % | 40 | 4 | 87.5 | 0.24 | 48.1 | – |

94 failures on the 16 unseen machines; $p^* = 0.1$, $H = 90$ orders.

What the numbers mean:

- **In time and lead.** The rules warn every failure - but a median of 687 orders (about five
  production days) early, throwing away that much part life. The pipeline opens the window about
  a day ahead (119 orders): enough for the night gap, without renewing parts that had days left.
  It pays for that with slightly more false alarms (0.86 against 0.77 per 1000 orders): $p^*$ was
  chosen for recall.
- **Remaining-life error** is the median prediction's error where the true life is under 300
  orders; the TCN's is from `web/public/ml/results.json`. Physics carries most of it: the threshold
  is known and the state is linear in use.
- **Calibration.** The 80 % interval holds the true life 81 % of the time on unseen machines.
- **The detectors** still fire more often than their nominal rate on healthy stretches (CUSUM
  0.7 % of orders, $T^2$ 0.6 % against a nominal 0.1 %): the innovations are not perfectly
  Gaussian - the wear law's shape, the per-machine starting wear. They are evidence, not the decision.

### The two failures of the production months

Without the two saves (`month.py`, the counterfactual), the HBW spindle fails on 16 September and
the VGR gearbox on 16 October:

| Part | First CUSUM alarm | U6 rule warning | Pre-failure window opens | Remaining life then (P10 / P50 / P90, orders) | Failure |
|---|---|---|---|---|---|
| VGR swivel gearbox | Sat 12 Sep 06:14 | Tue 13 Oct 06:57 (83 h ahead) | Wed 14 Oct 21:42 (44 h ahead) | 86.8 / 105.6 / 125.3 | Fri 16 Oct 17:29 |
| HBW travel spindle + nut | Sun 06 Sep 10:29 | Thu 10 Sep 15:12 (149 h ahead) | Tue 15 Sep 11:57 (33 h ahead) | 86.4 / 93.9 / 105.3 | Wed 16 Sep 20:32 |

Both windows open a day and a half ahead, with the remaining life's 80 % range inside the night
gap's reach; the rules warned three and six days ahead. The spindle's first CUSUM alarm (6 Sep)
follows its grease loss (day 5); the gearbox's (12 Sep) comes long before its bearing damage
starts (8 Oct) - one of the CUSUM's false alarms, which is why the decision rests on the
remaining-life probability, not on the change detectors.

## Foundation models

The pipeline can ask a time-series foundation model for a second opinion (`pdm/foundation.py`):
**Chronos-Bolt** forecasts the health state zero-shot, as quantiles, and the same decision grades
it (`make pdm FOUNDATION=chronos`; needs `pip install chronos-forecasting` and downloads the weights
from Hugging Face). It knows no physics, so it is a check on the model and the path to parts that
have no wear law; TimesFM, Moirai, Lag-Llama and MOMENT fit the same interface. The Upgrade 8 TCN,
pre-trained self-supervised on the whole fleet, is this project's own small domain model.

## Where to take it next

1. **Hierarchical Bayesian fleet priors** - each machine's wear rate drawn from a population
   distribution, updated as it runs (Gebraeel-style Bayesian updating), instead of one prior for all.
2. **Particle filter** where the posterior is far from Gaussian (sudden-onset parts near the knee).
3. **Conformal prediction** on the remaining life: a coverage guarantee that does not lean on the
   model being right.
4. **Survival models with time-varying covariates** (Cox, accelerated failure time) where there is
   no wear law, only failure records.
5. **Real signals**: motor currents and vibration (envelope spectra for the bearings), read over
   the OPC UA interface; the normal-behaviour model then grows to more covariates (load, speed).
6. **Fine-tuning a foundation model** on the fleet's health states, then calibrating it the same way.
7. **Maintenance optimisation** across parts: group renewals into one stop when several windows
   overlap (opportunistic maintenance).

## Reading list

In the order to read them.

**Foundations of condition-based maintenance and prognostics**

1. Jardine, A. K. S., Lin, D., Banjevic, D. (2006). A review on machinery diagnostics and prognostics
   implementing condition-based maintenance. *Mechanical Systems and Signal Processing*, 20(7), 1483-1510.
2. Lei, Y., Li, N., Guo, L., Li, N., Yan, T., Lin, J. (2018). Machinery health prognostics: A systematic
   review from data acquisition to RUL prediction. *Mechanical Systems and Signal Processing*, 104, 799-834.
3. Si, X.-S., Wang, W., Hu, C.-H., Zhou, D.-H. (2011). Remaining useful life estimation - A review on the
   statistical data driven approaches. *European Journal of Operational Research*, 213(1), 1-14.
4. ISO 13374 (condition monitoring data processing) and ISO 13381-1 (prognostics) - the standard
   vocabulary for the stages above.

**Degradation models and remaining-life distributions**

5. Whitmore, G. A. (1995). Estimating degradation by a Wiener diffusion process subject to measurement
   error. *Lifetime Data Analysis*, 1, 307-319.
6. Gebraeel, N. Z., Lawley, M. A., Li, R., Ryan, J. K. (2005). Residual-life distributions from component
   degradation signals: A Bayesian approach. *IIE Transactions*, 37(6), 543-557.
7. Si, X.-S., Wang, W., Hu, C.-H., Chen, M.-Y., Zhou, D.-H. (2013). A Wiener-process-based degradation
   model with a recursive filter algorithm for remaining useful life estimation. *Mechanical Systems and
   Signal Processing*, 35(1-2), 219-237.
8. Meeker, W. Q., Escobar, L. A. (1998). *Statistical Methods for Reliability Data*. Wiley.

**Filtering**

9. Simon, D. (2006). *Optimal State Estimation: Kalman, H∞, and Nonlinear Approaches*. Wiley - the
   iterated EKF and constrained Kalman filtering (chapters 13 and 7).
10. Mehra, R. K. (1970). On the identification of variances and adaptive Kalman filtering. *IEEE
    Transactions on Automatic Control*, 15(2), 175-184.

**Statistical process control and change detection**

11. Page, E. S. (1954). Continuous inspection schemes. *Biometrika*, 41(1/2), 100-115.
12. Montgomery, D. C. *Introduction to Statistical Quality Control*. Wiley - CUSUM and EWMA charts.
13. MacGregor, J. F., Kourti, T. (1995). Statistical process control of multivariate processes.
    *Control Engineering Practice*, 3(3), 403-414.
14. Adams, R. P., MacKay, D. J. C. (2007). Bayesian online changepoint detection. arXiv:0710.3742.

**Normal-behaviour models (the wind-industry practice)**

15. Schlechtingen, M., Santos, I. F. (2011). Comparative analysis of neural network and regression based
    condition monitoring approaches for wind turbine fault detection. *Mechanical Systems and Signal
    Processing*, 25(5), 1849-1875.
16. Tautz-Weinert, J., Watson, S. J. (2017). Using SCADA data for wind turbine condition monitoring - a
    review. *IET Renewable Power Generation*, 11(4), 382-394.

**Hybrid physics and machine learning**

17. Karniadakis, G. E., Kevrekidis, I. G., Lu, L., Perdikaris, P., Wang, S., Yang, L. (2021).
    Physics-informed machine learning. *Nature Reviews Physics*, 3, 422-440.

**Evaluating prognostics**

18. Saxena, A., Celaya, J., Saha, B., Saha, S., Goebel, K. (2010). Metrics for offline evaluation of
    prognostic performance. *International Journal of Prognostics and Health Management*, 1(1).
19. Saxena, A., Goebel, K., Simon, D., Eklund, N. (2008). Damage propagation modeling for aircraft engine
    run-to-failure simulation. *PHM 2008* - the C-MAPSS benchmark, to test the pipeline on outside data.
20. Gneiting, T., Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and estimation.
    *Journal of the American Statistical Association*, 102(477), 359-378.

**Deep learning and foundation models for time series**

21. Bai, S., Kolter, J. Z., Koltun, V. (2018). An empirical evaluation of generic convolutional and
    recurrent networks for sequence modeling. arXiv:1803.01271 - the TCN.
22. Nie, Y., Nguyen, N. H., Sinthong, P., Kalagnanam, J. (2023). A time series is worth 64 words:
    Long-term forecasting with transformers (PatchTST). *ICLR 2023*.
23. Ansari, A. F., et al. (2024). Chronos: Learning the language of time series. *Transactions on Machine
    Learning Research*; arXiv:2403.07815.
24. Das, A., Kong, W., Sen, R., Zhou, Y. (2024). A decoder-only foundation model for time-series
    forecasting (TimesFM). *ICML 2024*.
25. Woo, G., Liu, C., Kumar, A., Xiong, C., Savarese, S., Sahoo, D. (2024). Unified training of universal
    time series forecasting transformers (Moirai). *ICML 2024*.
26. Goswami, M., Szafer, K., Choudhry, A., Cai, Y., Li, S., Dubrawski, A. (2024). MOMENT: A family of open
    time-series foundation models. *ICML 2024*.

**Uncertainty and the decision**

27. Angelopoulos, A. N., Bates, S. (2021). A gentle introduction to conformal prediction and
    distribution-free uncertainty quantification. arXiv:2107.07511.
28. Barlow, R., Hunter, L. (1960). Optimum preventive maintenance policies. *Operations Research*, 8(1),
    90-100.
29. Jardine, A. K. S., Tsang, A. H. C. (2013). *Maintenance, Replacement, and Reliability: Theory and
    Applications* (2nd ed.). CRC Press.

**Bearings and vibration (for real sensors)**

30. Randall, R. B., Antoni, J. (2011). Rolling element bearing diagnostics - A tutorial. *Mechanical
    Systems and Signal Processing*, 25(2), 485-520.

Code: `stf-cad/hbw/pdm/` (`data.py` the fleet, `model.py` the normal-behaviour model, filter and
remaining life, `stats.py` the charts and BOCPD, `foundation.py` the optional foundation model,
`run.py` fitting, grading and the dashboard's `web/public/pdm/pdm.json`). Tests:
`tests/test_pdm_stats.py`.
