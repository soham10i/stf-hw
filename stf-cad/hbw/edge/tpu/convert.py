"""
Runs INSIDE the stf-edgetpu container (edge/tpu/Dockerfile), called by edge/tpu.py.

  in   /work/in.npz    the deployed weights, calibration data, the test inputs (edge/tpu.py)
  out  /work/*.tflite  full-integer TFLite (int8 in, int8 out) and the Edge TPU compilation
       /work/out.npz   the int8 TFLite interpreter's answers on the test inputs
       /work/report.json  the compiler's operator mapping, sizes, quantisation parameters

The networks are rebuilt layer for layer in Keras from the same weights (TFLite needs a TensorFlow
graph); the int8 answers are then graded on the host with the same decisions as everything else.
The Edge TPU executes the compiled model with the int8 parameters the converter chose, so the CPU
interpreter's answers are the accelerator's answers up to its own rounding - it cannot be timed
without the device.
"""
import json
import os
import re
import subprocess
import time

import numpy as np
import tensorflow as tf

K = tf.keras
W = "/work"


def tcn(z, nin, win):
    x = K.Input((win, nin), batch_size=1, name="x")       # static shapes: what the compiler maps

    def conv(h, i, d):
        w, b = z[f"tcn.c{i}.conv.weight"], z[f"tcn.c{i}.conv.bias"]
        L = K.layers.Conv1D(w.shape[0], w.shape[2], dilation_rate=d, padding="causal", activation="relu", name=f"c{i}")
        y = L(h)
        L.set_weights([w.transpose(2, 1, 0), b])
        return y

    h2 = conv(conv(x, 1, 1), 2, 2)
    h4 = K.layers.Add(name="residual")([conv(conv(h2, 3, 4), 4, 8), h2])
    last = K.layers.Cropping1D((win - 1, 0), name="last")(h4)
    last = K.layers.Reshape((h4.shape[-1],))(last)
    mean = K.layers.GlobalAveragePooling1D(name="mean")(h4)
    f = K.layers.Concatenate()([last, mean])
    f = dense(z, "tcn.fc", f, "relu")
    rul = dense(z, "tcn.rul", f, "sigmoid")                       # x RUL_CAP on the host
    cls = K.layers.Softmax()(dense(z, "tcn.cls", f, None))
    return K.Model(x, [rul, cls])


def dense(z, name, h, act):
    w, b = z[f"{name}.weight"], z[f"{name}.bias"]
    L = K.layers.Dense(w.shape[0], activation=act, name=name.split(".")[-1])
    y = L(h)
    L.set_weights([w.T, b])
    return y


def cnn(z):
    x = K.Input((64, 64, 3), batch_size=1, name="image")
    h = x
    for i in range(1, 5):
        w, b = z[f"cnn.c{i}.weight"], z[f"cnn.c{i}.bias"]
        L = K.layers.Conv2D(w.shape[0], 3, padding="same", activation="relu", name=f"c{i}")
        h = L(h)
        L.set_weights([w.transpose(2, 3, 1, 0), b])
        if i < 4:
            h = K.layers.MaxPool2D(2)(h)
    h = K.layers.GlobalAveragePooling2D()(h)
    f = dense(z, "cnn.fc", h, "relu")
    return K.Model(x, [K.layers.Softmax(name="p_flavour")(dense(z, "cnn.flav", f, None)),
                       K.layers.Softmax(name="p_condition")(dense(z, "cnn.cond", f, None))])


def int8_tflite(model, rep, path):
    c = tf.lite.TFLiteConverter.from_keras_model(model)
    c.optimizations = [tf.lite.Optimize.DEFAULT]
    c.representative_dataset = lambda: ([r[None]] for r in rep)
    c.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    c.inference_input_type = tf.int8
    c.inference_output_type = tf.int8
    b = c.convert()
    with open(path, "wb") as fh:
        fh.write(b)
    return path


def compile_tpu(path):
    r = subprocess.run(["edgetpu_compiler", "-s", "-o", W, path], capture_output=True, text=True)
    ops = []
    for line in r.stdout.splitlines():
        m = re.match(r"^([A-Z_0-9]+)\s+(\d+)\s+(.+)$", line.strip())
        if m:
            ops.append({"op": m.group(1), "count": int(m.group(2)), "status": m.group(3)})
    out = path.replace(".tflite", "_edgetpu.tflite")
    return {"ok": r.returncode == 0, "stdout": r.stdout[-4000:], "stderr": r.stderr[-2000:], "ops": ops,
            "bytes": os.path.getsize(out) if os.path.exists(out) else None,
            "version": subprocess.run(["edgetpu_compiler", "--version"], capture_output=True, text=True).stdout.strip()}


def run_int8(path, X, batch=1):
    """The int8 interpreter over X, one input at a time through the very file that was compiled;
    -> {output width: dequantized answers} (TFLite does not keep the Keras output order), seconds,
    quantisation parameters."""
    it = tf.lite.Interpreter(model_path=path, num_threads=1)          # batch 1: threads only add overhead
    inp = it.get_input_details()[0]
    s, zp = inp["quantization"]
    n = len(X)
    it.allocate_tensors()
    outs = it.get_output_details()
    res = {int(o["shape"][-1]): np.zeros((n, int(o["shape"][-1])), np.float32) for o in outs}
    q = np.clip(np.round(X / s) + zp, -128, 127).astype(np.int8)
    t0 = time.time()
    for i in range(0, n, batch):
        xb = q[i:i + batch]
        m = len(xb)
        if m < batch:                                                       # the last, partial batch
            xb = np.concatenate([xb, np.zeros((batch - m, *xb.shape[1:]), np.int8)])
        it.set_tensor(inp["index"], xb)
        it.invoke()
        for o in outs:
            so, zo = o["quantization"]
            res[int(o["shape"][-1])][i:i + m] = (it.get_tensor(o["index"])[:m].astype(np.float32) - zo) * so
    sec = time.time() - t0
    return res, sec, {"input": [float(s), int(zp)], "outputs": [[o["name"], *map(float, o["quantization"])] for o in outs]}


def main():
    z = dict(np.load(os.path.join(W, "in.npz")))
    rep = {}
    nin, win = int(z["tcn_nin"]), int(z["tcn_win"])
    t = tcn(z, nin, win)
    xc = z["tcn_cal"].transpose(0, 2, 1)                                   # N x T x NIN
    keras_err = float(np.abs(t.predict(xc[:256], batch_size=1, verbose=0)[0][:, 0] * float(z["rul_cap"]) - z["tcn_cal_rul"][:256]).max())
    p = int8_tflite(t, xc, os.path.join(W, "stf_tcn_int8.tflite"))
    rep["tcn"] = {"keras_vs_torch_max_abs_rul": keras_err, "tflite_bytes": os.path.getsize(p), "edgetpu": compile_tpu(p)}
    # the test machines: every order's window per part, rebuilt from the channels (C x T x NIN each)
    preds = {}
    tsec = 0.0
    for key in [k for k in z if k.startswith("tcn_test_")]:
        s = z[key]                                                          # C x T x NIN
        pad = np.concatenate([np.repeat(s[:, :1], win - 1, axis=1), s], axis=1)
        V = np.lib.stride_tricks.sliding_window_view(pad, win, axis=1)     # C x T x NIN x W
        C, n = V.shape[:2]
        X = np.ascontiguousarray(V.reshape(C * n, nin, win).transpose(0, 2, 1))
        out, sec, qp = run_int8(p, X)
        r, c = out[1], out[3]
        tsec += sec
        preds[key] = r[:, 0].reshape(C, n).T * float(z["rul_cap"])
        preds[key + "_cls"] = c.reshape(C, n, 3).transpose(1, 0, 2)
        rep["tcn"]["quant"] = qp
    rep["tcn"]["interpreter_s"] = round(tsec, 1)
    m = cnn(z)
    xc = z["cnn_cal"].transpose(0, 2, 3, 1)
    p = int8_tflite(m, xc, os.path.join(W, "stf_cnn_int8.tflite"))
    rep["cnn"] = {"keras_vs_torch_max_abs_p": float(np.abs(m.predict(xc[:64], batch_size=1, verbose=0)[1] - z["cnn_cal_p"][:64]).max()),
                  "tflite_bytes": os.path.getsize(p), "edgetpu": compile_tpu(p)}
    for name in ("in_domain", "shifted"):
        out, sec, qp = run_int8(p, z[f"cnn_{name}"].transpose(0, 2, 3, 1))
        pf, pc = out[3], out[5]
        preds[f"cnn_{name}_flavour"], preds[f"cnn_{name}_condition"] = pf, pc
        rep["cnn"]["quant"] = qp
    rep["tf"] = tf.__version__
    np.savez(os.path.join(W, "out.npz"), **preds)
    with open(os.path.join(W, "report.json"), "w") as fh:
        json.dump(rep, fh, indent=1)
    for k in ("tcn", "cnn"):
        e = rep[k]["edgetpu"]
        print(k, "compiled" if e["ok"] else "NOT compiled", e["ops"], e["stderr"][-300:])


if __name__ == "__main__":
    main()
