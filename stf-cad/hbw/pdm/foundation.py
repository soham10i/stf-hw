"""
A time-series foundation model as a second opinion on the remaining life - optional, off by default.

The statistical pipeline (model.py) knows each part's physics. A foundation model knows none of
it: pretrained on very many unrelated series, it forecasts this part's health from its history
alone, zero-shot, as quantiles. Where both agree, trust grows; where they part, a person looks.
It is also the path to parts without a physical law.

  Backend   Amazon Chronos-Bolt (Ansari et al. 2024, "Chronos: Learning the Language of Time
            Series"; Bolt is its direct multi-step successor), package `chronos-forecasting`,
            weights amazon/chronos-bolt-small from Hugging Face. Not a dependency of the project:
            install it, and run `make pdm FOUNDATION=chronos`.
  Input     the filter's health state w (model.Track.w) since the part was renewed, the last
            CONTEXT orders.
  Output    P(failure within H orders): the share of the forecast quantile levels whose path
            reaches w = 1 by H - the same number the statistical model gives, so the two are
            graded by the same decision (run.py).

Other foundation models fit the same interface (forecast quantiles of a univariate series):
TimesFM (Das et al. 2024), Moirai (Woo et al. 2024), Lag-Llama (Rasul et al. 2023), MOMENT
(Goswami et al. 2024).
"""
from __future__ import annotations

import numpy as np

CONTEXT = 512
LEVELS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


class Chronos:
    def __init__(self, model: str = "amazon/chronos-bolt-small", device: str = "cpu"):
        try:
            import torch
            from chronos import BaseChronosPipeline
        except ImportError as e:  # pragma: no cover - optional
            raise RuntimeError("the foundation-model backend needs `pip install chronos-forecasting`") from e
        self.torch = torch
        self.pipe = BaseChronosPipeline.from_pretrained(model, device_map=device, torch_dtype=torch.float32)

    def p_fail(self, w: np.ndarray, horizon: int) -> float:
        """P(the health state reaches 1 within `horizon` orders), from the forecast quantiles."""
        ctx = self.torch.tensor(np.nan_to_num(w[-CONTEXT:]), dtype=self.torch.float32)
        q, _ = self.pipe.predict_quantiles(context=ctx, prediction_length=horizon, quantile_levels=LEVELS)
        paths = q[0].numpy()                   # horizon x levels
        crossed = (paths >= 1.0).any(axis=0)   # per level: does its path reach failure in time
        # the level-q path crossing means at least (1 - q) of the mass crosses
        return float(max((1 - lv for lv, c in zip(LEVELS, crossed, strict=True) if c), default=0.0))


def p_fail_series(backend: Chronos, w: np.ndarray, horizon: int, every: int = 15) -> np.ndarray:
    """The probability along a whole track, forecast every `every` orders and held between."""
    out = np.zeros(len(w))
    last = 0.0
    for t in range(len(w)):
        if t % every == 0 and t >= 32:
            last = backend.p_fail(w[: t + 1], horizon)
        out[t] = last
    return out
