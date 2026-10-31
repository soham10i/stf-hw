"""
Trustworthy maintenance T4 - the networks at the edge: what int8 costs, graded on the decisions
they feed, and what each runtime costs in time.

    STF_VARIANT=up7 python3 -m edge.run        (from stf-cad/hbw; or `make edge`)

MODELS   the remaining-life TCN (Upgrade 8, ml/ckpt/semi.pt) and the inspection CNN (Upgrade 15,
         web/public/vision/weights.json, batch norm folded) - as deployed, not retrained.
INT8     post-training quantisation with integer-only arithmetic (edge/int8.py): per-channel
         int8 weights, per-tensor int8 activations calibrated on data the grading never sees
         (TCN: machines 16-31; CNN: the validation renders), fixed-point requantisation. Three
         ways, to separate the causes: weights alone, everything with min/max ranges, and
         everything with the input channels equalised first (each input channel brought to the
         same range, the first layer's weights divided by the same factors - exact in fp32,
         Nagel et al. 2019) - the TCN's input tensor mixes a health signal in [0, 1] with
         temperatures in standard deviations and one-hot flags, one int8 scale for all of them.
GRADED   TCN: the test machines 64-79 with ml/train.py's own decision (alarm when the predicted
         life is under 90 orders for 3 orders; warned a shift ahead, late, missed, false alarms)
         and the life error; how often the int8 alarm differs from fp32's, order by order.
         CNN: the in-domain and shifted test renders of vision/train.py (same seeds) - escapes,
         false rejects, sent to a person - and verdicts that change.
RUNTIME  ONNX Runtime on this CPU (one thread, the RevPi's situation; and all cores), fp32 and
         its own static int8 (QDQ, per-channel), against PyTorch: p50/p99 latency for one window
         and for one order (every part), and fleet throughput. The statistics beside them - the
         filter step, the first-passage draws, the conformal bound - timed the same way.
OUTPUT   web/public/edge/edge.json; web/public/edge/*.onnx (the int8 models).
"""
import copy
import json
import os
import time

import month as M
import numpy as np
import torch

from edge import int8 as Q
from ml import train as T
from ml.model import RUL_CAP, WINDOW, Net
from pdm import data

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..", "..")
OUT = os.path.join(ROOT, "web", "public", "edge")
ML = os.path.join(ROOT, "web", "public", "ml")
VIS = os.path.join(ROOT, "web", "public", "vision")
CAL = list(range(16, 32))
CAL_STRIDE = 4
CHUNK = 4096
LOGIT = 8.0          # sigmoid(8) = 0.99966: beyond +-8 the remaining life no longer moves


# ================================================================== the TCN
def tcn_fp32():
    net = Net(T.N_IN, 1)
    net.load_state_dict(torch.load(os.path.join(HERE, "..", "ml", "ckpt", "semi.pt"), map_location="cpu"))
    return net.eval()


def windows(x, mu, sd):
    """ml/train.py Data: every order's window, per component -> C x T x N_IN x W."""
    s = T.channels(x, mu, sd)
    pad = np.concatenate([np.repeat(s[:, :1], WINDOW - 1, axis=1), s], axis=1)
    return np.lib.stride_tricks.sliding_window_view(pad, WINDOW, axis=1)


def tcn_taps(net, x):
    """The fp32 forward pass with every tensor int8 will hold."""
    with torch.no_grad():
        x = torch.from_numpy(np.ascontiguousarray(x))
        F = torch.nn.functional
        h1 = F.relu(net.c1(x))
        h2 = F.relu(net.c2(h1))
        h3 = F.relu(net.c3(h2))
        r4 = F.relu(net.c4(h3))
        h4 = r4 + h2
        z = torch.cat([h4[:, :, -1], h4.mean(dim=2)], 1)
        f = F.relu(net.fc(z))
        return {"x": x, "h1": h1, "h2": h2, "h3": h3, "r4": r4, "h4": h4, "z": z, "f": f,
                "rl": net.rul(f), "cl": net.cls(f)}


class TCN8:
    """The TCN in integers: conv x4 (ReLU in the clamp), the residual ADD, last step and mean
    rescaled to one scale (the concatenation), fc, and the two heads; the remaining life through
    the int8 logistic, as an Edge TPU would output it."""

    def __init__(self, net, P, eq):
        sd = {k: v.numpy().astype(np.float64) for k, v in net.state_dict().items()}
        self.P, self.eq = P, eq
        w1 = sd["c1.conv.weight"] / eq[None, :, None]
        self.c = [Q.Conv(w1, sd["c1.conv.bias"], *P["x"], *P["h1"], True, 1),
                  Q.Conv(sd["c2.conv.weight"], sd["c2.conv.bias"], *P["h1"], *P["h2"], True, 2),
                  Q.Conv(sd["c3.conv.weight"], sd["c3.conv.bias"], *P["h2"], *P["h3"], True, 4),
                  Q.Conv(sd["c4.conv.weight"], sd["c4.conv.bias"], *P["h3"], *P["r4"], True, 8)]
        self.add = Q.Add(*P["r4"], *P["h2"], *P["h4"])
        self.last = Q.Rescale(*P["h4"], *P["z"])
        self.mean = Q.Rescale(*P["h4"], *P["z"], n=WINDOW)
        self.fc = Q.Linear(sd["fc.weight"], sd["fc.bias"], *P["z"], *P["f"], True)
        self.rul = Q.Linear(sd["rul.weight"], sd["rul.bias"], *P["f"], *P["rl"], False)
        self.cls = Q.Linear(sd["cls.weight"], sd["cls.bias"], *P["f"], *P["cl"], False)

    def __call__(self, x):
        q = Q.quantize(x * self.eq[None, :, None], *self.P["x"])
        h1 = self.c[0](q)
        h2 = self.c[1](h1)
        r4 = self.c[3](self.c[2](h2))
        h4 = self.add(r4, h2)
        z_h4 = self.P["h4"][1]
        z = np.concatenate([self.last(h4[:, :, -1]),
                            self.mean((h4.astype(np.int64) - z_h4).sum(2), summed=True)], 1)
        f = self.fc(z)
        rul = Q.dequantize(Q.logistic(self.rul(f), *self.P["rl"]), *Q.LOGISTIC)[:, 0] * RUL_CAP
        cl = Q.dequantize(self.cls(f), *self.P["cl"]).reshape(-1, 3)
        return rul, softmax(cl)


def softmax(a):
    e = np.exp(a - a.max(1, keepdims=True))
    return e / e.sum(1, keepdims=True)


def calibrate_tcn(net, fleet, mu, sd, how="minmax"):
    obs = {k: Q.Observer(how) for k in ("x", "h1", "h2", "h3", "r4", "h4", "z", "f", "rl", "cl")}
    xs = []
    for i in CAL:
        V = windows(fleet[i][0], mu, sd)
        for c in range(len(V)):
            xs.append(np.ascontiguousarray(V[c][::CAL_STRIDE]))
    X = np.concatenate(xs)
    rng = np.abs(X).max(axis=(0, 2))                         # each input channel's range
    for i in range(0, len(X), CHUNK):
        taps = tcn_taps(net, X[i:i + CHUNK])
        for k, o in obs.items():
            o(taps[k].numpy())
    return {k: o.params() for k, o in obs.items()}, rng, X


def equalised_params(net, X, rng, how="minmax"):
    """Ranges with the input equalised: every channel scaled to the widest one's range."""
    eq = rng.max() / np.maximum(rng, 1e-6)
    o = Q.Observer(how)
    for i in range(0, len(X), CHUNK):
        o(X[i:i + CHUNK] * eq[None, :, None])
    return eq, o.params()


def logit_range(P):
    """The remaining-life logit only matters where the sigmoid moves: a healthy part drives it far
    into saturation, and min/max then spends the 256 steps on logits that all mean 'RUL_CAP'."""
    s, z = P["rl"]
    lo, hi = (Q.QMIN - z) * s, (Q.QMAX - z) * s
    return {**P, "rl": Q.act_params(max(lo, -LOGIT), min(hi, LOGIT))}


def weights_only(net):
    """fp32 activations, int8 weights (per channel): the weights' share of the error."""
    w = Net(T.N_IN, 1)
    sd = {}
    for k, v in net.state_dict().items():
        if k.endswith("weight") and v.ndim >= 2:
            q, s = Q.weight_q(v.numpy())
            v = torch.from_numpy((q * s.reshape(-1, *([1] * (v.ndim - 1)))).astype(np.float32))
        sd[k] = v
    w.load_state_dict(sd)
    return w.eval()


def torch_fn(net, dev=T.DEV):
    """PyTorch's answers in bulk on the GPU (MPS) as in ml/train.py: its CPU dilated Conv1d takes a
    slow path here (~3 GFLOP/s). Latency is timed on the CPU separately (runtimes)."""
    net = copy.deepcopy(net).to(dev)

    def f(x):
        with torch.no_grad():
            r, c = net(torch.from_numpy(np.ascontiguousarray(x)).to(dev))
        return r[:, 0].cpu().numpy(), c[:, 0].softmax(-1).cpu().numpy()
    return f


class Graded:
    """What ml/train.py's evaluate() reads: X, failures F, labels Y per machine."""

    def __init__(self, fleet, ids):
        self.X = {i: fleet[i][0] for i in ids}
        self.F = {i: fleet[i][1] for i in ids}
        self.Y = {i: T.labels(len(fleet[i][0]), fleet[i][1]) for i in ids}


def predict(fn, fleet, ids, mu, sd):
    out = {}
    for i in ids:
        V = windows(fleet[i][0], mu, sd)
        n = V.shape[1]
        R = np.zeros((n, len(V)), np.float32)
        P = np.zeros((n, len(V), 3), np.float32)
        for c in range(len(V)):
            for a in range(0, n, CHUNK):
                r, p = fn(np.ascontiguousarray(V[c][a:a + CHUNK]))
                R[a:a + CHUNK, c], P[a:a + CHUNK, c] = r, p
        out[i] = (R, P)
    return out


def agreement(ref, new):
    """Order by order: does the int8 alarm say what the fp32 alarm says; the life's change."""
    same = tot = 0
    d = []
    for i in ref:
        for c in range(ref[i][0].shape[1]):
            a = set(T.alarm_idx(ref[i][0][:, c]))
            b = set(T.alarm_idx(new[i][0][:, c]))
            n = len(ref[i][0])
            same += n - len(a ^ b)
            tot += n
        d.append(np.abs(ref[i][0] - new[i][0]).ravel())
    d = np.concatenate(d)
    return {"alarm_agreement": round(same / tot, 5), "rul_abs_diff_median": round(float(np.median(d)), 2),
            "rul_abs_diff_p99": round(float(np.percentile(d, 99)), 2), "rul_abs_diff_max": round(float(d.max()), 1)}


def tcn_study(fleet):
    W = json.load(open(os.path.join(ML, "weights.json")))
    mu, sd = np.array(W["ctx_mu"], np.float32), np.array(W["ctx_sd"], np.float32)
    net = tcn_fp32()
    t0 = time.time()
    P, rng, Xc = calibrate_tcn(net, fleet, mu, sd)
    eq, px = equalised_params(net, Xc, rng)
    Pp, _, _ = calibrate_tcn(net, fleet, mu, sd, "percentile")
    eqp, pxp = equalised_params(net, Xc, rng, "percentile")
    del Xc
    ones = np.ones(T.N_IN)
    variants = {
        "fp32": torch_fn(net),
        "int8 weights only": torch_fn(weights_only(net)),
        "int8, min/max": TCN8(net, P, ones),
        "int8, + logit range": TCN8(net, logit_range(P), ones),
        "int8, + logit range, input equalised": TCN8(net, logit_range({**P, "x": px}), eq),
        "int8, percentile, both": TCN8(net, logit_range({**Pp, "x": pxp}), eqp),
    }
    G = Graded(fleet, data.TEST)
    preds, out = {}, {}
    for name, fn in variants.items():
        t = time.time()
        preds[name] = predict(fn, fleet, data.TEST, mu, sd)
        r = T.evaluate(G, preds[name], name)
        if name != "fp32":
            r.update(agreement(preds["fp32"], preds[name]))
        r["seconds"] = round(time.time() - t, 1)
        out[name] = r
        print(f"  TCN {name:36s} warned {r['warned_1shift']}/{r['failures']} late {r['late']} missed {r['missed']} "
              f"false/1000 {r['false_per_1000']} MAE {r['rul_mae_orders']} F1 {r['macro_f1']} "
              f"{'agree ' + str(r.get('alarm_agreement')) if name != 'fp32' else ''} ({r['seconds']} s)", flush=True)
    x_scale = {"per_tensor": P["x"][0], "equalised": px[0], "h_levels_per_tensor": int(round(1 / P["x"][0])),
               "h_levels_equalised": int(round(eq[0] / px[0])), "input_ranges": np.round(rng, 3).tolist(),
               "inputs": T.INPUTS, "logit_step_minmax": P["rl"][0], "logit_step_clipped": logit_range(P)["rl"][0],
               "logit_range_minmax": [round((Q.QMIN - P["rl"][1]) * P["rl"][0], 2), round((Q.QMAX - P["rl"][1]) * P["rl"][0], 2)]}
    return {"variants": out, "input": x_scale, "seconds": round(time.time() - t0, 1),
            "calibration": {"machines": f"{CAL[0]}-{CAL[-1]}", "stride": CAL_STRIDE},
            "scales": {k: [float(v[0]), int(v[1])] for k, v in {**P, "x_eq": px}.items()}}, (net, mu, sd, eq, px, P), preds


# ================================================================== the CNN
def cnn_fp32():
    from vision import train as VT
    W = json.load(open(os.path.join(VIS, "weights.json")))
    net = VT.Net(bn=False, ref=bool(W["ref"]))
    sd = {}
    for name, L in W["layers"].items():
        sd[f"{name}.weight"] = torch.from_numpy(np.frombuffer(__import__("base64").b64decode(L["w"]), "<f4").reshape(L["shape"]).copy())
        sd[f"{name}.bias"] = torch.from_numpy(np.frombuffer(__import__("base64").b64decode(L["b"]), "<f4").copy())
    net.load_state_dict(sd)
    return net.eval()


def light(net, x):
    """The host's part: divide out the light with the grey target, centre on 0 (vision/train.py).
    A per-image division - kept on the CPU, the int8 graph starts after it."""
    from vision import render as R
    if net.ref:
        g = x[:, :, :R.REF, :R.REF].mean(axis=(2, 3), keepdims=True)
        x = x * (0.5 / (g + 1e-3))
    return (x - 0.5).astype(np.float32)


def cnn_taps(net, x):
    F = torch.nn.functional
    with torch.no_grad():
        x = torch.from_numpy(x)
        a1 = F.relu(net.c1(x))
        a2 = F.relu(net.c2(F.max_pool2d(a1, 2)))
        a3 = F.relu(net.c3(F.max_pool2d(a2, 2)))
        a4 = F.relu(net.c4(F.max_pool2d(a3, 2)))
        g = a4.mean(dim=(2, 3))
        f = F.relu(net.fc(g))
        return {"x": x, "a1": a1, "a2": a2, "a3": a3, "a4": a4, "g": g, "f": f, "fl": net.flav(f), "co": net.cond(f)}


class CNN8:
    def __init__(self, net, P):
        sd = {k: v.numpy().astype(np.float64) for k, v in net.state_dict().items()}
        self.P = P
        ins = ["x", "a1", "a2", "a3"]
        self.c = [Q.Conv(sd[f"c{i + 1}.weight"], sd[f"c{i + 1}.bias"], *P[ins[i]], *P[f"a{i + 1}"], True, dims=2)
                  for i in range(4)]
        self.gap = Q.Rescale(*P["a4"], *P["g"], n=64)
        self.fc = Q.Linear(sd["fc.weight"], sd["fc.bias"], *P["g"], *P["f"], True)
        self.fl = Q.Linear(sd["flav.weight"], sd["flav.bias"], *P["f"], *P["fl"], False)
        self.co = Q.Linear(sd["cond.weight"], sd["cond.bias"], *P["f"], *P["co"], False)

    def __call__(self, x):
        q = Q.quantize(x, *self.P["x"])
        for i, conv in enumerate(self.c):
            q = conv(q)
            if i < 3:
                q = Q.maxpool2(q)
        g = self.gap((q.astype(np.int64) - self.P["a4"][1]).sum((2, 3)), summed=True)
        f = self.fc(g)
        return (softmax(Q.dequantize(self.fl(f), *self.P["fl"])),
                softmax(Q.dequantize(self.co(f), *self.P["co"])))


def cnn_study():
    from vision import render as R
    from vision import train as VT
    net = cnn_fp32()
    t0 = time.time()
    Xva, _, _ = R.dataset(VT.VAL_N, VT.SEED + 1, R.TRAIN)          # calibration: the validation renders
    sets = {"in_domain": R.dataset(VT.TEST_N, VT.SEED + 2, R.TRAIN), "shifted": R.dataset(VT.TEST_N, VT.SEED + 3, R.SHIFT)}
    out = {}
    for how in ("minmax", "percentile"):
        obs = {k: Q.Observer(how) for k in ("x", "a1", "a2", "a3", "a4", "g", "f", "fl", "co")}
        xv = light(net, Xva)
        for i in range(0, len(xv), 500):
            taps = cnn_taps(net, xv[i:i + 500])
            for k, o in obs.items():
                o(taps[k].numpy())
        P = {k: o.params() for k, o in obs.items()}
        m8 = CNN8(net, P)
        for sname, (X, yf, yc) in sets.items():
            xl = light(net, X)
            with torch.no_grad():
                f32 = [torch.softmax(t, 1).numpy() for t in net(torch.from_numpy(X))]
            i8 = [np.concatenate(z) for z in zip(*[m8(xl[i:i + 250]) for i in range(0, len(xl), 250)])]
            row = out.setdefault(sname, {"fp32": VT.score(*f32, yf, yc)})
            s = VT.score(*i8, yf, yc)
            s["verdicts_changed"] = round(float((VT.verdicts(f32[1]) != VT.verdicts(i8[1])).mean()), 4)
            s["p_ok_abs_diff_max"] = round(float(np.abs(f32[1][:, 0] - i8[1][:, 0]).max()), 4)
            row[f"int8, {'min/max' if how == 'minmax' else 'percentile'}"] = s
    for sname, row in out.items():
        for k, s in row.items():
            print(f"  CNN {sname:9s} {k:18s} condition {s['condition_acc']:.4f} escape {s['escape_rate']:.4f} "
                  f"false reject {s['false_reject']:.4f} to a person {s['to_person']:.4f} "
                  f"{'changed ' + str(s.get('verdicts_changed')) if 'verdicts_changed' in s else ''}", flush=True)
    return {"sets": out, "seconds": round(time.time() - t0, 1), "calibration": f"{VT.VAL_N} validation renders"}, net


# ================================================================== runtimes
def lat(fn, n=2000, warm=100):
    for _ in range(warm):
        fn()
    t = np.empty(n)
    for i in range(n):
        a = time.perf_counter_ns()
        fn()
        t[i] = time.perf_counter_ns() - a
    return {"p50_us": round(float(np.median(t)) / 1e3, 1), "p99_us": round(float(np.percentile(t, 99)) / 1e3, 1)}


class TCNReader:
    def __init__(self, X, name, n=4000):
        self.it = iter([{name: X[i:i + 1]} for i in np.random.default_rng(0).choice(len(X), n, replace=False)])

    def get_next(self):
        return next(self.it, None)


def ort_models(Xc_tcn, Xc_cnn):
    """The deployed fp32 ONNX files and ONNX Runtime's own static int8 (QDQ, per channel) of each."""
    from onnxruntime.quantization import CalibrationMethod, QuantFormat, QuantType, quantize_static
    from onnxruntime.quantization.shape_inference import quant_pre_process
    os.makedirs(OUT, exist_ok=True)
    made = {}
    for name, src, X, inp in (("tcn", os.path.join(ML, "stf_pm_tcn.onnx"), Xc_tcn, "x"),
                              ("cnn", os.path.join(VIS, "stf_vision_cnn.onnx"), Xc_cnn, "image")):
        pre = os.path.join(OUT, f".{name}_pre.onnx")
        quant_pre_process(src, pre, skip_symbolic_shape=True)
        dst = os.path.join(OUT, f"stf_{name}_int8.onnx")
        quantize_static(pre, dst, TCNReader(X, inp, min(len(X), 2000)), quant_format=QuantFormat.QDQ,
                        per_channel=True, activation_type=QuantType.QInt8, weight_type=QuantType.QInt8,
                        calibrate_method=CalibrationMethod.MinMax)
        os.remove(pre)
        made[name] = (src, dst)
    return made


def session(path, threads):
    import onnxruntime as ort
    o = ort.SessionOptions()
    o.intra_op_num_threads = threads
    o.inter_op_num_threads = 1
    o.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(path, o, providers=["CPUExecutionProvider"])


def ort_fn(sess):
    name = sess.get_inputs()[0].name

    def f(x):
        r, c = sess.run(None, {name: np.ascontiguousarray(x)})
        return r[:, 0], softmax(c[:, 0])
    return f


def runtimes(tcn, cnn, made, fleet):
    net, mu, sd, eq, px, P = tcn
    V = windows(fleet[data.TEST[0]][0], mu, sd)                      # C x T x N_IN x W
    one = np.ascontiguousarray(V[0][500:501])
    order = np.ascontiguousarray(V[:, 500])                         # every part at one order
    fleet_b = np.ascontiguousarray(V[0][:2048])
    from vision import render as R
    img = light(cnn, R.dataset(16, 99, R.TRAIN)[0])
    img_raw = R.dataset(16, 99, R.TRAIN)[0]
    rows = []
    for threads in (1, os.cpu_count()):
        torch.set_num_threads(threads)
        tf = torch_fn(net, "cpu")
        s32, s8 = session(made["tcn"][0], threads), session(made["tcn"][1], threads)
        c32, c8 = session(made["cnn"][0], threads), session(made["cnn"][1], threads)
        fns = {
            "PyTorch fp32": (lambda x: tf(x), lambda x: cnn(torch.from_numpy(x))),
            "ONNX Runtime fp32": (ort_fn(s32), lambda x: c32.run(None, {"image": x})),
            "ONNX Runtime int8": (ort_fn(s8), lambda x: c8.run(None, {"image": x})),
        }
        for name, (ft, fc) in fns.items():
            with torch.no_grad():
                r = {"runtime": name, "threads": threads,
                     "tcn_window": lat(lambda: ft(one)), "tcn_order": lat(lambda: ft(order)),
                     "cnn_image": lat(lambda: fc(img_raw[:1]), n=1000)}
                t = time.perf_counter()
                for _ in range(5):
                    ft(fleet_b)
                r["tcn_windows_per_s"] = round(5 * len(fleet_b) / (time.perf_counter() - t))
            rows.append(r)
            print(f"  {name:20s} {threads:2d} thr  TCN window {r['tcn_window']['p50_us']} us (p99 {r['tcn_window']['p99_us']})  "
                  f"order {r['tcn_order']['p50_us']} us  CNN image {r['cnn_image']['p50_us']} us  "
                  f"{r['tcn_windows_per_s']} windows/s", flush=True)
    m8 = TCN8(net, logit_range({**P, "x": px}), eq)
    rows.append({"runtime": "int8 reference (numpy, edge/int8.py)", "threads": 1, "tcn_window": lat(lambda: m8(one), n=300),
                 "tcn_order": lat(lambda: m8(order), n=300), "note": "integer semantics, not speed"})
    torch.set_num_threads(os.cpu_count())
    del img
    return rows


def ort_decisions(made, fleet, mu, sd, ref):
    """The deployable int8 files graded like the reference: does ONNX Runtime's int8 keep the decision?"""
    G = Graded(fleet, data.TEST)
    out = {}
    for name, path in (("ONNX Runtime fp32", made["tcn"][0]), ("ONNX Runtime int8", made["tcn"][1])):
        p = predict(ort_fn(session(path, os.cpu_count())), fleet, data.TEST, mu, sd)
        r = T.evaluate(G, p, name)
        r.update(agreement(ref, p))
        out[name] = r
        print(f"  TCN {name:36s} warned {r['warned_1shift']}/{r['failures']} late {r['late']} missed {r['missed']} "
              f"false/1000 {r['false_per_1000']} MAE {r['rul_mae_orders']} agree {r['alarm_agreement']}", flush=True)
    return out


def statistics_cost(fleet):
    """The filter + first-passage RUL per order, all parts, and the conformal bound: CPU work."""
    from pdm import conformal as K
    from pdm import model as Mo
    _, pop, _ = K.population()
    X, F, _ = fleet[data.TEST[0]]
    n = 400
    t = time.perf_counter()
    for k in Mo.COMPS:
        Mo.track(X[:n], k, pop, [], horizon=90)
    full = (time.perf_counter() - t) / n
    t = time.perf_counter()
    for k in Mo.COMPS:
        Mo.track(X[:n], k, pop, [], horizon=90, rul=False)
    filt = (time.perf_counter() - t) / n
    q = np.linspace(0.1, 0.9, 3)
    b = np.array([45, 150])
    lb = lat(lambda: np.expm1(np.maximum(np.log1p(123.0) - q[np.digitize(80.0, b)], 0)), n=5000)
    return {"filter_all_parts_per_order_us": round(filt * 1e6, 1), "filter_and_rul_all_parts_per_order_us": round(full * 1e6, 1),
            "first_passage_draws": Mo.N_DRAW, "conformal_bound_us": lb["p50_us"], "parts": len(Mo.COMPS)}


def macs():
    """Multiply-accumulates and bytes moved per inference, for the roofline."""
    C = len(M.COMP)
    n_in = 4 + C
    tcn = WINDOW * 32 * 3 * (n_in + 32 * 3) + 2 * 32 * 64 + 64 * 4
    cnn = 64 * 64 * 16 * 27 + 32 * 32 * 32 * 144 + 16 * 16 * 64 * 288 + 8 * 8 * 64 * 576 + 64 * 64 + 64 * 8
    return {"tcn_mac": tcn, "cnn_mac": cnn}


def main():
    t0 = time.time()
    fleet = data.load(data.FIT + CAL + data.TEST)
    tcn_doc, tcn, preds = tcn_study(fleet)
    cnn_doc, cnn = cnn_study()
    net, mu, sd, eq, px, P = tcn
    from vision import render as R
    from vision import train as VT
    Xc_tcn = np.concatenate([np.ascontiguousarray(windows(fleet[i][0], mu, sd)[c][::16]) for i in CAL for c in range(len(M.COMP))])
    Xc_cnn = R.dataset(2000, VT.SEED + 1, R.TRAIN)[0]
    made = ort_models(Xc_tcn, Xc_cnn)
    tcn_doc["onnx_runtime"] = ort_decisions(made, fleet, mu, sd, preds["fp32"])
    rows = runtimes(tcn, cnn, made, fleet)
    doc = {"tcn": tcn_doc, "cnn": cnn_doc, "runtimes": rows, "statistics": statistics_cost(fleet), "work": macs(),
           "files": {k: {"fp32_bytes": os.path.getsize(a), "int8_bytes": os.path.getsize(b)} for k, (a, b) in made.items()},
           "cpu": "Apple M4 (this machine) - not a RevPi; one thread stands in for its situation, not its speed",
           "seconds": round(time.time() - t0, 1)}
    print("statistics", doc["statistics"])
    with open(os.path.join(OUT, "edge.json"), "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    print(f"  {doc['seconds']} s")
    return doc


if __name__ == "__main__":
    main()
