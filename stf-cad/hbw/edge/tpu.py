"""
Trustworthy maintenance T4 - ready for a Coral: both networks as full-integer TFLite (int8 in, int8
out), compiled for the Edge TPU, and graded on the same decisions as everything else.

    STF_VARIANT=up7 python3 -m edge.tpu        (from stf-cad/hbw; or `make edge-tpu`; needs Docker)

The conversion and the compiler run in the stf-edgetpu container (edge/tpu/Dockerfile): TensorFlow
rebuilds each network from the deployed weights and quantizes it with its own calibration (the
TCN on machines 16-31, the CNN on validation renders); edgetpu_compiler maps the operators. The int8
interpreter's answers on the test machines and test renders come back here and are graded like
fp32 and like edge/run.py's integer reference. There is no Edge TPU attached: what is measured is
that the model compiles, what runs on the accelerator, and what int8 does to the decisions - not
its speed.

OUTPUT   web/public/edge/tpu.json; web/public/edge/stf_{tcn,cnn}_int8{,_edgetpu}.tflite
"""
import json
import os
import shutil
import subprocess
import time

import month
import numpy as np
import torch
from ml import train as ml_train
from ml.model import RUL_CAP, WINDOW
from pdm import data

from edge import run

WORK = os.path.join(run.ROOT, ".cache", "edgetpu")
IMAGE = "stf-edgetpu"


def export(fleet):
    from vision import render
    from vision import train as vision_train
    W = json.load(open(os.path.join(run.ML, "weights.json")))
    mu, sd = np.array(W["ctx_mu"], np.float32), np.array(W["ctx_sd"], np.float32)
    tcn, cnn = run.tcn_fp32(), run.cnn_fp32()
    z = {f"tcn.{k}": v.numpy() for k, v in tcn.state_dict().items() if not k.startswith("dec.")}
    z.update({f"cnn.{k}": v.numpy() for k, v in cnn.state_dict().items()})
    rng = np.random.default_rng(0)
    xc = np.concatenate([np.ascontiguousarray(run.windows(fleet[i][0], mu, sd)[c][::16]) for i in run.CAL for c in range(len(month.COMP))])
    xc = xc[rng.choice(len(xc), 1500, replace=False)]
    z["tcn_cal"], z["tcn_cal_rul"] = xc, run.torch_fn(tcn)(xc)[0]
    z["tcn_nin"], z["tcn_win"], z["rul_cap"] = ml_train.N_IN, WINDOW, RUL_CAP
    for i in data.TEST:
        z[f"tcn_test_{i}"] = ml_train.channels(fleet[i][0], mu, sd)          # C x T x NIN
    cal = run.light(cnn, render.dataset(500, vision_train.SEED + 1, render.TRAIN)[0])
    z["cnn_cal"], z["cnn_cal_p"] = cal, run.softmax(run.cnn_taps(cnn, cal)["co"].numpy())  # after the light step
    sets = {"in_domain": render.dataset(vision_train.TEST_N, vision_train.SEED + 2, render.TRAIN), "shifted": render.dataset(vision_train.TEST_N, vision_train.SEED + 3, render.SHIFT)}
    for name, (X, _, _) in sets.items():
        z[f"cnn_{name}"] = run.light(cnn, X)
    os.makedirs(WORK, exist_ok=True)
    np.savez(os.path.join(WORK, "in.npz"), **z)
    return mu, sd, tcn, cnn, sets


def container():
    here = os.path.join(run.HERE, "tpu")
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode:
        subprocess.run(["docker", "build", "--platform", "linux/amd64", "-t", IMAGE, here], check=True)
    subprocess.run(["docker", "run", "--rm", "--platform", "linux/amd64", "-v", f"{os.path.abspath(WORK)}:/work",
                    "-v", f"{here}:/app:ro", IMAGE, "python", "/app/convert.py"], check=True)
    with open(os.path.join(WORK, "report.json")) as fh:
        return json.load(fh), dict(np.load(os.path.join(WORK, "out.npz")))


def main():
    from vision import train as vision_train
    t0 = time.time()
    fleet = data.load(run.CAL + data.TEST)
    mu, sd, tcn, cnn, sets = export(fleet)
    rep, out = container()
    G = run.Graded(fleet, data.TEST)
    ref = run.predict(run.torch_fn(tcn), fleet, data.TEST, mu, sd)
    lite = {i: (out[f"tcn_test_{i}"], out[f"tcn_test_{i}_cls"]) for i in data.TEST}
    rep["tcn"]["graded"] = {"fp32": ml_train.evaluate(G, ref, "fp32"), "tflite int8": {**ml_train.evaluate(G, lite, "tflite int8"), **run.agreement(ref, lite)}}
    rep["cnn"]["graded"] = {}
    for name, (X, yf, yc) in sets.items():
        with torch.no_grad():
            f32 = [torch.softmax(t, 1).numpy() for t in cnn(torch.from_numpy(X))]
        pf, pc = out[f"cnn_{name}_flavour"], out[f"cnn_{name}_condition"]
        s = vision_train.score(pf, pc, yf, yc)
        s["verdicts_changed"] = round(float((vision_train.verdicts(f32[1]) != vision_train.verdicts(pc)).mean()), 4)
        rep["cnn"]["graded"][name] = {"fp32": vision_train.score(*f32, yf, yc), "tflite int8": s}
    for k in ("tcn", "cnn"):
        for f in (f"stf_{k}_int8.tflite", f"stf_{k}_int8_edgetpu.tflite"):
            if os.path.exists(os.path.join(WORK, f)):
                shutil.copy(os.path.join(WORK, f), os.path.join(run.OUT, f))
        for e in ("stdout", "stderr"):
            rep[k]["edgetpu"][e] = rep[k]["edgetpu"][e].strip()
    rep["seconds"] = round(time.time() - t0, 1)
    with open(os.path.join(run.OUT, "tpu.json"), "w") as fh:
        json.dump(rep, fh, separators=(",", ":"))
    g = rep["tcn"]["graded"]
    for k, r in g.items():
        print(f"  TCN {k:12s} warned {r['warned_1shift']}/{r['failures']} late {r['late']} missed {r['missed']} "
              f"false/1000 {r['false_per_1000']} MAE {r['rul_mae_orders']} {r.get('alarm_agreement', '')}")
    for name, r in rep["cnn"]["graded"].items():
        for k, s in r.items():
            print(f"  CNN {name:9s} {k:12s} escape {s['escape_rate']:.4f} false reject {s['false_reject']:.4f} "
                  f"to a person {s['to_person']:.4f} {s.get('verdicts_changed', '')}")
    for k in ("tcn", "cnn"):
        print(k, rep[k]["edgetpu"]["ops"])
    print(f"  {rep['seconds']} s")


if __name__ == "__main__":
    main()
