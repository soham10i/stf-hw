"""The actuation graph (actions.py): propose -> precheck -> approval -> revalidate -> execute ->
observe, with decide() in front. Every test runs on the SQLite ledger and checkpointer and, when
STF_TEST_PG_URL names a throwaway Postgres, on Postgres with the real migration applied."""

from __future__ import annotations

import os
import threading
import time
import uuid

import pytest
from pydantic import ValidationError

from services.api import actions as A
from services.api import actuation as ACT
from services.api import ledger as L
from services.api.operators import Operator
from services.api.runtime import SimRuntime
from tests.test_ledger import PG_URL, SECRET, _apply_migration

ANA = Operator("ana", "operator", "k" * 12, time.time() + 3600)
BEN = Operator("ben", "viewer", "b" * 12, time.time() + 3600)


class Clock:
    def __init__(self) -> None:
        self.t = time.time()

    def __call__(self) -> float:
        return self.t


class Store:
    """One backing store; open() is a process starting on it (a restart opens it again)."""

    def __init__(self, kind: str, tmp_path) -> None:
        self.kind, self.path, self.opened = kind, str(tmp_path / "actions.db"), []

    def open(self, rt, clock=None, observe_s: float = 0.5) -> A.Actions:
        lg = L.SqliteLedger(self.path) if self.kind == "sqlite" else L.PgLedger(PG_URL)
        self.opened.append(lg)
        guard = ACT.ActionGuard(secret_key=SECRET, audit=lg)
        return A.Actions(guard, lg, lg.saver(), runtime=lambda: rt, now=clock or time.time,
                         observe_s=observe_s, poll_s=0.01)

    def close(self) -> None:
        for lg in self.opened:
            lg.close()


@pytest.fixture(params=["sqlite", "postgres"])
def store(request, tmp_path):
    if request.param == "postgres":
        if not PG_URL:
            pytest.skip("STF_TEST_PG_URL is not set")
        _apply_migration(PG_URL)
    s = Store(request.param, tmp_path)
    yield s
    s.close()


@pytest.fixture()
def rt():
    return SimRuntime()


def propose(acts: A.Actions, kind="order_submit", params=None, guest="g1") -> dict:
    p = acts.new_proposal(kind, params or {"op": "retrieve", "slot": "B2"}, guest,
                          reason="the operator asked", evidence=["slot B2: full"])
    return acts.start(p)


def statuses(acts: A.Actions, action: str = "action_proposal") -> list[str]:
    return [r.status for r in acts.guard.records(action=action)]


# -------------------------------------------------------------------------- the typed proposal
def test_the_proposal_is_typed_and_normalized():
    t = time.time()
    base = {"id": uuid.uuid4(), "guest": "g", "created_at": t, "expires_at": t + 300}
    p = A.ActionProposal(kind="order_submit", params={"op": " Retrieve", "slot": "b2"}, **base)
    assert p.params.model_dump() == {"op": "retrieve", "slot": "B2"}
    for kind, params in [
        ("order_submit", {"op": "retrieve", "slot": "C4"}),  # F5: one range
        ("order_submit", {"op": "dance", "slot": "B2"}),
        ("order_submit", {"op": "retrieve", "slot": "B2", "qty": 99}),  # nothing extra
        ("order_cancel", {}),  # F6: a cancel names its order
        ("order_cancel", {"order_id": "7"}),
        ("order_cancel", {"op": "retrieve", "slot": "B2"}),  # a submit's parameters
        ("order_submit", {"order_id": 3}),
        ("alarm_ack", {"code": "OVN-D02"}),  # frozen actions are not proposals
    ]:
        with pytest.raises(ValidationError):
            A.ActionProposal(kind=kind, params=params, **base)
    with pytest.raises(ValidationError):
        A.ActionProposal(kind="order_submit", params={"op": "home"},
                         **{**base, "expires_at": t})


def test_the_hash_binds_the_payload_and_the_proposal_not_the_words():
    t = time.time()
    base = {"kind": "order_submit", "params": {"op": "retrieve", "slot": "B2"}, "guest": "g",
            "created_at": t, "expires_at": t + 300}
    pid = uuid.uuid4()
    one = A.ActionProposal(id=pid, reason="because", **base)
    assert A.payload_hash(one) == A.payload_hash(A.ActionProposal(id=pid, reason="other", **base))
    assert A.payload_hash(one) != A.payload_hash(A.ActionProposal(id=uuid.uuid4(), **base))
    other = A.ActionProposal(id=pid, **{**base, "params": {"op": "retrieve", "slot": "B3"}})
    assert A.payload_hash(one) != A.payload_hash(other)
    assert b'"slot":"B2"' in A.canonical(one) and b"because" not in A.canonical(one)


# ------------------------------------------------------------------------------- the round trip
def test_an_approved_proposal_runs_once_and_is_observed(store, rt):
    acts = store.open(rt)
    v = propose(acts)
    assert v["status"] == "pending" and v["summary"] == "Retrieve from slot B2"
    assert all(r["ok"] for r in v["precheck"]) and not rt._pending  # nothing moved yet
    assert acts.graph.get_state(acts._config(v["id"])).next == ("approval",)

    out = acts.decide(v["id"], "approve", v["payload_hash"], ANA)
    assert out.code == 200
    p = out.proposal
    assert (p["status"], p["decided_by"], p["execution"]["state"]) == ("done", "ana", "done")
    assert [(o.id, o.op, o.slot) for o in rt._pending] == [(p["execution"]["order_id"],
                                                             "retrieve", "B2")]
    assert statuses(acts) == ["PENDING", "APPROVED", "DONE"]
    assert statuses(acts, "order_submit") == ["ACCEPTED", "EXECUTED"]
    assert acts.guard.records(action="order_submit")[0].actor == "ana"
    assert acts.guard.verify_chain()
    steps = [s[0] for s in acts.history(v["id"]) if s]
    assert steps[steps.index("approval") + 1] == "revalidate"


def test_a_rejected_proposal_changes_nothing(store, rt):
    acts = store.open(rt)
    v = propose(acts)
    out = acts.decide(v["id"], "reject", v["payload_hash"], ANA)
    assert (out.code, out.proposal["status"], out.proposal["execution"]) == (200, "rejected", None)
    assert not rt._pending and not acts.graph.get_state(acts._config(v["id"])).next
    assert statuses(acts) == ["PENDING", "REJECTED"]


def test_a_cancel_runs_once_and_is_observed(store, rt):
    acts = store.open(rt)
    rt.submit("retrieve", "A1")
    target = rt.submit("store", "A2")
    v = propose(acts, "order_cancel", {"order_id": target.id})
    assert v["summary"] == f"Cancel order #{target.id}"
    out = acts.decide(v["id"], "approve", v["payload_hash"], ANA)
    assert out.proposal["status"] == "done" and out.proposal["execution"]["seen"] == "cancelled"
    assert [o.id for o in rt._pending] == [1]


# ------------------------------------------------------------------------ the decision's checks
def test_only_an_operator_decides(store, rt):
    acts = store.open(rt)
    v = propose(acts)
    for who in (None, BEN):
        assert acts.decide(v["id"], "approve", v["payload_hash"], who).code == 403
    assert acts.view(v["id"])["status"] == "pending" and not rt._pending


def test_an_unknown_proposal_is_404(store, rt):
    acts = store.open(rt)
    assert acts.decide(str(uuid.uuid4()), "approve", "a" * 64, ANA).code == 404
    assert acts.decide("not-a-uuid", "approve", "a" * 64, ANA).code == 404
    assert acts.view("not-a-uuid") is None


def test_another_payload_is_409_and_moves_nothing(store, rt):
    acts = store.open(rt)
    v, w = propose(acts), propose(acts, params={"op": "retrieve", "slot": "B3"})
    h = v["payload_hash"]
    for wrong in (w["payload_hash"], h[:-1] + ("0" if h[-1] != "0" else "1"), "", "x" * 128):
        out = acts.decide(v["id"], "approve", wrong, ANA)
        assert out.code == 409 and out.proposal["status"] == "pending"
    assert not rt._pending


def test_an_expired_proposal_is_410_and_ends(store, rt):
    clock = Clock()
    acts = store.open(rt, clock)
    v = propose(acts)
    clock.t = v["expires_at"] + 1
    out = acts.decide(v["id"], "approve", v["payload_hash"], ANA)
    assert out.code == 410 and out.proposal["status"] == "expired"
    assert acts.decide(v["id"], "approve", v["payload_hash"], ANA).code == 410
    assert not rt._pending and not acts.graph.get_state(acts._config(v["id"])).next
    assert statuses(acts) == ["PENDING", "EXPIRED"]


def test_reading_an_expired_proposal_ends_it_too(store, rt):
    clock = Clock()
    acts = store.open(rt, clock)
    v = propose(acts)
    clock.t = v["expires_at"] + 1
    assert acts.view(v["id"])["status"] == "expired"
    assert not acts.graph.get_state(acts._config(v["id"])).next


def test_a_replayed_approval_answers_with_the_outcome_and_runs_nothing(store, rt):
    acts = store.open(rt)
    v = propose(acts)
    first = acts.decide(v["id"], "approve", v["payload_hash"], ANA)
    again = acts.decide(v["id"], "approve", v["payload_hash"], ANA)
    assert (again.code, again.proposal["status"]) == (200, "done")
    assert again.proposal["execution"] == first.proposal["execution"]
    assert len(rt._pending) == 1
    assert acts.decide(v["id"], "reject", v["payload_hash"], ANA).code == 409
    assert statuses(acts) == ["PENDING", "APPROVED", "DONE"]


def test_of_ten_approvals_at_once_one_resumes_and_one_order_exists(store, rt):
    acts = store.open(rt)
    v = propose(acts)
    start, codes = threading.Barrier(10), []

    def click() -> None:
        start.wait()
        codes.append(acts.decide(v["id"], "approve", v["payload_hash"], ANA).code)

    threads = [threading.Thread(target=click) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes == [200] * 10
    assert len(rt._pending) == 1
    assert statuses(acts) == ["PENDING", "APPROVED", "DONE"]
    assert statuses(acts, "order_submit") == ["ACCEPTED", "EXECUTED"]


# --------------------------------------------------------------------------- fresh state wins
def test_a_full_queue_between_proposal_and_approval_refuses(store, rt):
    acts = store.open(rt)
    v = propose(acts)
    for _ in range(ACT.MAX_PENDING_ORDERS):
        rt.submit("home", None)
    out = acts.decide(v["id"], "approve", v["payload_hash"], ANA)
    assert out.code == 200 and out.proposal["status"] == "refused"
    assert "Queue saturated" in out.proposal["note"]
    assert len(rt._pending) == ACT.MAX_PENDING_ORDERS and out.proposal["execution"] is None
    assert statuses(acts) == ["PENDING", "APPROVED", "REFUSED"]


def test_an_estop_between_proposal_and_approval_refuses(store, rt):
    acts = store.open(rt)
    v = propose(acts)
    acts.guard.trigger_emergency_stop(actor="sensor", reason="light curtain")
    out = acts.decide(v["id"], "approve", v["payload_hash"], ANA)
    assert out.proposal["status"] == "refused" and "Emergency stop" in out.proposal["note"]
    assert not rt._pending


def test_a_proposal_the_precheck_refuses_never_waits(store, rt):
    acts = store.open(rt)
    acts.guard.trigger_emergency_stop(actor="sensor", reason="light curtain")
    v = propose(acts)
    assert v["status"] == "refused" and v["final"]
    assert [r["rule"] for r in v["precheck"] if not r["ok"]] == ["estop_clear"]
    assert not acts.graph.get_state(acts._config(v["id"])).next
    assert acts.decide(v["id"], "approve", v["payload_hash"], ANA).code == 409


def test_the_guards_last_check_refuses_when_the_plant_moved_after_revalidate(store, rt):
    acts = store.open(rt)
    target = rt.submit("store", "A2")
    v = propose(acts, "order_cancel", {"order_id": target.id})
    real = acts._n_revalidate

    def then_start_it(state):
        out = real(state)
        rt._active = rt._pending.popleft()  # production picked the order up meanwhile
        return out

    acts._n_revalidate = then_start_it
    acts.graph = acts._build()
    out = acts.decide(v["id"], "approve", v["payload_hash"], ANA)
    assert out.proposal["status"] == "refused" and "in production" in out.proposal["note"]
    assert out.proposal["execution"]["state"] == "refused"


# ------------------------------------------------------------------------ restarts and crashes
def test_a_restart_while_pending_loses_nothing(store, rt):
    v = propose(store.open(rt))
    fresh = SimRuntime()  # a new process: the same store, a new runtime
    acts = store.open(fresh)
    out = acts.decide(v["id"], "approve", v["payload_hash"], ANA)
    assert out.proposal["status"] == "done" and len(fresh._pending) == 1
    steps = [s[0] for s in acts.history(v["id"]) if s]
    assert steps[:4] == ["__start__", "propose", "precheck", "approval"]
    assert steps[4] == "revalidate"
    assert acts.guard.verify_chain()


def test_a_restart_that_lost_the_target_refuses(store, rt):
    target = rt.submit("store", "A2")
    v = propose(store.open(rt), "order_cancel", {"order_id": target.id})
    acts = store.open(SimRuntime())  # the new process's runtime never had that order
    out = acts.decide(v["id"], "approve", v["payload_hash"], ANA)
    assert out.proposal["status"] == "refused"
    assert any(r["rule"] == "cancel_target_pending" and not r["ok"]
               for r in acts.graph.get_state(acts._config(v["id"])).values["recheck"])


class Crash(BaseException):
    """The process dies: nothing after it runs, no checkpoint is written."""


def test_a_crash_after_the_side_effect_reconciles_and_never_submits_again(store, rt):
    acts = store.open(rt)
    v = propose(acts)
    real = acts.guard.execute_order

    def submit_then_die(*a, **kw):
        real(*a, **kw)
        raise Crash

    acts.guard.execute_order = submit_then_die
    with pytest.raises(Crash):
        acts.decide(v["id"], "approve", v["payload_hash"], ANA)
    assert len(rt._pending) == 1

    again = store.open(rt)  # the next process, the same plant
    out = again.decide(v["id"], "approve", v["payload_hash"], ANA)  # the operator retries
    assert out.code == 200 and out.proposal["status"] == "done"
    assert out.proposal["execution"]["order_id"] == rt._pending[0].id
    assert len(rt._pending) == 1  # exactly one such order
    steps = [s[0] for s in again.history(v["id"]) if s]
    assert "reconcile" in steps and steps.count("execute") == 1


def test_a_crash_before_the_side_effect_is_unknown_never_a_late_order(store, rt):
    acts = store.open(rt)
    v = propose(acts)

    def die(*a, **kw):
        raise Crash

    acts.guard.execute_order = die
    with pytest.raises(Crash):
        acts.decide(v["id"], "approve", v["payload_hash"], ANA)
    out = store.open(rt).decide(v["id"], "approve", v["payload_hash"], ANA)
    assert out.proposal["status"] == "unknown" and not rt._pending


def test_a_result_the_runtime_does_not_show_is_unknown_not_done(store, rt):
    acts = store.open(rt, observe_s=0.1)
    v = propose(acts)
    real = acts.guard.execute_order

    def submit_and_lose(*a, **kw):
        out = real(*a, **kw)
        rt._pending.clear()  # the machine dropped it
        return out

    acts.guard.execute_order = submit_and_lose
    out = acts.decide(v["id"], "approve", v["payload_hash"], ANA)
    assert out.proposal["status"] == "unknown" and out.proposal["execution"]["state"] == "unknown"
    assert statuses(acts, "order_submit").count("ACCEPTED") == 1  # no second submit
    assert statuses(acts)[-1] == "UNKNOWN"


# ------------------------------------------------------------------------------- retention
def test_forgetting_a_guest_drops_their_proposals_and_threads(store, rt):
    acts = store.open(rt)
    mine, other = propose(acts, guest="g1"), propose(acts, guest="g2")
    assert acts.owned_by(mine["id"], "g1") and not acts.owned_by(mine["id"], "g2")
    assert acts.forget("g1") == 1
    assert acts.view(mine["id"]) is None and acts.view(other["id"])
    assert not acts.graph.get_state(acts._config(mine["id"])).values
    assert acts.graph.get_state(acts._config(other["id"])).values
    recs = acts.guard.records()
    assert recs and all("g1" not in str(r.as_dict()) for r in recs)


def test_a_guest_is_kept_as_a_keyed_hash(store, rt):
    acts = store.open(rt)
    v = propose(acts, guest="guest-123")
    row = acts.ledger.proposal(v["id"])
    assert row["guest"] == acts.guest_ref("guest-123") and "guest-123" not in row["guest"]
    assert len(row["guest"]) == 32


# ------------------------------------------------------------------------------ the switch
def test_actions_are_off_unless_asked_for(monkeypatch):
    monkeypatch.setattr(A, "_ACTIONS", None)
    monkeypatch.setattr(ACT, "_GUARD", None)
    assert A.status() == (None, "STF_AGENT_ACTUATION is not propose")
    monkeypatch.setenv("STF_AGENT_ACTUATION", "1")  # the legacy switch is not this one
    assert A.mode() == "off"
    monkeypatch.setenv("STF_AGENT_ACTUATION", "propose")
    acts, why = A.status()
    assert why == "" and isinstance(acts.ledger, L.SqliteLedger)
    assert os.path.exists(acts.ledger.path.replace("actions.db", "actions-graph.db"))
    monkeypatch.setattr(A, "_ACTIONS", None)
    monkeypatch.setattr(ACT, "_GUARD", None)


def test_a_public_deployment_without_its_settings_keeps_actions_off(monkeypatch):
    monkeypatch.setenv("STF_AGENT_ACTUATION", "propose")
    monkeypatch.setenv("K_SERVICE", "stf-live")
    for env in ({}, {"SUPABASE_DB_URL": "postgresql://u@h/db"}):
        for k, val in env.items():
            monkeypatch.setenv(k, val)
        monkeypatch.setattr(A, "_ACTIONS", None)
        monkeypatch.setattr(ACT, "_GUARD", None)
        acts, why = A.status()
        assert acts is None and "STF_AUDIT_SECRET" in why
    monkeypatch.setenv("STF_AUDIT_SECRET", SECRET)
    monkeypatch.setenv("SUPABASE_DB_URL", "")
    monkeypatch.setattr(ACT, "_GUARD", None)
    acts, why = A.status()
    assert acts is None and "SUPABASE_DB_URL" in why
    monkeypatch.setattr(ACT, "_GUARD", None)
