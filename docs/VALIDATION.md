# Validation of Upgrades 1-11

Run 2026-10-01 15:10 by `stf-cad/hbw/validate.py` in 21.9 min. **All checks pass.**

## A. Regression: every variant re-exported through its own proof gates

| Variant | Proof gates | Fingerprint | Baseline |
|---|---|---|---|
| base | pass | `824c457c8189eb7b` | same |
| up1 | pass | `000b366fd15909cd` | same |
| up2 | pass | `3ec82a7265d44c9a` | same |
| up3 | pass | `a5970f960fb01ec4` | same |
| up4 | pass | `97134e9092eda466` | same |
| up5 | pass | `8adfd516e55343a4` | same |
| up6 | pass | `66b9654eaab6a0af` | same |
| up7 | pass | `c9509a5d41227fd1` | same |
| up10 | pass | `9b8e41238bbb3f40` | same |
| up11 | pass | `4c776f070fa29158` | same |
| up12 | pass | `c2be57a44db3b6b6` | same |

## B. Proofs without an export of their own

- **U11 security:** 25 allow rules for 70 program accesses; 6/6 attacks contained; 20 zone pairs denied; exposed and blocked: vgr.Q7, oven.Q10, sorting.Q2.
- **U10 published numbers:** fresh simulation 644.5 → 425.7 s and 1787 explored states, equal to throughput.json.

## C. Robustness: ±20 % random variation on every plant step, 25 seeds each

| Program | Fastest | Median | Slowest | False watchdog trips | Worst watchdog use |
|---|---|---|---|---|---|
| Upgrade 7 | 629.74 s | 636.08 s | 646.58 s | 0 | 79 % |
| Upgrade 10 | 421.94 s | 429.64 s | 435.01 s | 0 | 79 % |

## D. Mutation tests: a defect planted in each proof

| # | Proof | Planted defect | Caught |
|---|---|---|---|
| M1 | U4/U10 exhaustive explorer | the arm is given a bay pick while its cup holds a cookie | yes |
| M2 | U4 exhaustive explorer | prefetch: a second mould on the belt | yes |
| M3 | U4 state-machine proof | the VGR's motion steps lose their timeouts | yes |
| M4 | U10 swept-path proof (SAT) | the blended crossing flown at 100 mm (inside the joint limits) | yes |
| M5 | U11 least privilege | the retired VGR compressor coil made writable | yes |
| M6 | U11 least privilege | the HBW write rule removed | yes |
| M7 | U11 default deny | a vendor VPN straight into cell control | yes |
| M8 | U2 safety logic (exhaustive) | the relay reads only channel 1 | yes |
| M9 | U11 SunSpec allow-list | the EMS may write the battery reserve | yes |

## E. Data products

- **Month data:** month.json `f2ea4c5120bed073` (baseline).
- **Grid:** re-run gives the same grid.json `f2b1af7de4e1da07`.
- **Network deployments** over 600 windows: PyTorch vs stored 0.0005, ONNX vs PyTorch 0.000000, browser JSON weights vs PyTorch 0.000032 orders.
- **pytest:** ............................                                             [100%]. **Web build:** ok.

