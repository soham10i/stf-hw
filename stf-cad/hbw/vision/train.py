"""
Upgrade 15 - vision quality inspection: a CNN trained only on rendered images.

    python3 -m vision.train          (from stf-cad/hbw; about two minutes)

DATA     vision/render.py: TRAIN_N randomised images to learn from, three times -
         NARROW randomisation, WIDE, and WIDE with the grey reference target (the
         deployed one); what each step buys is the point, VAL_N to pick
         the epoch, and two test sets drawn once and never used to decide
         anything - TEST_N like the training images, and TEST_N under conditions
         the network never saw (render.SHIFT).
MODEL    four 3x3 convolutions (16-32-64-64, batch norm in training - folded into
         the weights for deployment - ReLU, 2x2 max-pool after the first three), global average pooling, a 64-unit layer, and two heads: the
         flavour (3) and the condition (5). Plain layers, so the same forward
         pass runs on an edge PLC (ONNX) and in the browser (vision/cnn.ts).
DECISION a cookie passes only if the condition head says ok with p >= PASS_P;
         if the head is unsure of anything (max p < SURE_P) the cookie goes to a
         person instead of being trusted either way. On a line, an ESCAPE (a
         defective cookie passed) is worse than a false reject, so the scores
         below count both.
DEPLOYED ONNX (checked with ONNX's reference evaluator) and JSON weights; the
         browser's forward pass is checked against PyTorch on the published
         test images (vision.parity, under Node).
Trained and tested on rendered images: it shows the method and the deployment
path, not the accuracy on a real camera.
"""
import base64
import json
import os
import subprocess
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from vision import render as R

OUT = os.path.expanduser("~/workspace/stf-hw/web/public/vision")
TRAIN_N, VAL_N, TEST_N = 24000, 3000, 3000
EPOCHS, BATCH, LR = 14, 128, 2e-3
PASS_P, SURE_P = 0.5, 0.6
SEED = 15
DEV = "mps" if torch.backends.mps.is_available() else "cpu"


class Net(nn.Module):
    """Trained with batch normalisation after each convolution; export() folds it into the
    convolution weights, so the deployed network is plain conv + ReLU."""

    def __init__(self, bn=True, ref=True):
        super().__init__()
        self.ref = ref
        self.c1 = nn.Conv2d(3, 16, 3, padding=1)
        self.c2 = nn.Conv2d(16, 32, 3, padding=1)
        self.c3 = nn.Conv2d(32, 64, 3, padding=1)
        self.c4 = nn.Conv2d(64, 64, 3, padding=1)
        self.bn = nn.ModuleList([nn.BatchNorm2d(c) for c in (16, 32, 64, 64)]) if bn else None
        self.fc = nn.Linear(64, 64)
        self.flav = nn.Linear(64, len(R.FLAVOURS))
        self.cond = nn.Linear(64, len(R.CONDITIONS))

    def _c(self, i, conv, x):
        x = conv(x)
        return F.relu(self.bn[i](x) if self.bn is not None else x)

    def forward(self, x):                      # x: B x 3 x 64 x 64, 0..1
        if self.ref:                           # divide out the light: the grey target reads 0.5
            g = x[:, :, :R.REF, :R.REF].mean(dim=(2, 3), keepdim=True)
            x = x * (0.5 / (g + 1e-3))
        x = x - 0.5
        x = F.max_pool2d(self._c(0, self.c1, x), 2)
        x = F.max_pool2d(self._c(1, self.c2, x), 2)
        x = F.max_pool2d(self._c(2, self.c3, x), 2)
        x = self._c(3, self.c4, x).mean(dim=(2, 3))
        x = F.relu(self.fc(x))
        return self.flav(x), self.cond(x)

    def folded(self):
        """The same network with each batch norm folded into its convolution."""
        plain = Net(bn=False, ref=self.ref)
        sd = {k: v for k, v in self.state_dict().items() if not k.startswith("bn.")}
        for i, name in enumerate(("c1", "c2", "c3", "c4")):
            bn = self.bn[i]
            g = bn.weight / torch.sqrt(bn.running_var + bn.eps)
            sd[f"{name}.weight"] = self.state_dict()[f"{name}.weight"] * g[:, None, None, None]
            sd[f"{name}.bias"] = (self.state_dict()[f"{name}.bias"] - bn.running_mean) * g + bn.bias
        plain.load_state_dict(sd)
        return plain.eval()


def n_params(net):
    return sum(p.numel() for p in net.parameters())


def predict(net, X, bs=512):
    net.eval()
    pf, pc = [], []
    with torch.no_grad():
        for i in range(0, len(X), bs):
            f, c = net(torch.from_numpy(X[i:i + bs]).to(DEV))
            pf.append(F.softmax(f, 1).cpu().numpy())
            pc.append(F.softmax(c, 1).cpu().numpy())
    return np.concatenate(pf), np.concatenate(pc)


def verdicts(pc):
    """pass / reject / check, from the condition probabilities."""
    ok = R.CONDITIONS.index("ok")
    v = np.where(pc[:, ok] >= PASS_P, "pass", "reject").astype(object)
    v[pc.max(1) < SURE_P] = "check"
    return v


def score(pf, pc, yf, yc):
    v = verdicts(pc)
    ok = R.CONDITIONS.index("ok")
    good, bad = yc == ok, yc != ok
    cm = np.zeros((len(R.CONDITIONS), len(R.CONDITIONS)), int)
    for t, p in zip(yc, pc.argmax(1), strict=True):
        cm[t, p] += 1
    return {
        "n": int(len(yc)),
        "flavour_acc": round(float((pf.argmax(1) == yf).mean()), 4),
        "flavour_acc_baked": round(float((pf.argmax(1) == yf)[yc != R.CONDITIONS.index("underbaked")].mean()), 4),
        "condition_acc": round(float((pc.argmax(1) == yc).mean()), 4),
        "escape_rate": round(float(((v == "pass") & bad).sum() / bad.sum()), 4),
        "false_reject": round(float(((v == "reject") & good).sum() / good.sum()), 4),
        "to_person": round(float((v == "check").mean()), 4),
        "recall": {c: round(float(cm[i, i] / cm[i].sum()), 4) for i, c in enumerate(R.CONDITIONS)},
        "confusion": cm.tolist(),
    }


def train(ranges, ref=True):
    """Learn from images drawn under `ranges`; test on unseen ones like them, and on SHIFT."""
    t0 = time.time()
    Xtr, ftr, ctr = R.dataset(TRAIN_N, SEED, ranges)
    Xva, fva, cva = R.dataset(VAL_N, SEED + 1, ranges)
    Xte, fte, cte = R.dataset(TEST_N, SEED + 2, ranges)
    Xsh, fsh, csh = R.dataset(TEST_N, SEED + 3, R.SHIFT)
    gen_s = round(time.time() - t0, 1)
    torch.manual_seed(SEED)
    net = Net(ref=ref).to(DEV)
    opt = torch.optim.Adam(net.parameters(), lr=LR)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, EPOCHS)
    Xt, Ft, Ct = (torch.from_numpy(a) for a in (Xtr, ftr, ctr))
    best, best_state, log = -1.0, None, []
    t1 = time.time()
    for ep in range(EPOCHS):
        net.train()
        perm = torch.randperm(len(Xt))
        for i in range(0, len(Xt), BATCH):
            idx = perm[i:i + BATCH]
            x = Xt[idx].to(DEV)
            if torch.rand(1).item() < 0.5:                 # a cookie is the same cookie mirrored
                x = x.flip(3)
            f, c = net(x)
            loss = F.cross_entropy(f, Ft[idx].to(DEV)) + F.cross_entropy(c, Ct[idx].to(DEV))
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()
        pf, pc = predict(net, Xva)
        acc = float(((pf.argmax(1) == fva) & (pc.argmax(1) == cva)).mean())
        log.append({"epoch": ep + 1, "val_both": round(acc, 4)})
        if acc > best:                                   # the epoch is chosen on validation only
            best, best_state = acc, {k: v.detach().clone() for k, v in net.state_dict().items()}
    net.load_state_dict(best_state)
    net = net.cpu().eval().folded().to(DEV)               # what is deployed is what is tested
    train_s = round(time.time() - t1, 1)
    res = {"in_domain": score(*predict(net, Xte), fte, cte), "shifted": score(*predict(net, Xsh), fsh, csh)}
    return net, res, log, gen_s, train_s


# ------------------------------------------------------------- export
def _b64(t):
    return base64.b64encode(t.detach().cpu().numpy().astype("<f4").tobytes()).decode()


def export(net, res, log, gen_s, train_s, steps):
    os.makedirs(OUT, exist_ok=True)
    net = net.cpu().eval()
    W = {"classes": {"flavour": R.FLAVOURS, "condition": R.CONDITIONS}, "size": R.N, "pass_p": PASS_P, "sure_p": SURE_P,
         "ref": R.REF if net.ref else 0,
         "layers": {}}
    for name, m in net.named_children():
        if m is not None and hasattr(m, "weight"):
            W["layers"][name] = {"shape": list(m.weight.shape), "w": _b64(m.weight), "b": _b64(m.bias)}
    with open(os.path.join(OUT, "weights.json"), "w") as f:
        json.dump(W, f, separators=(",", ":"))
    # ONNX for the edge, checked with ONNX's own reference evaluator
    import onnx
    from onnx.reference import ReferenceEvaluator
    probe = torch.from_numpy(R.dataset(8, 99)[0])
    path = os.path.join(OUT, "stf_vision_cnn.onnx")
    torch.onnx.export(net, (probe,), path, input_names=["image"], output_names=["flavour", "condition"],
                      dynamic_axes={"image": {0: "n"}}, opset_version=17, dynamo=False)
    o = ReferenceEvaluator(onnx.load(path)).run(None, {"image": probe.numpy()})
    with torch.no_grad():
        t = net(probe)
    onnx_err = float(max(np.abs(o[i] - t[i].numpy()).max() for i in range(2)))
    # the published test images: a sheet the browser classifies live, with PyTorch's answers
    rnd = np.random.default_rng(SEED + 4)
    tiles, labels = [], []
    for shift in (False, True):
        for k in range(48):
            fl, co = k % 3, (k // 3) % 5
            img = R.render(R.FLAVOURS[fl], R.CONDITIONS[co], rnd, R.SHIFT if shift else R.TRAIN)
            tiles.append(np.round(img * 255) / 255)          # as the PNG stores it, for the parity check
            labels.append({"flavour": fl, "condition": co, "shifted": shift})
    X = np.stack([t_.transpose(2, 0, 1) for t_ in tiles]).astype(np.float32)
    with torch.no_grad():
        f, c = net(torch.from_numpy(X))
    for i, lb in enumerate(labels):
        lb["torch_flavour"] = [round(float(v), 5) for v in f[i]]
        lb["torch_condition"] = [round(float(v), 5) for v in c[i]]
    cols = 12
    rows = [np.concatenate(tiles[r * cols:(r + 1) * cols], axis=1) for r in range(len(tiles) // cols)]
    with open(os.path.join(OUT, "test.png"), "wb") as fh:
        fh.write(R.png(np.concatenate(rows, axis=0)))
    meta = {
        "method": "CNN trained only on rendered images (domain randomisation); tested once on unseen images, "
                  "and on images drawn outside the training ranges",
        "model": {"params": n_params(net), "layers": "conv3x3 16-32-64-64, maxpool x3, GAP, fc 64, two heads",
                  "onnx_bytes": os.path.getsize(path), "onnx_max_abs_err": onnx_err, "device": DEV},
        "data": {"train": TRAIN_N, "val": VAL_N, "test": TEST_N, "generate_s": gen_s, "size_px": R.N, "fov_mm": R.MM},
        "train_s": train_s, "log": log, "results": res, "pass_p": PASS_P, "sure_p": SURE_P,
        "steps": steps, "train_ranges": R.TRAIN, "narrow_ranges": R.NARROW, "shift_ranges": R.SHIFT,
        "sheet": {"cols": cols, "tile": R.N, "labels": labels},
        "limits": "rendered images only: the renderer's faults and lighting are ASSUMED. It shows the method and the "
                  "deployment path, not the accuracy on a real camera.",
    }
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(meta, f, indent=1)
    return meta


def parity():
    """The browser's forward pass (web/src/vision/cnn.ts) against PyTorch, under Node."""
    web = os.path.expanduser("~/workspace/stf-hw/web")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".cache", "vision-parity.mjs")
    subprocess.run(["npx", "esbuild", "scripts/vision-parity.ts", "--bundle", "--platform=node", "--format=esm",
                    f"--outfile={out}", "--log-level=warning"], cwd=web, check=True)
    r = subprocess.run(["node", out, OUT], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


if __name__ == "__main__":
    # the comparison is the point: what each step buys under conditions never seen in training
    _, narrow, _, _, _ = train(R.NARROW, ref=False)
    _, wide, _, _, _ = train(R.WIDE, ref=False)
    net, res, log, gen_s, train_s = train(R.WIDE, ref=True)          # the deployed network
    meta = export(net, res, log, gen_s, train_s, {"narrow": narrow, "wide": wide})
    p = parity()
    meta["model"]["browser_max_abs_err"] = p["max_abs_err"]
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(meta, f, indent=1)
    print(f"data {gen_s}s, train {train_s}s on {DEV}, {n_params(net)} params, onnx err {meta['model']['onnx_max_abs_err']:.1e}, "
          f"browser err {p['max_abs_err']:.1e}")
    for k, s in [("narrow/shift", narrow["shifted"]), ("wide/shift", wide["shifted"]),
                 ("deployed/in", res["in_domain"]), ("deployed/shift", res["shifted"])]:
        print(f"{k:10s} flavour {s['flavour_acc']:.3f} (baked {s['flavour_acc_baked']:.3f})  condition {s['condition_acc']:.3f}  "
              f"escape {s['escape_rate']:.3f}  false reject {s['false_reject']:.3f}  to a person {s['to_person']:.3f}")
        print("           recall", s["recall"])
