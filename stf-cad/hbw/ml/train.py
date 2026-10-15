"""
Upgrade 8 - semi-supervised deep learning for predictive maintenance.

    STF_VARIANT=up7 python3 -m ml.train        (from stf-cad/hbw)

DATA     80 simulated machines (ml/fleet.py), run to failure: 64 train, 16
         test. Of the 64, only N_LABELED have failure records (a maintenance
         log); the rest are sensor data only.
INPUT    channel-independent (as PatchTST): one shared network looks at ONE
         component at a time - its health h = (r - 1) / (r_fail - 1), where
         r_fail is the limit the machine already knows (the U4 watchdog, the
         breaker, the pump, the colour band) - plus the shared context
         (hall temperature, vacuum losses, order time) and the component's
         identity. Every failure of every component then teaches the same
         "approach to the limit" pattern. (A first version gave each component
         its own output from all signals at once: the rarely-failing ones -
         the Sauger cylinder, the pusher, the RFID heads - never learned.)
LABELS   remaining useful life in orders, capped at RUL_CAP, censored where
         the run ends too soon to know; health class critical <= CRIT orders,
         degrading <= DEGR, else healthy.
TRAINING (1) self-supervised pre-training: masked reconstruction on ALL
             training machines;
         (2) supervised fine-tuning on the labelled machines;
         (3) Mean Teacher (Tarvainen & Valpola, NeurIPS 2017): the student
             also matches an exponential-moving-average teacher on the
             unlabelled machines under input noise.
         References with the same network and budget: supervised-only on the
         labelled machines, and an "oracle" given every training label.
GRADED   on the 16 unseen machines against the U6 rule monitor: remaining-
         life error, class F1, and the decision itself - for every failure,
         did an alarm come at least a shift ahead; how many alarms came where
         no failure followed.
DEPLOYED ONNX (RevPi) and JSON weights (the dashboard runs the same forward
         pass in TypeScript); both checked against PyTorch.
Trained and tested on SIMULATED machines: it shows the method and the
deployment path, not the accuracy on the real cell.
"""
import json
import math
import os
import time

import numpy as np
import torch
import torch.nn.functional as F

import month as M
from ml import fleet
from ml.model import CH, RUL_CAP, WINDOW, Net, n_params

OUT = os.path.expanduser("~/workspace/stf-hw/web/public/ml")
N_RUNS, N_TRAIN, N_LABELED = 80, 64, 8
CRIT, DEGR = 45, 150            # orders: ~1 shift, ~3 shifts
ALARM_RUL = 90                  # alarm when the predicted life is under 2 shifts...
ALARM_RUN = 3                   # ...for 3 orders in a row
SEED = 7
DEV = "mps" if torch.backends.mps.is_available() else "cpu"
COMPS = fleet.COMPS
C = len(COMPS)
R_FAIL = np.array([M.COMP[k]["r_fail"] for k in COMPS], dtype=np.float32)
I_TEMP, I_VAC, I_OT = M.FEATURES.index("temp_c"), M.FEATURES.index("vacuum_loss"), M.FEATURES.index("order_time_ratio")
INPUTS = ["h", "temp_c (normalised)", "vacuum_loss", "order_time_ratio (normalised)"] + [f"is_{k}" for k in COMPS]
N_IN = len(INPUTS)
NEAR_W = 10.0


def next_fail(n, fails, k):
    fi = sorted(i for i, kk in fails if kk == k)
    out, j = [None] * n, 0
    for i in range(n):
        while j < len(fi) and fi[j] < i:
            j += 1
        out[i] = fi[j] if j < len(fi) else None
    return out


def labels(n, fails):
    """Remaining life to the next failure of each component, capped at
    RUL_CAP; NaN where the run ends too soon to know (censored)."""
    rul = np.full((n, C), np.nan, dtype=np.float32)
    for c, k in enumerate(COMPS):
        nf = next_fail(n, fails, k)
        for i in range(n):
            if nf[i] is not None:
                rul[i, c] = min(RUL_CAP, nf[i] - i)
            elif n - i > RUL_CAP:
                rul[i, c] = RUL_CAP
    cls = np.full((n, C), -1, dtype=np.int64)
    ok = ~np.isnan(rul)
    cls[ok] = np.where(rul[ok] <= CRIT, 2, np.where(rul[ok] <= DEGR, 1, 0))
    return rul, cls


def channels(x, ctx_mu, ctx_sd):
    """raw month.FEATURES rows (T x 18) -> per component input (C x T x N_IN)."""
    T = len(x)
    h = (x[:, :C] - 1.0) / (R_FAIL - 1.0)
    ctx = np.stack([(x[:, I_TEMP] - ctx_mu[0]) / ctx_sd[0], x[:, I_VAC], (x[:, I_OT] - ctx_mu[1]) / ctx_sd[1]], 1)
    out = np.zeros((C, T, N_IN), dtype=np.float32)
    for c in range(C):
        out[c, :, 0] = h[:, c]
        out[c, :, 1:4] = ctx
        out[c, :, 4 + c] = 1.0
    return out


class Data:
    def __init__(self):
        t = time.time()
        self.X, self.F, self.R = fleet.build(N_RUNS)
        self.gen_s = round(time.time() - t, 1)
        tr = np.concatenate(self.X[:N_TRAIN])
        self.ctx_mu = np.array([tr[:, I_TEMP].mean(), tr[:, I_OT].mean()], dtype=np.float32)
        self.ctx_sd = np.array([tr[:, I_TEMP].std(), tr[:, I_OT].std()], dtype=np.float32) + 1e-6
        self.V = []
        for x in self.X:
            s = channels(x, self.ctx_mu, self.ctx_sd)                          # C x T x N_IN
            pad = np.concatenate([np.repeat(s[:, :1], WINDOW - 1, axis=1), s], axis=1)
            self.V.append(np.lib.stride_tricks.sliding_window_view(pad, WINDOW, axis=1))   # C x T x N_IN x W
        self.Y = [labels(len(x), f) for x, f in zip(self.X, self.F)]

    def index(self, runs, stride):
        out = []
        for r in runs:
            T = len(self.X[r])
            for c in range(C):
                for t in range(0, T, stride):
                    out.append((r, c, t))
        return np.array(out, dtype=np.int64)

    def batch(self, idx, with_labels=True):
        x = torch.from_numpy(np.stack([self.V[r][c, t] for r, c, t in idx]))    # B x N_IN x W
        if not with_labels:
            return x
        rul = torch.tensor(np.array([self.Y[r][0][t, c] for r, c, t in idx]))
        cls = torch.tensor(np.array([self.Y[r][1][t, c] for r, c, t in idx]))
        return x, rul, cls


def sup_loss(net, x, r, c, cls_w):
    pr, pc = net(x)
    pr, pc = pr[:, 0], pc[:, 0]
    m = ~torch.isnan(r)
    if m.any():
        w = 1.0 + (NEAR_W - 1.0) * (r[m] < RUL_CAP).float()
        lr = (w * (pr[m] / RUL_CAP - r[m] / RUL_CAP).abs()).sum() / w.sum()
    else:
        lr = pr.sum() * 0
    lc = F.cross_entropy(pc, c, ignore_index=-1, weight=cls_w)
    return lr + 0.5 * lc


def aug(x):
    n = x.clone()
    n[:, :4] = n[:, :4] * (1 + 0.03 * torch.randn(x.shape[0], 4, 1, device=x.device)) \
        + 0.03 * torch.randn_like(n[:, :4])
    return n


def shuffled(idx, bs, g):
    p = torch.randperm(len(idx), generator=g).numpy()
    for i in range(0, len(p), bs):
        yield idx[p[i:i + bs]]


def pretrain(net, D, iu, epochs, g, log):
    opt = torch.optim.Adam(net.parameters(), 2e-3)
    for ep in range(epochs):
        tot, n = 0.0, 0
        for b in shuffled(iu, 512, g):
            x = D.batch(b, False).to(DEV)
            mask = (torch.rand(x.shape[0], 1, x.shape[2], device=DEV) < 0.15).float()
            rec = net.reconstruct(x * (1 - mask))
            loss = (((rec[:, :4] - x[:, :4]) ** 2) * mask).sum() / (mask.sum() * 4 + 1e-6)
            opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item() * len(b); n += len(b)
        log.append({"stage": "pretrain", "epoch": ep + 1, "loss": round(tot / n, 5)})


def supervised(net, D, il, epochs, g, log, stage, cls_w):
    opt = torch.optim.Adam(net.parameters(), 1e-3)
    for ep in range(epochs):
        tot, n = 0.0, 0
        for b in shuffled(il, 256, g):
            x, r, c = D.batch(b)
            loss = sup_loss(net, aug(x.to(DEV)), r.to(DEV), c.to(DEV), cls_w)
            opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item() * len(b); n += len(b)
        log.append({"stage": stage, "epoch": ep + 1, "loss": round(tot / n, 5)})


def mean_teacher(student, D, il, iu, epochs, g, log, cls_w):
    teacher = Net(N_IN, 1).to(DEV)
    teacher.load_state_dict(student.state_dict())
    for p in teacher.parameters():
        p.requires_grad_(False)
    opt = torch.optim.Adam(student.parameters(), 1e-3)
    steps = epochs * math.ceil(len(il) / 256)
    s = 0
    rng = np.random.default_rng(SEED)
    for ep in range(epochs):
        tot = cons_tot = 0.0
        n = 0
        for b in shuffled(il, 256, g):
            x, r, c = D.batch(b)
            xu = D.batch(iu[rng.integers(0, len(iu), 512)], False).to(DEV)
            lam = 4.0 * math.exp(-5 * (1 - min(1.0, s / (0.4 * steps))) ** 2)      # sigmoid ramp-up
            ls = sup_loss(student, aug(x.to(DEV)), r.to(DEV), c.to(DEV), cls_w)
            sr, sc = student(aug(xu))
            with torch.no_grad():
                tr, tc = teacher(aug(xu))
            cons = F.mse_loss(sr / RUL_CAP, tr / RUL_CAP) + F.mse_loss(sc.softmax(-1), tc.softmax(-1))
            loss = ls + lam * cons
            opt.zero_grad(); loss.backward(); opt.step()
            with torch.no_grad():
                for pt, ps in zip(teacher.parameters(), student.parameters()):
                    pt.mul_(0.99).add_(ps, alpha=0.01)
            s += 1
            tot += ls.item() * len(b); cons_tot += cons.item() * len(b); n += len(b)
        log.append({"stage": "mean teacher", "epoch": ep + 1, "loss": round(tot / n, 5),
                    "consistency": round(cons_tot / n, 5)})
    return teacher


@torch.no_grad()
def predict_run(net, D, r):
    """-> (T x C remaining life, T x C x 3 class probabilities)"""
    net.eval()
    dev = next(net.parameters()).device
    T = len(D.X[r])
    R = np.zeros((T, C), dtype=np.float32)
    P = np.zeros((T, C, 3), dtype=np.float32)
    for c in range(C):
        w = torch.from_numpy(np.ascontiguousarray(D.V[r][c]))
        for i in range(0, T, 2048):
            pr, pc = net(w[i:i + 2048].to(dev))
            R[i:i + 2048, c] = pr[:, 0].cpu().numpy()
            P[i:i + 2048, c] = pc[:, 0].softmax(-1).cpu().numpy()
    net.train()
    return R, P


def alarm_idx(rul_pred):
    """Every order at which the alarm is ACTIVE: the predicted life has been
    under ALARM_RUL for the last ALARM_RUN orders."""
    out, run = [], 0
    for i, v in enumerate(rul_pred):
        run = run + 1 if v < ALARM_RUL else 0
        if run >= ALARM_RUN:
            out.append(i)
    return out


def decisions(alarms_at, n, fails, k):
    """Per failure of k: the lead of the first alarm since its last failure.
    Alarms in the stretch after its last failure where no failure followed
    (and the run did not end within RUL_CAP) are false: one per shift at most."""
    fi = sorted(i for i, kk in fails if kk == k)
    leads, missed, start = [], 0, 0
    for f in fi:
        a = [i for i in alarms_at if start <= i <= f]
        if a:
            leads.append(f - a[0])
        else:
            missed += 1
        start = f + 1
    tail = [i for i in alarms_at if i >= start and n - i > RUL_CAP]
    return leads, len(set(i // 45 for i in tail)), missed


def summarise(name, leads, false, missed, orders, mae=None, f1=None):
    lead = np.array(leads) if leads else np.array([0])
    n_fail = len(leads) + missed
    ok = int((lead >= CRIT).sum()) if leads else 0
    out = {"name": name, "failures": n_fail, "warned_1shift": ok, "warned_1shift_pct": round(100 * ok / max(1, n_fail), 1),
           "missed": missed, "late": int((lead < CRIT).sum()) if leads else 0,
           "lead_median_orders": float(np.median(lead)) if leads else None,
           "false": false, "false_per_1000": round(1000 * false / max(1, orders), 2)}
    if mae is not None:
        out["rul_mae_orders"] = round(mae, 1)
    if f1 is not None:
        out["f1_healthy_degrading_critical"] = [round(float(x), 3) for x in f1]
        out["macro_f1"] = round(float(np.mean(f1)), 3)
    return out


def evaluate(D, preds, name):
    leads, false, missed, orders, ae, n_ae = [], 0, 0, 0, 0.0, 0
    tp, fp, fn = np.zeros(3), np.zeros(3), np.zeros(3)
    for r, (pr, pc) in preds.items():
        rul, cls = D.Y[r]
        n = len(rul)
        orders += n
        m = ~np.isnan(rul) & (rul < RUL_CAP)
        ae += float(np.abs(pr[m] - rul[m]).sum()); n_ae += int(m.sum())
        yc, pcl = cls.reshape(-1), pc.argmax(-1).reshape(-1)
        ok = yc >= 0
        for k in range(3):
            tp[k] += ((pcl == k) & (yc == k) & ok).sum()
            fp[k] += ((pcl == k) & (yc != k) & ok).sum()
            fn[k] += ((pcl != k) & (yc == k) & ok).sum()
        for c, k in enumerate(COMPS):
            l, fa, mi = decisions(alarm_idx(pr[:, c]), n, D.F[r], k)
            leads += l; false += fa; missed += mi
    f1 = [2 * tp[k] / max(1, 2 * tp[k] + fp[k] + fn[k]) for k in range(3)]
    return summarise(name, leads, false, missed, orders, ae / max(1, n_ae), f1)


def rule_eval(D, runs):
    leads, false, missed, orders = [], 0, 0, 0
    for r in runs:
        n = len(D.X[r])
        orders += n
        for k in COMPS:
            l, fa, mi = decisions(sorted(i for i, kk in D.R[r] if kk == k), n, D.F[r], k)
            leads += l; false += fa; missed += mi
    return summarise("U6 rules (EWMA + soft limit + trend)", leads, false, missed, orders)


def per_component(D, preds, runs):
    out = {}
    for c, k in enumerate(COMPS):
        leads, missed, rleads, rmissed = [], 0, [], 0
        for r in runs:
            n = len(D.X[r])
            l, _, mi = decisions(alarm_idx(preds[r][0][:, c]), n, D.F[r], k)
            leads += l; missed += mi
            l, _, mi = decisions(sorted(i for i, kk in D.R[r] if kk == k), n, D.F[r], k)
            rleads += l; rmissed += mi
        nf = len(leads) + missed
        if nf:
            out[k] = {"failures": nf, "ml_ok": int(sum(1 for x in leads if x >= CRIT)),
                      "ml_lead_median": float(np.median(leads)) if leads else None,
                      "rule_ok": int(sum(1 for x in rleads if x >= CRIT)),
                      "rule_lead_median": float(np.median(rleads)) if rleads else None}
    return out


def export_weights(net, D):
    sd = {k: v.detach().cpu().numpy() for k, v in net.state_dict().items()}
    r = lambda a: np.round(np.asarray(a, dtype=np.float64), 6).tolist()
    return {"features": M.FEATURES, "components": COMPS, "inputs": INPUTS, "window": WINDOW, "rul_cap": RUL_CAP,
            "ch": CH, "r_fail": r(R_FAIL), "ctx_mu": r(D.ctx_mu), "ctx_sd": r(D.ctx_sd),
            "i_temp": I_TEMP, "i_vac": I_VAC, "i_ot": I_OT, "alarm_rul": ALARM_RUL, "alarm_run": ALARM_RUN,
            "conv": [{"w": r(sd[f"c{i}.conv.weight"]), "b": r(sd[f"c{i}.conv.bias"]), "dil": d}
                     for i, d in zip((1, 2, 3, 4), (1, 2, 4, 8))],
            "fc": {"w": r(sd["fc.weight"]), "b": r(sd["fc.bias"])},
            "rul": {"w": r(sd["rul.weight"]), "b": r(sd["rul.bias"])},
            "cls": {"w": r(sd["cls.weight"]), "b": r(sd["cls.bias"])}}


def main():
    torch.manual_seed(SEED)
    g = torch.Generator().manual_seed(SEED)
    D = Data()
    train, test = list(range(N_TRAIN)), list(range(N_TRAIN, N_RUNS))
    lab = train[:N_LABELED]
    iu = D.index(train, 4)
    il = D.index(lab, 1)
    ia = D.index(train, 4)
    cc = np.array([D.Y[r][1][t, c] for r, c, t in il])
    cnt = np.bincount(cc[cc >= 0], minlength=3).astype(np.float32)
    cls_w = torch.tensor(np.minimum(cnt.sum() / (3 * np.maximum(cnt, 1)), 50.0), device=DEV)
    log = []
    t0 = time.time()
    pre = Net(N_IN, 1).to(DEV)
    pretrain(pre, D, iu, 3, g, log)
    semi = Net(N_IN, 1).to(DEV)
    semi.load_state_dict(pre.state_dict())
    supervised(semi, D, il, 3, g, log, "fine-tune", cls_w)
    teacher = mean_teacher(semi, D, il, iu, 8, g, log, cls_w)
    sup = Net(N_IN, 1).to(DEV)
    supervised(sup, D, il, 11, g, log, "supervised-only", cls_w)
    orc = Net(N_IN, 1).to(DEV)
    supervised(orc, D, ia, 4, g, log, "oracle", cls_w)
    train_s = round(time.time() - t0, 1)
    semi_name = "semi-supervised (pre-train + Mean Teacher)"
    models = {semi_name: teacher, f"supervised-only (same {N_LABELED} labelled machines)": sup,
              f"oracle (all {N_TRAIN} machines labelled)": orc}
    results = [rule_eval(D, test)]
    preds_all = {}
    for name, net in models.items():
        preds = {r: predict_run(net, D, r) for r in test}
        preds_all[name] = preds
        results.append(evaluate(D, preds, name))
    percomp = per_component(D, preds_all[semi_name], test)
    ck = os.path.join(os.path.dirname(__file__), "ckpt")
    os.makedirs(ck, exist_ok=True)
    for nm, m_ in (("semi", teacher), ("sup", sup), ("oracle", orc)):
        torch.save(m_.state_dict(), os.path.join(ck, f"{nm}.pt"))
    net = teacher.cpu().eval()
    # ---- deploy: ONNX for the RevPi, JSON for the browser, both checked
    os.makedirs(OUT, exist_ok=True)
    probe = torch.from_numpy(np.ascontiguousarray(D.V[test[0]][:, 500]))              # C x N_IN x W: one order
    onnx_path = os.path.join(OUT, "stf_pm_tcn.onnx")
    torch.onnx.export(net, (probe,), onnx_path, input_names=["x"], output_names=["rul", "cls"],
                      dynamic_axes={"x": {0: "batch"}}, opset_version=17, dynamo=False)
    import onnx
    from onnx.reference import ReferenceEvaluator
    o = ReferenceEvaluator(onnx.load(onnx_path)).run(None, {"x": probe.numpy()})[0]
    with torch.no_grad():
        onnx_err = float(np.abs(o - net(probe)[0].numpy()).max())
    W = export_weights(net, D)
    # the dashboard's month (Upgrade 7, with maintenance): raw inputs, and PyTorch's answer for the parity check
    mm = M.Month().run()
    mx = np.array(mm.feat, dtype=np.float32)
    s = channels(mx, D.ctx_mu, D.ctx_sd)
    pad = np.concatenate([np.repeat(s[:, :1], WINDOW - 1, axis=1), s], axis=1)
    Vm = np.lib.stride_tricks.sliding_window_view(pad, WINDOW, axis=1)
    with torch.no_grad():
        mr = np.stack([net(torch.from_numpy(np.ascontiguousarray(Vm[c])))[0][:, 0].numpy() for c in range(C)], 1)
    month_in = {"t": [o_["t"] for o_ in mm.orders], "x": np.round(mx.astype(np.float64), 5).tolist(),
                "torch_rul": np.round(mr, 3).tolist(),
                "rule_warnings": [{"t": e["t"], "comp": e["comp"]} for e in mm.events if e["kind"] == "warning"],
                "maintenance": [{"t": e["t"], "comp": e["comp"]} for e in mm.events if e["kind"] == "maintenance"]}
    # one test machine for the dashboard: truth, prediction, alarms, rule warnings
    best = max(test, key=lambda r: len(D.F[r]))
    pr, _ = preds_all[semi_name][best]
    rows = []
    for c, k in enumerate(COMPS):
        if not any(kk == k for _, kk in D.F[best]):
            continue
        rul = D.Y[best][0][:, c]
        rows.append({"comp": k, "true": [None if np.isnan(v) else round(float(v), 1) for v in rul[::3]],
                     "pred": np.round(pr[::3, c], 1).tolist(), "fails": [i for i, kk in D.F[best] if kk == k],
                     "alarms": alarm_idx(pr[:, c]), "rules": [i for i, kk in D.R[best] if kk == k]})
    res = {
        "method": "semi-supervised: masked-reconstruction pre-training, supervised fine-tuning, then Mean Teacher "
                  "consistency on the unlabelled machines (Tarvainen & Valpola, NeurIPS 2017)",
        "model": {"type": "channel-independent causal temporal CNN (4 dilated Conv1d, residual) + MLP heads",
                  "params": n_params(net), "window_orders": WINDOW, "rul_cap_orders": RUL_CAP, "inputs": INPUTS,
                  "heads": "remaining useful life + health class, for the component given",
                  "onnx_bytes": os.path.getsize(onnx_path), "onnx_max_abs_err": onnx_err, "device": DEV},
        "data": {"machines": N_RUNS, "train": N_TRAIN, "labelled": N_LABELED, "test": N_RUNS - N_TRAIN,
                 "days_each": fleet.DAYS, "orders": int(sum(len(x) for x in D.X)),
                 "failures": int(sum(len(f) for f in D.F)), "failures_labelled": int(sum(len(D.F[r]) for r in lab)),
                 "failures_test": int(sum(len(D.F[r]) for r in test)),
                 "unlabelled_windows": int(len(iu)), "labelled_windows": int(len(il)), "generate_s": D.gen_s},
        "labels": {"critical_orders": CRIT, "degrading_orders": DEGR},
        "alarm": {"rul_below_orders": ALARM_RUL, "for_orders": ALARM_RUN, "lead_needed_orders": CRIT},
        "results": results, "per_component": percomp, "log": log, "train_s": train_s,
        "showcase": {"machine": best, "stride": 3, "rows": rows},
        "limits": "trained and tested on simulated machines whose wear laws were written by hand (month.py): it shows "
                  "the semi-supervised method and the deployment path, not the accuracy on the real cell",
    }
    json.dump(W, open(os.path.join(OUT, "weights.json"), "w"), separators=(",", ":"))
    json.dump(month_in, open(os.path.join(OUT, "month_inputs.json"), "w"), separators=(",", ":"))
    json.dump(res, open(os.path.join(OUT, "results.json"), "w"), separators=(",", ":"))
    print(f"data {D.gen_s}s, train {train_s}s on {DEV}, params {n_params(net)}, onnx err {onnx_err:.2e}")
    for r_ in results:
        print(" ", {k: r_.get(k) for k in ("name", "warned_1shift", "missed", "late", "lead_median_orders", "false",
                                            "rul_mae_orders", "macro_f1")})
    for k, v in percomp.items():
        print(f"   {k:8s} {v}")


if __name__ == "__main__":
    main()
