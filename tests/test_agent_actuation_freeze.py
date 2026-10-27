"""Phase 0: model-initiated writes are frozen without removing their future route parsers."""

from services.api import tools as T


def test_write_tools_are_not_advertised_to_models_by_default():
    names = {d["name"] for d in T.declarations()}
    assert not names & T.WRITE_TOOLS
    assert "machine_health" in names


def test_direct_write_call_fails_closed_before_entering_legacy_handler(monkeypatch):
    def must_not_run(args, ctx):
        raise AssertionError("a frozen write reached its legacy handler")

    monkeypatch.setattr(T, "order_submit", must_not_run)
    monkeypatch.setattr(T.TOOLS["order_submit"], "fn", must_not_run)
    out = T.call("order_submit", {"op": "cycle", "slot": "B2"}, T.Ctx(client="guest"))
    assert "No state was changed" in out.text
    assert dict(out.facts) == {"Status": "BLOCKED", "State changed": "No"}


def test_action_intent_still_routes_but_cannot_execute():
    calls = T.route("bake a cookie from slot B2", T.Ctx(client="guest"))
    assert any(name == "order_submit" for name, _ in calls)
    out = T.rules_answer("bake a cookie from slot B2", T.Ctx(client="guest"))
    assert "No state was changed" in out[0]


def test_controlled_legacy_tests_can_opt_in(monkeypatch):
    monkeypatch.setenv("STF_AGENT_ACTUATION", "1")
    assert T.actuation_enabled()
    assert T.WRITE_TOOLS <= {d["name"] for d in T.declarations()}
