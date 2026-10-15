"""
Upgrade 15, step 2 - an autoencoder that knows only good cookies: unsupervised anomaly and
drift detection beside the supervised CNN.

    python3 -m vision.autoencoder        (from stf-cad/hbw; a few minutes; or `make vision-live`)

The CNN can only name the five conditions it was taught, and its test showed what happens
when the light changes (30 % false rejects). An autoencoder learns to rebuild images of GOOD
cookies only - no defect labels at all - from the same light-corrected input as the CNN.
What it rebuilds badly is unusual:
  ANOMALY  a cookie whose reconstruction error is above the 99th percentile of good cookies
           is flagged - including faults it has never seen (scored on all four defect types,
           none of which it was trained on)
  DRIFT    the error of GOOD cookies rises when the conditions move away from training (the
           SHIFT images: other light, a warm lamp, blur, a worn belt) - a running mean of the
           error is a label-free alarm that the line has changed and the CNN's answers can no
           longer be trusted: the trigger to collect and label new images and retrain
           (or adapt) - the path toward self-supervised adaptation
Everything is measured on held-out rendered images; like the CNN, it shows the method, not the
accuracy on a real camera.
Writes web/public/vision/autoencoder.json (weights, threshold, results, parity samples).
"""
import base64
import json
import os
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from vision import render as R

OUT = os.path.join(os.path.dirname(R.__file__), "..", "..", "..", "web", "public", "vision", "autoencoder.json")
SEED = 31
TRAIN_N, VAL_N, TEST_N = 12000, 2000, 2500
EPOCHS, BATCH, LR = 18, 128, 2e-3
DEV = "mps" if torch.backends.mps.is_available() else "cpu"
OK = R.CONDITIONS.index("ok")
PATCH = 6                                                # px: about 7.5 mm, a chip or a crack's width


class AE(nn.Module):
    """64x64x3 -> 8x8x8 -> 64x64x3. conv3x3+ReLU+maxpool down, nearest upsample+conv3x3 up."""

    def __init__(self):
        super().__init__()
        self.e1, self.e2, self.e3 = nn.Conv2d(3, 16, 3, padding=1), nn.Conv2d(16, 32, 3, padding=1), nn.Conv2d(32, 32, 3, padding=1)
        self.e4 = nn.Conv2d(32, 8, 3, padding=1)
        self.d1, self.d2, self.d3 = nn.Conv2d(8, 32, 3, padding=1), nn.Conv2d(32, 16, 3, padding=1), nn.Conv2d(16, 16, 3, padding=1)
        self.d4 = nn.Conv2d(16, 3, 3, padding=1)

    @staticmethod
    def prep(x):                                         # the CNN's own input: light divided out, centred
        g = x[:, :, :R.REF, :R.REF].mean(dim=(2, 3), keepdim=True)
        return x * (0.5 / (g + 1e-3)) - 0.5

    def forward(self, x):
        x = self.prep(x)
        h = F.max_pool2d(F.relu(self.e1(x)), 2)
        h = F.max_pool2d(F.relu(self.e2(h)), 2)
        h = F.max_pool2d(F.relu(self.e3(h)), 2)
        h = F.relu(self.e4(h))
        h = F.relu(self.d1(F.interpolate(h, scale_factor=2, mode="nearest")))
        h = F.relu(self.d2(F.interpolate(h, scale_factor=2, mode="nearest")))
        h = F.relu(self.d3(F.interpolate(h, scale_factor=2, mode="nearest")))
        return self.d4(h), x                             # reconstruction, and its target

    def score(self, x):
        """(patch, mean): the worst 6x6 px patch of the error map - a crack or a chip is local, the
        belt's random texture is everywhere - and the whole image's mean error, the drift signal."""
        y, t = self(x)
        e = ((y - t) ** 2).mean(dim=1, keepdim=True)
        patch = F.avg_pool2d(e, PATCH, stride=2).amax(dim=(1, 2, 3))
        return patch, e.mean(dim=(1, 2, 3))


def images(n, seed, ranges, conditions):
    rnd = np.random.default_rng(seed)
    X = np.empty((n, 3, R.N, R.N), np.float32)
    yc = np.empty(n, np.int64)
    for i in range(n):
        f = R.FLAVOURS[i % len(R.FLAVOURS)]
        c = conditions[(i // len(R.FLAVOURS)) % len(conditions)]
        X[i] = R.render(f, c, rnd, ranges).transpose(2, 0, 1)
        yc[i] = R.CONDITIONS.index(c)
    return X, yc


def scores(net, X, bs=500):
    """patch scores and mean errors"""
    p, m = [], []
    with torch.no_grad():
        for i in range(0, len(X), bs):
            a, b = net.score(torch.from_numpy(X[i:i + bs]).to(DEV))
            p.append(a.cpu().numpy()); m.append(b.cpu().numpy())
    return np.concatenate(p), np.concatenate(m)


def auroc(neg, pos):
    """P(score of a random positive > score of a random negative)."""
    s = np.concatenate([neg, pos])
    r = s.argsort().argsort() + 1.0
    return float((r[len(neg):].sum() - len(pos) * (len(pos) + 1) / 2) / (len(neg) * len(pos)))


def evaluate(net, thr, seed, ranges):
    X, yc = images(TEST_N, seed, ranges, R.CONDITIONS)
    s, m = scores(net, X)
    good = s[yc == OK]
    out = {"ok_mean_error": float(m[yc == OK].mean()), "false_alarm": float((good > thr).mean()), "per_defect": {}}
    for c in R.CONDITIONS:
        if c == "ok":
            continue
        bad = s[yc == R.CONDITIONS.index(c)]
        out["per_defect"][c] = {"auroc": round(auroc(good, bad), 4), "detected": round(float((bad > thr).mean()), 4)}
    bad_all = s[yc != OK]
    out["auroc"] = round(auroc(good, bad_all), 4)
    out["detected"] = round(float((bad_all > thr).mean()), 4)
    return out


def _b64(t):
    return base64.b64encode(t.detach().cpu().numpy().astype("<f4").tobytes()).decode()


def main():
    torch.manual_seed(SEED)
    t0 = time.time()
    Xtr, _ = images(TRAIN_N, SEED, R.TRAIN, ["ok"])            # good cookies only: no defect labels
    Xva, _ = images(VAL_N, SEED + 1, R.TRAIN, ["ok"])
    gen_s = time.time() - t0
    net = AE().to(DEV)
    opt = torch.optim.Adam(net.parameters(), lr=LR)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, EPOCHS)
    Xt = torch.from_numpy(Xtr)
    log = []
    t1 = time.time()
    for ep in range(EPOCHS):
        net.train()
        perm = torch.randperm(len(Xt))
        for i in range(0, len(Xt), BATCH):
            xb = Xt[perm[i:i + BATCH]].to(DEV)
            y, t = net(xb)
            loss = F.mse_loss(y, t)
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()
        net.eval()
        v = float(scores(net, Xva)[1].mean())
        log.append({"epoch": ep + 1, "val_mse": round(v, 6)})
        print(f"  epoch {ep + 1:2d}  val mse {v:.5f}", flush=True)
    train_s = time.time() - t1
    net = net.cpu().eval()
    DEVc = DEV
    globals()["DEV"] = "cpu"
    sv, mv = scores(net, Xva)
    thr = float(np.percentile(sv, 99))
    res = {"in_domain": evaluate(net, thr, SEED + 2, R.TRAIN), "shifted": evaluate(net, thr, SEED + 3, R.SHIFT)}
    drift = res["shifted"]["ok_mean_error"] / res["in_domain"]["ok_mean_error"]
    # parity samples for the browser: four images and PyTorch's scores
    Xp, _ = images(4, SEED + 9, R.TRAIN, ["ok", "cracked", "burnt", "chipped"])
    W = {"size": R.N, "ref": R.REF, "patch": PATCH, "threshold": thr, "ok_mean_error": float(mv.mean()),
         "drift_alarm": float(2.0 * mv.mean()),
         "layers": {n: {"shape": list(m.weight.shape), "w": _b64(m.weight), "b": _b64(m.bias)}
                    for n, m in net.named_children()},
         "parity": {"images": [_b64(torch.from_numpy(x)) for x in Xp],
                    "scores": [float(v) for v in scores(net, Xp)[0]], "means": [float(v) for v in scores(net, Xp)[1]]}}
    meta = {"method": "convolutional autoencoder trained on good cookies only (no defect labels); score = "
                      "reconstruction error of the light-corrected image; threshold = 99th percentile of good cookies",
            "score": f"anomaly = the worst {PATCH}x{PATCH} px patch of the error map; drift = the mean error of good cookies",
            "model": {"params": sum(p.numel() for p in net.parameters()), "bottleneck": "8 x 8 x 8",
                      "device": DEVc},
            "data": {"train_ok_only": TRAIN_N, "val_ok": VAL_N, "test_each": TEST_N, "generate_s": round(gen_s, 1)},
            "train_s": round(train_s, 1), "log": log, "threshold": thr, "results": res,
            "drift_ratio": round(drift, 3),
            "limits": "rendered images only, like the CNN: the method, not the accuracy on a real camera"}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({**W, "meta": meta}, open(OUT, "w"), separators=(",", ":"))
    print(f"threshold {thr:.5f}; in-domain AUROC {res['in_domain']['auroc']}, detected {res['in_domain']['detected']:.1%}, "
          f"false alarms {res['in_domain']['false_alarm']:.1%}")
    print(f"shifted: AUROC {res['shifted']['auroc']}, false alarms {res['shifted']['false_alarm']:.1%}; "
          f"good-cookie error x{drift:.2f} - the drift signal")
    for c, r in res["in_domain"]["per_defect"].items():
        print(f"  {c:11s} AUROC {r['auroc']}  detected {r['detected']:.1%}   (shifted: {res['shifted']['per_defect'][c]['auroc']})")


if __name__ == "__main__":
    main()
