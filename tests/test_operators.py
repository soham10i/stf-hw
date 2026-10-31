"""Named operator keys and the signed session cookie (operators.py)."""

from __future__ import annotations

import pytest

from services.api import operators as O

ANA, BEN = "ana-key-" + "a" * 32, "ben-key-" + "b" * 32
SPEC = f"ana:operator:{O.key_hash(ANA)}, ben:viewer:{O.key_hash(BEN)}"


class Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def ops(spec: str = SPEC, clock: Clock | None = None, secret: bytes = b"s" * 32) -> O.Operators:
    return O.Operators({"STF_OPERATORS": spec}, secret, now=clock or Clock())


def test_the_configuration_holds_names_roles_and_hashes_only():
    by_name, problems = O.parse(SPEC + "\n carl:operator:" + O.key_hash("c" * 40))
    assert by_name == {
        "ana": ("operator", O.key_hash(ANA)), "ben": ("viewer", O.key_hash(BEN)),
        "carl": ("operator", O.key_hash("c" * 40)),
    }
    assert problems == []


@pytest.mark.parametrize("entry", [
    "ana:operator", "ana:admin:" + "0" * 64, "Ana Smith:operator:" + "0" * 64,
    "ana:operator:" + ANA, "ana:operator:" + "0" * 63,
])
def test_a_bad_entry_is_skipped_and_said_without_its_value(entry):
    by_name, problems = O.parse(entry)
    assert by_name == {} and len(problems) == 1
    assert ANA not in problems[0]


def test_a_name_twice_is_refused():
    by_name, problems = O.parse(f"ana:operator:{'0' * 64},ana:viewer:{'1' * 64}")
    assert list(by_name) == ["ana"] and "twice" in problems[0]


def test_a_key_names_its_operator_and_role():
    o = ops()
    ana, ben = o.check_key(ANA), o.check_key(BEN)
    assert (ana.name, ana.role, ana.may_approve) == ("ana", "operator", True)
    assert (ben.name, ben.role, ben.may_approve) == ("ben", "viewer", False)
    assert o.check_key("wrong") is None and o.check_key("") is None
    assert o.check_key("x" * 600) is None
    assert ana.expires_at == 1000.0 + 1800


def test_the_cookie_round_trips():
    o = ops()
    ana = o.check_key(ANA)
    assert o.read(o.issue(ana)) == ana
    header = o.cookie(ana, secure=True)
    assert header.startswith(f"{O.COOKIE}=") and "HttpOnly" in header
    assert "SameSite=Strict" in header and "Secure" in header and "Max-Age=1800" in header
    assert "Secure" not in o.cookie(ana, secure=False)
    assert "Max-Age=0" in O.Operators.clear_cookie(True)


def test_a_cookie_expires():
    clock = Clock()
    o = ops(clock=clock)
    value = o.issue(o.check_key(ANA))
    clock.t += 1799
    assert o.read(value) is not None
    clock.t += 2
    assert o.read(value) is None


def test_a_forged_or_tampered_cookie_names_nobody():
    o = ops()
    value = o.issue(o.check_key(BEN))
    payload, sig = value.split(".")
    import base64
    import json

    doc = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    promoted = O._b64(json.dumps({**doc, "r": "operator"}).encode())
    assert o.read(f"{promoted}.{sig}") is None  # the viewer made an operator: signature fails
    assert o.read(value + "x") is None and o.read("junk") is None and o.read(None) is None
    assert ops(secret=b"t" * 32).read(value) is None  # another server's key


def test_removing_an_operator_or_rotating_a_key_ends_their_session_at_once():
    o = ops()
    value = o.issue(o.check_key(ANA))
    assert ops(f"ben:viewer:{O.key_hash(BEN)}").read(value) is None  # removed
    assert ops(f"ana:operator:{O.key_hash('new-' + ANA)}").read(value) is None  # rotated
    assert ops(f"ana:viewer:{O.key_hash(ANA)}").read(value) is None  # demoted


def test_the_entry_maker_prints_a_key_and_its_entry(capsys):
    assert O.main(["Dana", "viewer"]) == 0
    out = capsys.readouterr().out.splitlines()
    key = out[0].split()[-1]
    entry = out[1].split()[-1]
    assert O.parse(entry)[0] == {"dana": ("viewer", O.key_hash(key))}
    assert O.main([]) == 2 and O.main(["Bad Name"]) == 2
