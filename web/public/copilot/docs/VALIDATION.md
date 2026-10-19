# Validation of Upgrades 1-11

Run 2026-10-18 15:32 by `stf-cad/hbw/validate.py` in 32.1 min. **12 checks fail** (listed at the end).

## A. Regression: every variant re-exported through its own proof gates

| Variant | Proof gates | Fingerprint | Baseline |
|---|---|---|---|
| base | pass | `da9412ff4f126dbf` | CHANGED |
| up1 | pass | `8a3222d27dff8ff7` | CHANGED |
| up2 | pass | `b9aa72488538b2d0` | CHANGED |
| up3 | pass | `d79df348f159b09f` | CHANGED |
| up4 | pass | `70b614b9745014fc` | CHANGED |
| up5 | pass | `edac0d10831c6e31` | CHANGED |
| up6 | pass | `35270c8b32a645a1` | CHANGED |
| up7 | pass | `ebdd5ab5eaa81e31` | CHANGED |
| up10 | pass | `08fafd7bb7802412` | CHANGED |
| up11 | pass | `5f6e8d7af114d606` | CHANGED |
| up12 | pass | `af23193285c05d49` | CHANGED |

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

- **Month data:** month.json `6d412cb05d705c30` (baseline).
- **Grid:** re-run gives the same grid.json `b96a35c6ca6396c9`.
- **Network deployments** over 600 windows: PyTorch vs stored 0.0005, ONNX vs PyTorch 0.000000, browser JSON weights vs PyTorch 0.000032 orders.
- **pytest:** FAILED tests/test_sessions.py::test_the_answer_says_its_style - TypeError: se.... **Web build:** ok.

## Failing checks

- export base: fingerprint da9412ff4f126dbf != 711384cae7050657
- export up1: fingerprint 8a3222d27dff8ff7 != 3a557419cd2f4a15
- export up2: fingerprint b9aa72488538b2d0 != b4d644ba341b40a9
- export up3: fingerprint d79df348f159b09f != 2971fec0a424fbdd
- export up4: fingerprint 70b614b9745014fc != eddb8092a85f09d2
- export up5: fingerprint edac0d10831c6e31 != 91a5151430b1369e
- export up6: fingerprint 35270c8b32a645a1 != 6aa7bba7c3157f14
- export up7: fingerprint ebdd5ab5eaa81e31 != 3472ba2584d4ad82
- export up12: fingerprint af23193285c05d49 != bb0fe5697678867a
- export up10: fingerprint 08fafd7bb7802412 != 06e82bb098ca27ac
- export up11: fingerprint 5f6e8d7af114d606 != f83568a8d7290ee1
- data: pytest: FAILED tests/test_sessions.py::test_the_answer_says_its_style - TypeError: se...
