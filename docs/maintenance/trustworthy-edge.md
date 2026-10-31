# Trustworthy maintenance at the edge

Physics-informed remaining-life prediction with calibrated uncertainty, a safety-shielded decision
layer, and measured accelerator trade-offs.

The twin already predicts failures (the [pre-failure window](pdm-pipeline.md): a physics-informed
Kalman filter with a first-passage remaining-life distribution, graded against rules and a temporal
CNN). This track asks the questions that decide whether such a model may be trusted with a real
machine, and answers each with a number:

1. **Are its uncertainties honest** - on a new machine, per part, in the last shift before a failure?
2. **Do they stay honest when the plant drifts** away from the data the model was fitted on?
3. **Can a decision built on them be guaranteed** not to break a safety or production constraint?
4. **What does running it on edge hardware cost** in accuracy, latency and energy?

No hardware is assumed. The simulated fleet (`ml/fleet.py`: Upgrade 7 cells, each with its own wear,
disturbances and seed, run to failure) stands in for the plant, and every write-up says so. The fleet
is split so nothing is graded on what it was fitted on:

| machines | role |
|---|---|
| 0-15 | population: fit the normal-behaviour model, noise levels, uncertainty scales (`pdm/run.py`) |
| 16-31 | calibration: conformal quantiles and the risk-controlled threshold (T1) |
| 64-79 | test: every number reported (the TCN's test machines too) |

## T1 Calibrated remaining life - `pdm/conformal.py`, `make conformal`

Split conformal prediction on the filter's P10/P50/P90, in log(1 + RUL):

- **interval**: conformalised quantile regression (Romano et al. 2019), 90 %;
- **lower bound**: one-sided, "lasts at least L orders with 90 % probability" - the quantity a
  maintenance decision needs;
- **Mondrian per component**: the guarantee per part, not only on average;
- **conformal risk control** (Angelopoulos et al. 2024) of the alarm threshold p*: the share of
  failures warned less than a shift ahead is bounded by 5 % in expectation, at the fewest false alarms.

Graded: coverage marginal / per component / by true remaining life, a bootstrap over test machines,
interval width, and the late share of the decision.

## T2 Under drift - `pdm/drift.py`, `make drift`

The guarantees of T1 assume a new machine is exchangeable with the calibration machines. A line
commissioned elsewhere is not. The twin builds that machine on purpose: the test machines 64-79 run
again with one thing changed (`month.Month(shift=...)`), keeping each machine's own wear, disturbances
and random draws, so every difference is the shift's (the nominal plant is bit-identical):

| shift | what changes | what it stands for |
|---|---|---|
| hot | hall +6 degC | another site; the normal-behaviour model should divide it out (benign) |
| noisy | sensor noise x 2 | a worn sensor, EMI |
| fast | wear x 1.6 | heavier duty |
| law | every wear-law exponent x 0.7 | a part from another supplier: model-plant mismatch |

Measured per shift:

- **static**: T1's calibration and risk-controlled p*, applied unchanged - how far each guarantee falls;
- **detection without labels**: the filter's innovations are white under the right model, so their
  per-block energy is ranked against the calibration machines (a conformal p-value) and a conformal
  test martingale bets against it; Ville's inequality bounds the false-alarm probability by 1 % per
  machine. Delay per machine and for the fleet;
- **recovery with delayed labels**: on the fleet's clock a failure labels its whole stretch at once.
  Recency-weighted conformal (the old fleet fades as new failures arrive) and, on top, adaptive
  conformal inference on the miscoverage level;
- **the decision online**: p* tracked after each failure (p* <- p* - eta (late - alpha)), so the
  long-run late share returns to its target whatever the drift.

## T3 Risk-aware decision layer - `pdm/decide.py`, `make decide`

The decision the remaining life exists for: a part whose window has opened is renewed in the free
night gap (22-06) or the cell stops now. The calibrated lower bound L is the shield: waiting is allowed
only while L outlasts the orders until the gap, so a wait fails with probability at most alpha.
Policies: run to failure, the U6 rules, window -> tonight, window + shield (alpha 0.01-0.5, and a
cost-aware alpha per part = cost of stopping / cost of failing), the shield alone. Graded by
renewal-reward on every failure stretch of the test machines, nominal and drifted: in-service
failures, production hours lost, renewals and life used per 1000 orders, and the shield's own check
(waits that failed). Still open: calibrating the decision at its decision points, and handing a
unit's planned stop to the Upgrade 16 scheduler (`sched_rl.py`), whose shield already proves the
PLC's policy can always finish.

## T4 Edge inference - `edge/`, `make edge`, `make edge-tpu`, `make edge-browser`

The twin's neural networks are what an accelerator is for. T4 measures what it costs to move them there,
on the hardware at hand and without the target device:

- **int8, three ways.**
  - An integer-only reference (`edge/int8.py`): per-channel int8 weights, per-tensor int8 activations,
    int32 accumulators, fixed-point requantisation and a 256-entry sigmoid, written out so every rounding
    is visible and tested (`tests/test_edge_int8.py`).
  - ONNX Runtime's static int8 (QDQ, per channel), which a RevPi would run.
  - TensorFlow's full-integer TFLite (int8 in and out), which an Edge TPU runs.
  - Calibration uses data the grading never sees: machines 16-31 for the TCN, the validation renders for
    the CNN.
  - Every variant is graded on the decision it feeds: for the TCN, warned a shift ahead, late, missed and
    false alarms; for the CNN, escapes, false rejects and cookies sent to a person.
- **Targets.**
  - CPU: PyTorch, ONNX Runtime fp32 and int8, on one thread (the RevPi's situation) and on all cores.
  - Browser: the existing TypeScript forward pass against a hand-written WebGPU kernel (`web/src/edge`),
    measured in headless Chrome and again on the visitor's own GPU from the dashboard.
  - Edge TPU: both models compiled with Coral's `edgetpu_compiler`, in a container.
- **Not done:**
  - the vision autoencoder in int8;
  - quantisation-aware training, not needed because post-training int8 kept the decisions;
  - WASM SIMD;
  - energy: no power meter here, and the Edge TPU's speed needs the device.

## Results

Filled in by each step's run; nothing here is quoted before it was measured.

### T1 - calibrated remaining life (`make conformal`)

Calibration: machines 16-31, 23,862 orders, 80 failures. Test: machines 64-79, 27,848 orders, 94
failures. Target 90 %. "Last shift" = true remaining life under 45 orders. Machine spread = 5-95 %
of a bootstrap over the 16 test machines. Filter as now (failure on the raw signal, see T2).

| method | holds | machine spread | last shift | worst part | lower bound, last shift | width, last shift |
|---|---|---|---|---|---|---|
| filter alone (P10-P90) | 81.1 % | 78-84 % | 66.4 % | 47.6 % (belt) | 73.5 % | 29 orders |
| conformal, pooled | 93.2 % | 92-95 % | 81.2 % | 81.5 % | 82.4 % | 60 |
| conformal, per part | 93.7 % | 92-95 % | 83.2 % | 90.1 % | 84.3 % | 62 |
| conformal, per part x predicted life | 93.2 % | 92-95 % | 82.3 % | 89.8 % | 83.1 % | 46 |

| alarm threshold | p* | late (test) | false per 1000 orders |
|---|---|---|---|
| from the population (`pdm/run.py`) | 0.50 | 2/94 | 0.00 |
| conformal risk control, late share <= 5 % | 0.65 | 2/94 | 0.00 |
| *first model (failure at w = 1)*, population | 0.10 | 2/94 | 0.83 |
| *first model*, risk control | 0.20 | 5/94 | 0.00 |

- The filter's intervals were tuned to 80 % on average and hit it, but the average hides a part
  covered under half the time (the belt, the part that fails most) and a last shift covered 66 %.
  The lower bound is optimistic exactly where a decision is taken: the dangerous direction.
- Conformal calibration restores the average (93 %, slightly conservative: orders within a machine
  are dependent, the effective sample is the 80 failures) and lifts the worst part to 90 %.
- **No interval method reaches 90 % in the last shift** (best 83 %). "The last shift" is defined by
  the true failure time, which is not observable when the interval is made, and conformal prediction
  can only condition on what is observable. That is the honest limit of order-level guarantees - so
  the guarantee for the decision is stated per failure (risk control), where it holds.
- With the first model, risk control traded 3 late warnings for every false alarm; with the corrected
  model both thresholds reach 2/94 late and none false, and risk control certifies a higher p*.

### T2 - under drift (`make drift`)

The test machines re-run with one thing changed; paired, so every difference is the shift's. Detect
-> adapt = the static calibration until a detector fires, then weighted conformal + ACI per part.

| shift | seen in the signals | seen in the failures | holds: static -> detect/adapt | worst part | late (first model) | late (now) | lowest late, any p* (first model) |
|---|---|---|---|---|---|---|---|
| none | 0/16 machines | - | 93.1 % | 88 % | 5/94 | 2/94 | 1.1 % |
| hall +6 degC | 0/16 | after 2 failures | 82.2 -> 89.0 % | 41 -> 83 % | **16/95** | **3/95** | **13.7 %** |
| sensor noise x 2 | 16/16, 165 orders | - | 85.8 -> 89.0 % | 79 -> 85 % | 3/94 | 3/94 | 1.1 % |
| wear x 1.6 | 0/16 | - | 93.9 % | 89 % | 3/145 | 2/145 | 1.4 % |
| wear law p x 0.7 | 0/16 | - | 91.7 % | 80 % | 8/93 | 2/93 | 1.1 % |

(Coverage columns: the first model, where the drift bites; with the corrected model the hot hall holds
94.6 % static, worst part 93 %.)

- **The detectors split the shifts.** The innovations test (median squared innovation across the
  parts, per block, against the calibration machines; a conformal test martingale with Ville's bound
  at 1 %) never fired on the unchanged machines and caught the noisy sensors on every machine within
  ~2.5 shifts - but it is blind to every physical shift, because the filter absorbs them into its wear
  estimate and its innovations stay white. Only the failures show those: the outcome test (how
  optimistic each failure's lower bound was, one p-value per failure) caught the hot hall after 2
  failures. A first version (mean across parts) raised alarms on unchanged machines - the gearbox
  near its knee under a 5x disturbance reaches innovations of 200, a local anomaly for the CUSUM, not
  a drift of the plant - and the p-values within a machine were not independent, so Ville's bound did
  not hold. The median across parts fixed both.
- **Detect -> adapt** keeps the static calibration where nothing is detected (adapting costs
  efficiency: always-on weighted ACI dropped the nominal coverage to 88 %) and recovers it where
  something is (hot 82 -> 89 %, worst part 41 -> 83 %).
- **The hot hall could not be saved by any threshold** (13.7 % late even at p* = 0.01): the
  normal-behaviour model divides temperature out of the signal, but the part fails on the raw signal,
  so in a warm hall it fails at less wear than the filter's w = 1. Fixed at the source - the filter's
  failure point w*(T) - the hot hall drops to 3/95 late, and the pipeline also improves on the
  unchanged machines (false alarms 0.86 -> 0 per 1000 orders at the same 97.9 % warned in time;
  see [pdm-pipeline.md](pdm-pipeline.md)). This is now the default.

### T3 - the decision with a shield (`make decide`)

Renew in the free night gap, or stop the cell now. Renewal-reward over every failure stretch of the
test machines (nominal; per 1000 orders):

| policy | in-service failures | production hours lost | renewals | life used | waits that failed |
|---|---|---|---|---|---|
| run to failure | 0.713 | 1.335 | 0.71 | 100 % | - |
| U6 rules -> tonight | 0 | 0 | 1.81 | 25 % | - |
| window -> tonight | 0.024 (3) | 0.032 | 0.74 | 96 % | - |
| window + shield, alpha 0.1 | 0 | 0.238 | 0.75 | 96 % | 1/58 |
| window + cost-aware shield | 0 | 0.128 | 0.74 | 96 % | 2/84 |
| shield alone (no window) | 0 | 0.310 | 0.88 | 89 % | 0/57 |

- The rules never fail a part - by renewing it at a quarter of its life (2.4x the parts).
- The window uses 96 % of each part's life; 3 of 94 failures still come before the night gap.
- The shield removes them (0 in-service failures on the nominal, hot, noisy and law fleets; 0.011
  per 1000 with wear x 1.6) and its promise holds with room: at most 2.4 % of its waits failed
  against the 10 % allowed. It pays in stops: 0.24 h per 1000 orders at alpha 0.1, 0.10 h at 0.5.
- **On this plant, stopping costs more production than the failures it prevents** (failures cost
  1-6.5 h, the window opens ~1.3 shifts ahead, often before a far gap). The risk-neutral shield level
  alpha_k = C_stop / C_fail halves the stops but stays above window -> tonight's 0.032 h: the bound is
  calibrated over all orders, not at the decision points, so its alpha is not the conditional
  P(fail before the gap). The shield is the price of a guarantee - zero in-service failures for about
  0.1 h per 1000 orders - which the operator buys when a failure costs more than downtime (scrap, a
  cookie on the gripper, safety).

Next for T3: calibrate the decision itself (risk control on "failed before its gap" at the decision
points, per part), and let the U16 scheduler's shield see a unit's planned stop.

### T4 - edge inference (`make edge`, `make edge-tpu`, `make edge-browser`)

**First finding: the deployed TCN was stale.** On today's simulator the Upgrade 8 network warned 8 of 94
failures in time (life error 140 orders), against the 53 of 96 its own `results.json` reported.
- The simulator had changed since the network was trained on 2 October: in the dashboard's month the hall
  temperature now differs by up to 6.7 degrees C.
- Its parity check could not notice. It stores the old month's inputs with PyTorch's answers, so the
  browser matched PyTorch on data that no longer exists.
- Retrained with the same recipe (`python -m ml.train`, 12 min on the GPU): 62 of 94 warned in time, life
  error 69.7 orders.
- All T4 numbers are on the retrained network.
- A network trained on a simulator drifts silently when the simulator changes. A real plant changes too,
  which is T2's question, here asked of the code.

**The TCN in int8**, test machines 64-79, 94 failures:

| variant | warned a shift ahead | late | missed | false /1000 | life error | same alarm as fp32 | life diff p99 |
|---|---|---|---|---|---|---|---|
| fp32 (deployed) | 62 | 9 | 23 | 0.83 | 69.7 | - | - |
| int8 weights, fp32 activations | 61 | 11 | 22 | 0.83 | 70.0 | 99.96 % | 3.4 |
| int8, min/max ranges | 59 | 12 | 23 | 0.72 | 70.7 | 99.78 % | 20.3 |
| + logit range | 60 | 12 | 22 | 0.81 | 70.1 | 99.84 % | 12.5 |
| + input equalised | 62 | 10 | 22 | 0.88 | 69.7 | 99.86 % | 10.9 |
| percentile ranges, both fixes | 62 | 10 | 22 | 0.83 | 69.7 | 99.88 % | 9.1 |
| ONNX Runtime int8 (QDQ) | 62 | 10 | 22 | 0.83 | 70.7 | 99.84 % | - |
| TFLite full int8 (the Edge TPU model) | 61 | 12 | 21 | 0.88 | 70.7 | 99.83 % | - |

- **Two int8 traps, each found and fixed in the arithmetic.**
  - *The remaining-life logit.* Healthy parts drive the sigmoid deep into saturation, so min/max spends
    the 256 steps on [-4.8, 148.6]: 0.60 logits per step, about 38 orders of life per step near the alarm
    threshold. Calibrating that one tensor over the sigmoid's working range [-8, 8] gives 0.05 per step (3 orders).
  - *The input tensor.* It mixes a health signal in [0, 1] with temperatures in standard deviations and
    one-hot flags under one int8 scale, leaving the health signal 43 levels. Scaling each input channel
    to the same range, and dividing the first layer's weights by the same factors (exact in fp32;
    Nagel et al. 2019), gives it 120.
  - Together they halve the worst-case life error from 20.3 to 10.9 orders (p99 against fp32).
- **The decision barely moves.** 99.8-99.9 % of orders raise the same alarm as fp32. The few flips change
  1-3 of 94 outcomes, in both directions: no worse than fp32 once both fixes are in.
- **Weights alone cost almost nothing** (99.96 %). The error is in the activations, which is where the
  two fixes act.
- **All three int8 implementations agree** (the reference, ONNX Runtime, TFLite): what int8 does to this
  network is a property of the network, not of a runtime.

**The inspection CNN in int8**, 3000 test renders like training and 3000 under unseen conditions:

| variant | images | condition right | escapes | false rejects | to a person | verdicts changed |
|---|---|---|---|---|---|---|
| fp32 (deployed) | like training | 98.8 % | 0.42 % | 0.67 % | 0.87 % | - |
| int8, min/max | like training | 98.6 % | 0.46 % | 0.67 % | 0.97 % | 0.43 % |
| int8, percentile | like training | 97.6 % | 0.92 % | 0.50 % | 1.27 % | 1.53 % |
| TFLite full int8 | like training | - | 0.54 % | 0.67 % | 0.77 % | 0.37 % |
| fp32 (deployed) | unseen | 67.3 % | 1.71 % | 29.8 % | 6.6 % | - |
| int8, min/max | unseen | 66.6 % | 1.75 % | 30.0 % | 6.8 % | 1.77 % |
| TFLite full int8 | unseen | - | 1.71 % | 30.3 % | 6.4 % | 2.10 % |

- Min/max beats percentile here: clipping the CNN's rare large activations doubles the escapes. The
  ranges that suit one network hurt another, so each is graded on its own decision.
- int8 adds at most 0.1 point of escapes. Under unseen conditions the CNN's own weakness (30 % false
  rejects, Upgrade 15) is unchanged: quantisation neither causes nor hides it.
- The light correction (a per-image division by the grey target) stays on the host; the int8 graph
  starts after it.

**What it costs on a CPU** (Apple M4, p50; one thread stands in for the RevPi's situation, not its speed):

| | TCN, one window | TCN, one order (10 parts) | CNN, one image | TCN windows /s |
|---|---|---|---|---|
| PyTorch fp32 | 220 us | 891 us | 481 us | 8,000 |
| ONNX Runtime fp32 | 43 us | 213 us | 302 us | 43,000 |
| ONNX Runtime int8 | 40 us | 170 us | 305 us | 58,000 |
| the statistics: filter + 300 first-passage draws, all parts | - | 1,183 us | - | - |
| the filter alone, all parts / the conformal bound | - | 185 us / 3 us | - | - |

ONNX files: TCN 68 kB fp32, 33 kB int8; CNN 258 kB, 84 kB (kB = 1024 bytes).

- **int8 hardly speeds up the CPU at this size.** 40 against 43 us per window: a 0.5-MFLOP network is
  dominated by the runtime's per-call overhead, not by arithmetic. More threads make it worse; ONNX
  Runtime int8 on ten threads has a 2.8 ms p99. int8 still halves the model (a third, for the CNN).
- **The plan expected the statistics to cost microseconds; measured, they cost more than the network.**
  The filter plus its first-passage draws take 1.18 ms per order, 7x the int8 TCN; the draws are 84 % of
  it. The hot spot on the device is the Monte-Carlo remaining life, not the neural network. It has a
  closed form to replace it (the inverse-Gaussian first passage, integrated over the filter's Gaussian
  posterior). An accelerator for the network would not have found this.
- **Both are negligible next to the process.** An order takes about 15 minutes, so the online decision
  does not need an accelerator on this plant.

**In the browser: a hand-written WebGPU kernel** (`web/src/edge/tcnGpu.ts`). One workgroup takes one
window through all four dilated causal convolutions, the residual, the pooling and the heads, without
leaving workgroup memory. The input (14 x 48) and two 32 x 48 buffers used in turn total 3744 floats,
inside WebGPU's 16 KB guarantee. Each thread computes TILE output channels at one time step. Headless
Chrome on the M4's GPU (Metal), the dashboard's two months (40,850 windows); the answers match the
TypeScript forward pass to 3e-5 orders:

| | one window | one order | windows /s | GFLOP/s |
|---|---|---|---|---|
| TypeScript (dashboard/ml.ts) | 0.5 ms | 4.8 ms | 1,255 | 1.3 |
| WebGPU, tile 1 | 1.5 ms | 1.4 ms | 68,000 | 70 |
| WebGPU, tile 2 | 0.9 ms | 0.8 ms | 129,000 | 132 |
| WebGPU, tile 4 | 0.7 ms | 0.6 ms | 188,000 | 192 |
| WebGPU, tile 8 | 0.6 ms | 0.5 ms | 202,000 | 206 |

Timer resolution is 0.1 ms in the browser, and runs on a loaded machine were up to 50 % slower; the table
is from an idle one.

- **One window is slower on the GPU.** A dispatch plus a read-back costs at least half a millisecond
  whatever the work, so a single window (0.5 ms in TypeScript) gains nothing, and loses at tile 1. One order (10 windows) is
  about 10x faster, and the whole replay 161x: the GPU pays off in bulk, not per decision.
- **Roofline** (Williams et al. 2009):
  - A window is 1.02 MFLOP over 2.7 kB of input: about 380 FLOP per byte from memory, far right of the
    M4's ridge (about 35 FLOP/B at 120 GB/s). The kernel draws 0.5 GB/s, so memory is not the limit.
  - At 206 GFLOP/s it reaches about 5 % of the GPU's arithmetic peak (Apple publishes none; estimates are
    near 4 TFLOP/s). The limit is load issue.
  - The plain kernel (tile 1) does two loads per multiply-add: an input value from workgroup memory and a
    weight. Tiling 8 output channels lets one input feed 8 multiply-adds: 3x faster.
  - What remains is the weight load per multiply-add, and occupancy: 15 KB of workgroup memory per
    window lets only a few workgroups share a GPU core.
  - The next steps would be weights in registers across a tile of time steps, or several windows per
    workgroup.
- **The bigger win is in the model, not the kernel.** Each window zero-pads its own past, so consecutive
  windows (47 of 48 orders shared) cannot share work.
  - A TCN trained with causal padding over the whole sequence would need only the newest column of each
    layer per order: 10,600 multiply-adds in the convolutions instead of 507,000 (48x less), or 34x
    less with the dense heads. This is the fast WaveNet trick (Paine et al. 2016).
  - No kernel recovers that: it needs a retraining decision.

**Ready for a Coral** (`make edge-tpu`). Both networks were rebuilt in Keras from the deployed weights:
the TCN matches PyTorch to 6e-5 orders, the CNN to 2e-6. Each was converted to full-integer TFLite and
compiled with Coral's Edge TPU Compiler 14.1:

| model | int8 TFLite | compiled | operators on the Edge TPU | on-chip parameters |
|---|---|---|---|---|
| remaining-life TCN | 28 kB | 65 kB | 26 of 26: CONV_2D x4 (dilated), PAD x4, ADD, MEAN, STRIDED_SLICE, CONCATENATION, FULLY_CONNECTED x3, LOGISTIC, SOFTMAX, RESHAPE x9 | 37 KiB |
| inspection CNN | 74 kB | 121 kB | 13 of 13: CONV_2D x4, MAX_POOL_2D x3, MEAN, FULLY_CONNECTED x3, SOFTMAX x2 | 81 KiB |

- **One subgraph each**, so nothing falls back to the CPU mid-network.
- **The first TCN attempt was rejected.** With a dynamic batch dimension, TensorFlow inserted int32
  shape arithmetic (SHAPE, PACK) before the reshape, and the compiler refused the model as "not
  quantized". A static batch of 1, which is how an Edge TPU model is deployed, removed it. The dilated
  convolutions then map to CONV_2D directly.
- **Coral's apt repository is gone.** `packages.cloud.google.com` answers 403, so the documented way to
  install the compiler no longer works. The container takes it from Coral's own repository, an older
  version (14.1) than the apt repository served.
- **What is not measured.** There is no device: the TFLite interpreter's int8 answers (graded above) are
  the accelerator's answers up to its own rounding, but its speed and energy need the hardware. With
  under 0.2 MB of parameters both fit the 8 MB on-chip cache whole, so a Coral would stream nothing.

## References

The track builds on the pipeline's own reading list ([pdm-pipeline.md](pdm-pipeline.md#reading-list):
condition-based maintenance, Wiener degradation, Kalman filtering, SPC and change detection,
normal-behaviour models, TCN and foundation models). New here:

**Conformal prediction (T1)**

1. Vovk, V., Gammerman, A., Shafer, G. (2005; 2nd ed. 2022). *Algorithmic Learning in a Random World*.
   Springer - the theory: exchangeability, conformal predictors, Mondrian predictors, martingales.
2. Lei, J., G'Sell, M., Rinaldo, A., Tibshirani, R. J., Wasserman, L. (2018). Distribution-free
   predictive inference for regression. *JASA*, 113(523), 1094-1111 - split conformal.
3. Romano, Y., Patterson, E., Candes, E. J. (2019). Conformalized quantile regression. *NeurIPS 2019* -
   the score used on P10/P90.
4. Vovk, V., Lindsay, D., Nouretdinov, I., Gammerman, A. (2003). Mondrian confidence machine. Working
   paper, Royal Holloway - per-group (per-part) guarantees.
5. Angelopoulos, A. N., Bates, S. (2023). Conformal prediction: a gentle introduction. *Foundations and
   Trends in Machine Learning*, 16(4) (arXiv:2107.07511).
6. Angelopoulos, A. N., Bates, S., Fisch, A., Lei, L., Schuster, T. (2024). Conformal risk control.
   *ICLR 2024* - the guarantee on the late share of the alarm threshold.
7. Candes, E. J., Lei, L., Ren, Z. (2023). Conformalized survival analysis. *JRSS B*, 85(1), 24-45 -
   lower bounds under censoring (the stretches after a machine's last failure, still unused).
8. Javanmardi, A., Hullermeier, E. (2023). Conformal prediction intervals for remaining useful lifetime
   estimation. *International Journal of Prognostics and Health Management* - conformal RUL on C-MAPSS.

**Distribution shift and online calibration (T2)**

9. Vovk, V., Nouretdinov, I., Gammerman, A. (2003). Testing exchangeability on-line. *ICML 2003* -
   conformal test martingales.
10. Volkhonskiy, D., Burnaev, E., Nouretdinov, I., Gammerman, A., Vovk, V. (2017). Inductive conformal
    martingales for change-point detection. *COPA 2017*, PMLR 60.
11. Ville, J. (1939). *Etude critique de la notion de collectif*. Gauthier-Villars - the maximal
    inequality behind the 1/delta threshold.
12. Tibshirani, R. J., Barber, R. F., Candes, E. J., Ramdas, A. (2019). Conformal prediction under
    covariate shift. *NeurIPS 2019*.
13. Barber, R. F., Candes, E. J., Ramdas, A., Tibshirani, R. J. (2023). Conformal prediction beyond
    exchangeability. *Annals of Statistics*, 51(2), 816-845 - the weighted quantile.
14. Gibbs, I., Candes, E. J. (2021). Adaptive conformal inference under distribution shift.
    *NeurIPS 2021* - ACI.
15. Zaffran, M., Feron, O., Goude, Y., Josse, J., Dieuleveut, A. (2022). Adaptive conformal predictions
    for time series. *ICML 2022*.
16. Angelopoulos, A. N., Candes, E. J., Tibshirani, R. J. (2023). Conformal PID control for time series
    prediction. *NeurIPS 2023* - quantile tracking, used for the online p*.
17. Podkopaev, A., Ramdas, A. (2022). Tracking the risk of a deployed model and detecting harmful
    distribution shifts. *ICLR 2022* - benign vs harmful shift (the "hot" case).
18. Gama, J., Zliobaite, I., Bifet, A., Pechenizkiy, M., Bouchachia, A. (2014). A survey on concept drift
    adaptation. *ACM Computing Surveys*, 46(4).
19. Tobin, J., et al. (2017). Domain randomization for transferring deep neural networks from simulation
    to the real world. *IROS 2017* - the sim-to-real practice the shifted fleets stand in for.

**Safe decisions and maintenance optimisation (T3)**

20. Alshiekh, M., Bloem, R., Ehlers, R., Konighofer, B., Niekum, S., Topcu, U. (2018). Safe
    reinforcement learning via shielding. *AAAI 2018* - the shield of Upgrade 16.
21. Garcia, J., Fernandez, F. (2015). A comprehensive survey on safe reinforcement learning. *JMLR*, 16,
    1437-1480.
22. Lindemann, L., Cleaveland, M., Shim, G., Pappas, G. J. (2023). Safe planning in dynamic
    environments using conformal prediction. *IEEE Robotics and Automation Letters*, 8(8) - conformal
    bounds as hard constraints in a planner.
23. Bertsekas, D. P. (2019). *Reinforcement Learning and Optimal Control*. Athena Scientific - rollout.
24. de Jonge, B., Scarf, P. A. (2020). A review on maintenance optimization. *European Journal of
    Operational Research*, 285(3), 805-824 - opportunistic and grouped maintenance.

**Edge inference (T4)**

25. Jacob, B., et al. (2018). Quantization and training of neural networks for efficient
    integer-arithmetic-only inference. *CVPR 2018* - the int8 scheme TFLite and the Edge TPU use.
26. Krishnamoorthi, R. (2018). Quantizing deep convolutional networks for efficient inference: a
    whitepaper. arXiv:1806.08342.
27. Nagel, M., et al. (2021). A white paper on neural network quantization. arXiv:2106.08295.
28. Jouppi, N. P., et al. (2017). In-datacenter performance analysis of a tensor processing unit.
    *ISCA 2017* - the systolic-array design the Edge TPU scales down.
29. Banbury, C., et al. (2021). MLPerf Tiny benchmark. *NeurIPS Datasets and Benchmarks* - how to
    report edge latency and energy.
30. Lai, L., Suda, N., Chandra, V. (2018). CMSIS-NN: efficient neural network kernels for Arm Cortex-M
    CPUs. arXiv:1801.06601.
31. Williams, S., Waterman, A., Patterson, D. (2009). Roofline: an insightful visual performance model
    for multicore architectures. *Communications of the ACM*, 52(4) - for the WebGPU kernel analysis.
32. Nagel, M., van Baalen, M., Blankevoort, T., Welling, M. (2019). Data-free quantization through weight
    equalization and bias correction. *ICCV 2019* - the range equalisation applied to the TCN's input.
33. Paine, T. L., et al. (2016). Fast WaveNet generation algorithm. arXiv:1611.09482 - cached causal
    convolutions: why a streaming TCN would need 34x less work per order.

