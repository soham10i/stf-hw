"""The number check (services/api/verify.py) on the errors a local model really made, and on
honest arithmetic it must not flag."""

from services.api.verify import unverified

EV = (
    '{"VGR swivel gearbox": "health 99 - warns in 30.5 shifts, fails in 35.8"} '
    '{"cost with PV + battery": "€6.16", "cost, grid only": "€14.37", "self-sufficiency": "48 %"} '
    '{"text": "the line stopped 44 times (2.43 h unplanned)", "month OEE": "0.803", '
    '"load": "45.98 kWh"}'
)


def test_real_inventions_are_caught():
    # a warning threshold no tool reported, and 2.43 h misread as 2 h 43 min
    assert unverified("It warns when health drops to 70%.", EV) == ["70"]
    assert unverified("2 hours and 43 minutes unplanned.", EV) == ["43"]


def test_honest_arithmetic_and_rounding_pass():
    assert unverified("It saves €8.21 a month (€14.37 - €6.16).", EV) == []  # a difference
    assert unverified("OEE was 80.3 % and it used about 46 kWh.", EV) == []  # ratio, rounding
    assert unverified("2.43 h is 145.8 minutes.", EV) == []  # hours as minutes
    assert unverified("1. first\n2. second\n7. seventh step", EV) == []  # list numbering
    assert unverified("Since 2025 it stopped 44 times.", EV) == []  # years, evidence


def test_question_numbers_are_allowed():
    assert unverified("At 300 shifts it will have failed.", EV, "what about at 300 shifts?") == []
