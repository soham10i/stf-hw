"""
The Upgrade 8 network: a small causal temporal CNN.

  input   the last WINDOW orders x N_FEAT features, normalised
  encoder 4 causal 1-D convolutions, kernel 3, dilation 1-2-4-8 (receptive
          field 31 orders), ReLU, a residual connection from block 2
  heads   remaining useful life per component (orders, 0..RUL_CAP) and a
          health class per component (healthy / degrading / critical)
  decoder (pre-training only) reconstructs the masked input steps

Everything is plain Conv1d + Linear + ReLU so the same forward pass is easy to
run on the RevPi (ONNX) and in the browser (the weights as JSON, ml.ts).
"""
import torch
import torch.nn as nn
import torch.nn.functional as F

WINDOW = 48
RUL_CAP = 300.0
CH = 32


class CausalConv(nn.Module):
    def __init__(self, cin, cout, dil):
        super().__init__()
        self.pad = 2 * dil
        self.conv = nn.Conv1d(cin, cout, 3, dilation=dil)

    def forward(self, x):
        return self.conv(F.pad(x, (self.pad, 0)))


class Net(nn.Module):
    def __init__(self, n_feat, n_comp):
        super().__init__()
        self.n_comp = n_comp
        self.c1 = CausalConv(n_feat, CH, 1)
        self.c2 = CausalConv(CH, CH, 2)
        self.c3 = CausalConv(CH, CH, 4)
        self.c4 = CausalConv(CH, CH, 8)
        self.fc = nn.Linear(2 * CH, 64)
        self.rul = nn.Linear(64, n_comp)
        self.cls = nn.Linear(64, n_comp * 3)
        self.dec = nn.Conv1d(CH, n_feat, 1)

    def encode(self, x):                      # x: B x F x T
        h1 = F.relu(self.c1(x))
        h2 = F.relu(self.c2(h1))
        h3 = F.relu(self.c3(h2))
        h4 = F.relu(self.c4(h3)) + h2         # residual
        return h4

    def heads(self, h):
        z = torch.cat([h[:, :, -1], h.mean(dim=2)], dim=1)
        z = F.relu(self.fc(z))
        rul = torch.sigmoid(self.rul(z)) * RUL_CAP
        cls = self.cls(z).view(-1, self.n_comp, 3)
        return rul, cls

    def forward(self, x):
        return self.heads(self.encode(x))

    def reconstruct(self, x):
        return self.dec(self.encode(x))


def n_params(m):
    return sum(p.numel() for n, p in m.named_parameters() if not n.startswith("dec."))
