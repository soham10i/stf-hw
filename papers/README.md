# Papers behind the models

The literature the twin's algorithms are built on: what each paper is, what it is used for, and
where in the code. Open-access papers are downloaded here (`papers/*.pdf`); the others are
behind a publisher's paywall and are listed with their DOI, to be read through a library.

The PDFs are **not committed** (`.gitignore`): an arXiv or NASA copy is free to download and read,
but putting it in a public repository would redistribute it. Run the commands at the end to fetch
them again on another machine.

## Time series and predicting failure (Upgrade 8, `stf-cad/hbw/ml/`)

| Paper | Used for | File |
|---|---|---|
| Nie, Nguyen, Sinthong, Kalagnanam (2023). *A Time Series is Worth 64 Words: Long-term Forecasting with Transformers.* ICLR 2023. [arXiv:2211.14730](https://arxiv.org/abs/2211.14730) | Channel independence: one shared network reads one component's health at a time, so every part's failure teaches the same pattern (`ml/train.py`, INPUT) | `nie-2023-patchtst.pdf` |
| Bai, Kolter, Koltun (2018). *An Empirical Evaluation of Generic Convolutional and Recurrent Networks for Sequence Modeling.* [arXiv:1803.01271](https://arxiv.org/abs/1803.01271) | The temporal convolutional network (TCN) behind the maintenance model (`web/public/ml/stf_pm_tcn.onnx`) | `bai-2018-tcn.pdf` |
| Tarvainen, Valpola (2017). *Mean teachers are better role models.* NeurIPS 2017. [arXiv:1703.01780](https://arxiv.org/abs/1703.01780) | Semi-supervised training on the machines with no failure records (`ml/train.py`, step 3) | `tarvainen-2017-mean-teacher.pdf` |
| Saxena, Celaya, Balaban, Goebel, Saha, Saha, Schwabacher (2008). *Metrics for Evaluating Performance of Prognostic Techniques.* IEEE PHM 2008. [doi:10.1109/PHM.2008.4711436](https://doi.org/10.1109/PHM.2008.4711436), open copy from NASA Ames | The lead-time requirement: a warning must leave time to act (`health.py`, Upgrade 6, step 10) | `saxena-2008-prognostics-metrics.pdf` |

## Condition monitoring, degradation and preventive maintenance (Upgrade 6, `stf-cad/hbw/health.py`, `health_theory.py`)

All paywalled; DOIs from the "Hardware degradation" page (`web/src/dashboard/Degradation.tsx`).

| Paper | Used for |
|---|---|
| Jardine, Lin, Banjevic (2006). *A review on machinery diagnostics and prognostics implementing condition-based maintenance.* Mech. Syst. Signal Process. 20(7). [doi:10.1016/j.ymssp.2005.09.012](https://doi.org/10.1016/j.ymssp.2005.09.012) | The condition-based maintenance frame: a signal per part, normalised to its healthy baseline |
| Archard (1953). *Contact and rubbing of flat surfaces.* J. Appl. Phys. 24(8). [doi:10.1063/1.1721448](https://doi.org/10.1063/1.1721448) | Linear wear (p = 1) |
| Paris, Erdogan (1963). *A critical analysis of crack propagation laws.* J. Basic Eng. 85(4). [doi:10.1115/1.3656900](https://doi.org/10.1115/1.3656900) | Accelerating, fatigue-like wear (p > 1) |
| Lu, Meeker (1993). *Using degradation measures to estimate a time-to-failure distribution.* Technometrics 35(2). [doi:10.1080/00401706.1993.10485038](https://doi.org/10.1080/00401706.1993.10485038) | The degradation path to a failure threshold |
| Roberts (1959). *Control chart tests based on geometric moving averages.* Technometrics 1(3). [doi:10.1080/00401706.1959.10489860](https://doi.org/10.1080/00401706.1959.10489860) | The EWMA |
| Lucas, Saccucci (1990). *Exponentially weighted moving average control schemes.* Technometrics 32(1). [doi:10.1080/00401706.1990.10484583](https://doi.org/10.1080/00401706.1990.10484583) | The EWMA's spread and false-alarm margins |
| Si, Wang, Hu, Zhou (2011). *Remaining useful life estimation - a review on the statistical data driven approaches.* EJOR 213(1). [doi:10.1016/j.ejor.2010.11.018](https://doi.org/10.1016/j.ejor.2010.11.018) | The trend warning: remaining life from the slope |
| Lei et al. (2018). *Machinery health prognostics: a systematic review from data acquisition to RUL prediction.* Mech. Syst. Signal Process. 104. [doi:10.1016/j.ymssp.2017.11.016](https://doi.org/10.1016/j.ymssp.2017.11.016) | The same, and the data path |
| Widrow, Kollár (2008). *Quantization Noise.* Cambridge University Press. [doi:10.1017/CBO9780511754661](https://doi.org/10.1017/CBO9780511754661) | The PLC scan's quantisation noise (Δ²/12) |
| Meeker, Escobar (1998). *Statistical Methods for Reliability Data*, ch. 13. Wiley (book) | Degradation data |
| Montgomery (2019). *Introduction to Statistical Quality Control*, ch. 9. Wiley (book) | CUSUM and EWMA charts |

## Vision inspection (Upgrade 15, `stf-cad/hbw/vision/adapt.py`)

| Paper | Used for | File |
|---|---|---|
| Li, Wang, Shi, Liu, Hou (2016). *Revisiting Batch Normalization For Practical Domain Adaptation* (AdaBN). [arXiv:1603.04779](https://arxiv.org/abs/1603.04779) | Re-estimating the network's statistics on a changed line | `li-2016-adabn.pdf` |
| Wang, Shelhamer, Liu, Olshausen, Darrell (2021). *Tent: Fully Test-time Adaptation by Entropy Minimization.* ICLR 2021. [arXiv:2006.10726](https://arxiv.org/abs/2006.10726) | Label-free adaptation, the study's second method | `wang-2021-tent.pdf` |

## The learned scheduler (Upgrade 16, `stf-cad/hbw/sched_rl.py`)

| Paper | Used for | File |
|---|---|---|
| Alshiekh, Bloem, Ehlers, Könighofer, Niekum, Topcu (2018). *Safe Reinforcement Learning via Shielding.* AAAI 2018. [arXiv:1708.08611](https://arxiv.org/abs/1708.08611) | The shield that keeps the learned policy inside what the proven policy can rescue | `alshiekh-2018-shielding.pdf` |

## Energy and the grid (Upgrade 9, `stf-cad/hbw/grid.py`)

The energy model cites no paper. It is built from standard methods and specifications:

- a dynamic programme over the battery's state of charge (Bellman's principle of optimality);
- OpenADR-style demand-response events;
- EN 50160 voltage-quality classes for the sags;
- SunSpec information models for the inverter and the battery;
- the Arrhenius "10 K rule" for the PSU's electrolytic capacitors.

## The bake (Upgrade 19, `stf-cad/hbw/bake.py`)

The bake model uses textbook heat and mass transfer: Stefan-Boltzmann radiation, buoyant doorway
flow through the open mouth, the Clausius-Clapeyron relation for water's vapour pressure, and
first-order Arrhenius browning kinetics. Its browning activation energy lies in the range reported
for bakery products by Purlis (2010), *Browning development in bakery products - a review*,
Journal of Food Engineering 99(3) (paywalled).

## Fetching the open papers again

```bash
cd papers && for p in 2211.14730:nie-2023-patchtst 1703.01780:tarvainen-2017-mean-teacher 1803.01271:bai-2018-tcn 1603.04779:li-2016-adabn 2006.10726:wang-2021-tent 1708.08611:alshiekh-2018-shielding; do curl -sL -o "${p#*:}.pdf" "https://arxiv.org/pdf/${p%%:*}"; sleep 3; done
```

```bash
curl -sL -o papers/saxena-2008-prognostics-metrics.pdf https://c3.ndc.nasa.gov/dashlink/static/media/publication/2008_IEEEPHM_MetricsSurvey.pdf
```
