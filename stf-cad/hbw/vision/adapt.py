"""
Upgrade 15, step 3 - what to do when the drift alarm rings.

    python3 -m vision.adapt          (from stf-cad/hbw, after vision.train; or `make vision-adapt`)

Step 2 built the alarm: the autoencoder's error rises when the light, the lamp or the belt
move outside what the CNN was trained on. This step tests the ways to adapt the deployed
CNN (train.py, batch norms kept: .cache/vision_cnn_bn.pt) to the changed line (render.SHIFT),
scored on held-out images of the new line - balanced, and in the mix the line delivers
(DEFECT_RATE defective) - and on the old line, because a fix that forgets it is no fix.

  DEPLOYED      the deployed network (its batch-norm statistics lag: under new conditions it
                rejects - it fails safe)
  SOURCE        the same recipe with settled statistics (precise BN): perfect on the old
                line, but under new conditions it passes defects - the starting point here
  ADABN         no labels: re-estimate every batch norm's statistics from unlabelled frames
                of the new line (Li et al. 2016)
  ADABN, BAL.   the same, the frames first balanced by the network's own predictions
  TENT          no labels: minimise the predictions' entropy, training only the batch
                norms' scale and shift (Wang et al. 2021)
  SELF-TRAIN    fine-tune the final layers on the network's own confident answers
  FEW LABELS    a person labels k frames per condition; fine-tune the final layers (the
                feature extractor and its statistics stay), old images replayed
  RETRAINED     trained from scratch with the new conditions included (the ceiling)
and the decision itself: the pass threshold traded between escapes and false rejects, and
a fail-safe rule once the alarm rings - what the autoencoder finds unusual goes to a person.
Rendered images only: the method, not the accuracy on a real camera.
Writes web/public/vision/adapt.json.
"""
import base64
import json
import os
import time

import numpy as np
import torch
import torch.nn.functional as F

from vision import render as R
from vision.autoencoder import AE
from vision.train import BATCH, BN_STATE, EPOCHS, LR, PRECISE_N, Net, n_params, predict, score, settle, verdicts

OUT = os.path.join(os.path.dirname(R.__file__), "..", "..", "..", "web", "public", "vision", "adapt.json")
ORACLE = os.path.join(os.path.dirname(BN_STATE), "vision_oracle_bn.pt")
SEED = 41
TRAIN_N, VAL_N, TEST_N = 24000, 3000, 3000
U_N = 1500                  # unlabelled frames of the new line
DEFECT_RATE = 0.15          # the line's mix
KS = [2, 5, 10, 20]         # labelled frames per condition
REPEATS = 3
THRESHOLDS = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99]
DEV = "mps" if torch.backends.mps.is_available() else "cpu"
HEAD = ("fc", "flav", "cond")


def stream(n, seed, ranges, defect=DEFECT_RATE):
    """n frames as a line delivers them: flavours in turn, a defect with probability `defect`."""
    rnd = np.random.default_rng(seed)
    X = np.empty((n, 3, R.N, R.N), np.float32)
    yf, yc = np.empty(n, np.int64), np.empty(n, np.int64)
    for i in range(n):
        f = i % len(R.FLAVOURS)
        c = 1 + int(rnd.integers(len(R.CONDITIONS) - 1)) if rnd.random() < defect else 0
        X[i] = R.render(R.FLAVOURS[f], R.CONDITIONS[c], rnd, ranges).transpose(2, 0, 1)
        yf[i], yc[i] = f, c
    return X, yf, yc


def load(state):
    net = Net(ref=True)
    net.load_state_dict(state)
    return net.to(DEV).eval()


def clone(net):
    return load({k: v.clone() for k, v in net.state_dict().items()})


def train_oracle():
    """train.py's recipe on old + new conditions, precise BN; cached."""
    if os.path.exists(ORACLE):
        return load(torch.load(ORACLE))
    parts = [R.dataset(TRAIN_N // 2, SEED + k, r) for k, r in enumerate((R.WIDE, R.SHIFT))]
    X, yf, yc = (np.concatenate([p[i] for p in parts]) for i in range(3))
    Xva, fva, cva = R.dataset(VAL_N, SEED + 10, R.SHIFT)
    torch.manual_seed(SEED)
    net = Net(ref=True).to(DEV)
    opt = torch.optim.Adam(net.parameters(), lr=LR)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, EPOCHS)
    Xt, Ft, Ct = (torch.from_numpy(a) for a in (X, yf, yc))
    best, state = -1.0, None
    for _ in range(EPOCHS):
        net.train()
        perm = torch.randperm(len(Xt))
        for i in range(0, len(Xt), BATCH):
            idx = perm[i:i + BATCH]
            x = Xt[idx].to(DEV)
            if torch.rand(1).item() < 0.5:
                x = x.flip(3)
            a, b = net(x)
            loss = F.cross_entropy(a, Ft[idx].to(DEV)) + F.cross_entropy(b, Ct[idx].to(DEV))
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()
        cal = settle(net, X[np.random.default_rng(0).choice(len(X), PRECISE_N, replace=False)])
        pf, pc = predict(cal, Xva)
        acc = float(((pf.argmax(1) == fva) & (pc.argmax(1) == cva)).mean())
        if acc > best:
            best, state = acc, {k: v.detach().cpu().clone() for k, v in cal.state_dict().items()}
    torch.save(state, ORACLE)
    return load(state)


def tent(net, U, steps=2, lr=1e-3, seed=0):
    """Entropy minimisation on unlabelled frames; only the batch norms' scale and shift learn."""
    net = clone(net)
    params = [p for bn in net.bn for p in (bn.weight, bn.bias)]
    for p in net.parameters():
        p.requires_grad_(False)
    for p in params:
        p.requires_grad_(True)
    opt = torch.optim.Adam(params, lr=lr)
    g = torch.Generator().manual_seed(seed)
    Ut = torch.from_numpy(U)
    for _ in range(steps):
        net.train()
        perm = torch.randperm(len(Ut), generator=g)
        for i in range(0, len(Ut), 64):
            a, b = net(Ut[perm[i:i + 64]].to(DEV))
            ent = sum(-(F.softmax(z, 1) * F.log_softmax(z, 1)).sum(1).mean() for z in (a, b))
            opt.zero_grad()
            ent.backward()
            opt.step()
    for p in net.parameters():
        p.requires_grad_(True)
    return net.eval()


def head_fit(net, X, yf, yc, replay, epochs, lr=1e-3, seed=0):
    """Fine-tune only the final layers; the feature extractor and its statistics stay."""
    net = clone(net)
    opt = torch.optim.Adam([p for n, p in net.named_parameters() if n.split(".")[0] in HEAD], lr=lr)
    g = torch.Generator().manual_seed(seed)
    Xt, Ft, Ct = (torch.from_numpy(a) for a in (X, yf, yc))
    bs = min(64, len(Xt))
    for _ in range(epochs):
        net.eval()                                       # batch norms in inference mode throughout
        perm = torch.randperm(len(Xt), generator=g)
        for i in range(0, len(Xt), bs):
            idx = perm[i:i + bs]
            j = torch.randint(len(replay[0]), (len(idx),), generator=g).numpy()
            x = torch.cat([Xt[idx], torch.from_numpy(replay[0][j])]).to(DEV)
            f = torch.cat([Ft[idx], torch.from_numpy(replay[1][j])]).to(DEV)
            c = torch.cat([Ct[idx], torch.from_numpy(replay[2][j])]).to(DEV)
            if torch.rand(1, generator=g).item() < 0.5:
                x = x.flip(3)
            a, b = net(x)
            loss = F.cross_entropy(a, f) + F.cross_entropy(b, c)
            opt.zero_grad()
            loss.backward()
            opt.step()
    return net.eval()


def labelled(k, seed):
    rnd = np.random.default_rng(seed)
    n = k * len(R.CONDITIONS)
    X = np.empty((n, 3, R.N, R.N), np.float32)
    yf, yc = np.empty(n, np.int64), np.empty(n, np.int64)
    for i in range(n):
        f, c = int(rnd.integers(len(R.FLAVOURS))), i % len(R.CONDITIONS)
        X[i] = R.render(R.FLAVOURS[f], R.CONDITIONS[c], rnd, R.SHIFT).transpose(2, 0, 1)
        yf[i], yc[i] = f, c
    return X, yf, yc


def brief(net, tests):
    out = {}
    for k, (X, yf, yc) in tests.items():
        s = score(*predict(net, X), yf, yc)
        out[k] = {m: s[m] for m in ("condition_acc", "flavour_acc", "false_reject", "escape_rate", "to_person", "recall")}
    return out


def tradeoff(net, X, yc):
    """Escapes and false rejects as the pass threshold on p(ok) rises."""
    pc = predict(net, X)[1]
    ok, bad = pc[:, R.CONDITIONS.index("ok")], yc != R.CONDITIONS.index("ok")
    return [{"p": p, "escapes": round(float(((ok >= p) & bad).sum() / bad.sum()), 4),
             "false_rejects": round(float(((ok < p) & ~bad).sum() / (~bad).sum()), 4)} for p in THRESHOLDS]


def _f32(b):
    return torch.from_numpy(np.frombuffer(base64.b64decode(b), dtype="<f4").copy())


def deployed():
    """The deployed network (batch norms folded), from web/public/vision/weights.json."""
    W = json.load(open(os.path.join(os.path.dirname(OUT), "weights.json")))
    net = Net(bn=False, ref=True)
    net.load_state_dict({f"{n}.{k}": _f32(l[k[0]]).reshape(l["shape"]) if k == "weight" else _f32(l["b"])
                         for n, l in W["layers"].items() for k in ("weight", "bias")})
    return net.to(DEV).eval()


def autoencoder():
    """Step 2's autoencoder and its anomaly threshold (web/public/vision/autoencoder.json)."""
    W = json.load(open(os.path.join(os.path.dirname(OUT), "autoencoder.json")))
    ae = AE()
    ae.load_state_dict({f"{n}.{k}": _f32(l[k[0]]).reshape(l["shape"]) if k == "weight" else _f32(l["b"])
                        for n, l in W["layers"].items() for k in ("weight", "bias")})
    return ae.to(DEV).eval(), W["threshold"]


def guarded(net, ae, thr, X, yc):
    """The fail-safe rule once the drift alarm rings: a cookie the CNN would pass but the
    autoencoder finds unusual goes to a person instead."""
    v = verdicts(predict(net, X)[1])
    with torch.no_grad():
        a = np.concatenate([ae.score(torch.from_numpy(X[i:i + 500]).to(DEV))[0].cpu().numpy() for i in range(0, len(X), 500)])
    ok = R.CONDITIONS.index("ok")
    bad, good = yc != ok, yc == ok
    out = {}
    for name, vv in (("CNN alone", v), ("CNN + autoencoder", np.where((v == "pass") & (a > thr), "check", v))):
        out[name] = {"escapes": round(float(((vv == "pass") & bad).sum() / bad.sum()), 4),
                     "false_rejects": round(float(((vv == "reject") & good).sum() / good.sum()), 4),
                     "to_person": round(float((vv == "check").mean()), 4),
                     "good_to_person": round(float(((vv == "check") & good).sum() / good.sum()), 4)}
    return out


def _b64(t):
    return base64.b64encode(t.detach().cpu().numpy().astype("<f4").tobytes()).decode()


def main():
    t0 = time.time()
    src = load(torch.load(BN_STATE))                            # settled statistics (train.py saves it settled)
    dep = deployed()
    tests = {"old line": R.dataset(TEST_N, SEED + 2, R.WIDE), "new line": R.dataset(TEST_N, SEED + 3, R.SHIFT),
             "new line, as delivered": stream(TEST_N, SEED + 5, R.SHIFT)}
    U = stream(U_N, SEED + 4, R.SHIFT)[0]                          # unlabelled: the labels are never read
    replay = R.dataset(4000, SEED + 7, R.WIDE)
    res = {"deployed": brief(dep, tests), "source": brief(src, tests)}
    ada = settle(src, U)
    res["adabn"] = brief(ada, tests)
    pf, pc = predict(src, U)
    p = pc.argmax(1)
    w = 1.0 / np.bincount(p, minlength=len(R.CONDITIONS))[p]
    bal = U[np.random.default_rng(1).choice(len(U), len(U), p=w / w.sum())]
    res["adabn, balanced"] = brief(settle(src, bal), tests)
    res["tent"] = brief(tent(ada, U), tests)
    keep = (pf.max(1) >= 0.9) & (pc.max(1) >= 0.9)
    res["self-training"] = brief(head_fit(src, U[keep], pf.argmax(1)[keep], p[keep], replay, epochs=2, seed=1), tests)
    curve = []
    for k in KS:
        runs = [brief(head_fit(src, *labelled(k, 100 + 10 * k + r), replay, epochs=max(4, 300 // (k * 5)), seed=r), tests)
                for r in range(REPEATS)]
        avg = {d: {m: round(float(np.mean([x[d][m] for x in runs])), 4) for m in ("condition_acc", "false_reject", "escape_rate")} for d in tests}
        sd = {d: round(float(np.std([x[d]["condition_acc"] for x in runs])), 4) for d in tests}
        curve.append({"k": k, "labels": k * len(R.CONDITIONS), **avg, "sd": sd})
        if k == 10:
            res["few labels"] = runs[0]
    oracle = train_oracle()
    res["retrained"] = brief(oracle, tests)
    Xd, _, cd = tests["new line, as delivered"]
    trade = {"deployed": tradeoff(dep, Xd, cd), "source": tradeoff(src, Xd, cd), "retrained": tradeoff(oracle, Xd, cd)}
    ae, thr = autoencoder()
    guard = {"deployed": guarded(dep, ae, thr, Xd, cd), "source": guarded(src, ae, thr, Xd, cd)}
    meta = {"source_params": n_params(src), "u_n": U_N, "defect_rate": DEFECT_RATE, "self_kept": int(keep.sum()),
            "predicted_mix": np.bincount(p, minlength=len(R.CONDITIONS)).tolist(), "ks": KS, "repeats": REPEATS,
            "precise_bn": PRECISE_N, "seconds": round(time.time() - t0), "device": DEV,
            "methods": {"deployed": "the deployed network (lagging batch-norm statistics: fails safe)",
                        "source": "the same recipe with settled statistics (precise BN): the starting point of every adaptation",
                        "adabn": "batch-norm statistics re-estimated on unlabelled frames of the new line",
                        "adabn, balanced": "the same, frames balanced by the network's own predictions",
                        "tent": "entropy minimisation on unlabelled frames (batch-norm scale and shift), after AdaBN",
                        "self-training": "final layers fine-tuned on the network's confident answers",
                        "few labels": "final layers fine-tuned on 10 labelled frames per condition, old images replayed",
                        "retrained": "trained from scratch on old + new conditions"},
            "limits": "rendered images only: the method, not the accuracy on a real camera"}
    W = {"classes": {"flavour": R.FLAVOURS, "condition": R.CONDITIONS}, "size": R.N, "ref": R.REF,
         "pass_p": 0.5, "sure_p": 0.6, "layers": {}, "bn": [], "adabn": []}
    for name in ("c1", "c2", "c3", "c4", "fc", "flav", "cond"):
        m = getattr(src, name)
        W["layers"][name] = {"shape": list(m.weight.shape), "w": _b64(m.weight), "b": _b64(m.bias)}
    for bn, ab in zip(src.bn, ada.bn, strict=True):
        W["bn"].append({"gamma": _b64(bn.weight), "beta": _b64(bn.bias), "mean": _b64(bn.running_mean), "var": _b64(bn.running_var), "eps": bn.eps})
        W["adabn"].append({"mean": _b64(ab.running_mean), "var": _b64(ab.running_var)})
    Xp, _, _ = stream(6, SEED + 90, R.SHIFT, defect=0.5)
    with torch.no_grad():
        s, a = src(torch.from_numpy(Xp).to(DEV)), ada(torch.from_numpy(Xp).to(DEV))
    W["parity"] = {"images": [_b64(torch.from_numpy(x)) for x in Xp],
                   "source": [[s[h][i].cpu().tolist() for h in range(2)] for i in range(len(Xp))],
                   "adabn": [[a[h][i].cpu().tolist() for h in range(2)] for i in range(len(Xp))]}
    W.update({"results": res, "curve": curve, "tradeoff": trade, "guard": guard, "meta": meta})
    json.dump(W, open(OUT, "w"), separators=(",", ":"))
    for k, r in res.items():
        d, n, o = r["new line, as delivered"], r["new line"], r["old line"]
        print(f"  {k:16s} as delivered: right {d['condition_acc']:.3f} false rej {d['false_reject']:.3f} escapes {d['escape_rate']:.3f}"
              f" | balanced {n['condition_acc']:.3f} | old {o['condition_acc']:.3f}")
    for c in curve:
        print(f"  k={c['k']:2d}: delivered {c['new line, as delivered']['condition_acc']:.3f}  escapes {c['new line, as delivered']['escape_rate']:.3f}  old {c['old line']['condition_acc']:.3f}")
    print("  trade-off (source):", [(t["p"], t["escapes"], t["false_rejects"]) for t in trade["source"]])
    print("  chipped recall: source", res["source"]["new line"]["recall"]["chipped"], "retrained", res["retrained"]["new line"]["recall"]["chipped"])
    print("  guard:", json.dumps(guard))
    print(f"done in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
