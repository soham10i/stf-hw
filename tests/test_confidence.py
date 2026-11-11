"""The answer confidence (confidence.py): a logistic score over the checks' signals, its fit and
its calibration measures."""

from __future__ import annotations

import random

import pytest

from services.api.agent import confidence as CF

from .test_claims import check

GOOD_CLAIM = "The colour sensor gives a brightness reading in millivolts, not a colour."


def test_a_grounded_answer_scores_above_an_invented_one():
    good = check("The colour sensor gives a brightness reading in millivolts, not a colour.")
    bad = check("The colour sensor was invented by Marie Curie in Vienna during the war.")
    hi = CF.confidence(CF.features(good, [], "relevant"))
    lo = CF.confidence(CF.features(bad, [], "relevant"))
    assert 0.0 <= lo < 0.5 < hi <= 1.0


def test_an_unbacked_number_and_a_none_verdict_lower_it():
    r = check("The colour sensor gives a brightness reading in millivolts, not a colour.")
    base = CF.confidence(CF.features(r, [], "relevant"))
    assert CF.confidence(CF.features(r, ["1400"], "relevant")) < base
    assert CF.confidence(CF.features(r, [], "none")) < base


def test_an_answer_with_nothing_to_check_has_no_confidence():
    assert CF.of(check("Hello! Happy to help."), [], "relevant") is None
    assert CF.of(None, [], None) is None
    assert CF.of(check(GOOD_CLAIM), [], "relevant") > 0.5


def test_the_features_of_no_report_are_neutral():
    x = CF.features(None, None, None)
    assert x["groundedness"] == 1.0 and x["retrieval"] == 0.5 and x["numbers_ok"] == 1.0
    assert set(x) == set(CF.FEATURES)


def test_the_fit_finds_the_signal_and_calibrates():
    rnd = random.Random(7)
    xs, ys = [], []
    for _ in range(400):
        g = rnd.random()
        x = {k: 0.5 for k in CF.FEATURES} | {"groundedness": g}
        xs.append(x)
        ys.append(int(rnd.random() < g))  # backed with probability g: calibrated by design
    w = CF.fit(xs, ys)
    assert w["groundedness"] > 2.0
    ps = [CF.confidence(x, w) for x in xs]
    assert CF.ece(ps, ys) < 0.08 and CF.auroc(ps, ys) > 0.7
    assert CF.brier(ps, ys) < CF.brier([0.5] * len(ys), ys)


def test_the_measures_on_known_values():
    assert CF.brier([1.0, 0.0], [1, 0]) == 0.0 and CF.brier([0.0], [1]) == 1.0
    assert CF.auroc([0.9, 0.8, 0.1], [1, 1, 0]) == 1.0
    assert CF.auroc([0.5, 0.5], [1, 0]) == 0.5 and CF.auroc([0.3], [1]) is None
    assert CF.ece([0.9] * 10, [1] * 9 + [0]) == pytest.approx(0.0, abs=1e-9)


def test_without_a_fitted_file_the_defaults_stand(monkeypatch, tmp_path):
    monkeypatch.setattr(CF, "WEIGHTS_PATH", str(tmp_path / "none.json"))
    CF.reset_weights()
    try:
        assert CF.get_weights() == CF.DEFAULT
    finally:
        CF.reset_weights()
