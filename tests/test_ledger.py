"""The guarded actions' ledger (ledger.py) and the signed audit chain, on both stores: every test
runs on a SQLite file and, when STF_TEST_PG_URL names a throwaway Postgres (CI's service, or a
local one), on Postgres with the real migration applied."""

from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path

import pytest

from services.api import actuation as ACT
from services.api import ledger as L

MIGRATION = Path(__file__).resolve().parent.parent / (
    "supabase/migrations/20261028120000_stf_actions.sql"
)
PG_URL = os.environ.get("STF_TEST_PG_URL", "")
SECRET = "k" * 40


def _apply_migration(url: str) -> None:
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS agent CASCADE")
        conn.execute(MIGRATION.read_text())
        conn.execute(MIGRATION.read_text())  # a second run changes nothing


@pytest.fixture(params=["sqlite", "postgres"])
def ledger(request, tmp_path):
    if request.param == "sqlite":
        lg = L.SqliteLedger(str(tmp_path / "actions.db"))
    else:
        if not PG_URL:
            pytest.skip("STF_TEST_PG_URL is not set")
        _apply_migration(PG_URL)
        lg = L.PgLedger(PG_URL)
    yield lg
    lg.close()


def proposal(guest: str = "g1", status: str = "pending", created: float | None = None) -> dict:
    pid = str(uuid.uuid4())
    t = time.time() if created is None else created
    return {
        "id": pid, "thread_id": f"act-{pid}", "guest": guest, "kind": "order_submit",
        "params": {"op": "retrieve", "slot": "B2"}, "payload_hash": "a" * 64,
        "reason": "the operator asked", "evidence": ["slot B2: full"],
        "precheck": [{"rule": "slot_in_rack", "ok": True}], "status": status,
        "created_at": t, "expires_at": t + 300,
    }


# ---------------------------------------------------------------------------------- proposals
def test_a_proposal_round_trips_and_is_stored_once(ledger):
    p = proposal()
    assert ledger.put_proposal(p) is True
    assert ledger.put_proposal(p) is False  # a re-run of the propose node
    got = ledger.proposal(p["id"])
    assert {k: got[k] for k in p} == p
    assert ledger.proposal(str(uuid.uuid4())) is None


def test_a_proposal_cannot_be_born_approved(ledger):
    with pytest.raises(ValueError):
        ledger.put_proposal(proposal(status="approved"))


def test_a_transition_happens_once_and_only_forward(ledger):
    p = proposal()
    ledger.put_proposal(p)
    assert ledger.transition(p["id"], "pending", "approved", decided_by="ana", decided_at=1.0)
    assert not ledger.transition(p["id"], "pending", "rejected")  # came too late
    got = ledger.proposal(p["id"])
    assert (got["status"], got["decided_by"]) == ("approved", "ana")
    with pytest.raises(ValueError):
        ledger.transition(p["id"], "approved", "pending")  # never backwards
    with pytest.raises(ValueError):
        ledger.transition(p["id"], "approved", "executing", payload_hash="b" * 64)


def test_of_ten_racing_decisions_exactly_one_wins(ledger):
    p = proposal()
    ledger.put_proposal(p)
    wins, start = [], threading.Barrier(10)

    def decide(i: int) -> None:
        start.wait()
        if ledger.transition(p["id"], "pending", "approved", decided_by=f"op{i}"):
            wins.append(i)

    threads = [threading.Thread(target=decide, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1
    assert ledger.proposal(p["id"])["decided_by"] == f"op{wins[0]}"


# --------------------------------------------------------------------------------- executions
def test_an_execution_is_claimed_once(ledger):
    p = proposal(status="pending")
    ledger.put_proposal(p)
    assert ledger.start_execution(p["id"], 10.0) is True
    assert ledger.start_execution(p["id"], 11.0) is False  # a re-run must reconcile
    assert ledger.execution(p["id"])["state"] == "started"
    assert ledger.finish_execution(p["id"], "done", 12.0, order_id=7, result={"seen": "queued"})
    got = ledger.execution(p["id"])
    assert (got["state"], got["order_id"], got["result"]) == ("done", 7, {"seen": "queued"})
    assert not ledger.finish_execution(p["id"], "unknown", 13.0)  # done stays done
    with pytest.raises(ValueError):
        ledger.finish_execution(p["id"], "started", 14.0)


def test_an_unknown_execution_can_be_reconciled(ledger):
    p = proposal()
    ledger.put_proposal(p)
    ledger.start_execution(p["id"], 1.0)
    assert ledger.finish_execution(p["id"], "unknown", 2.0)
    assert ledger.finish_execution(p["id"], "done", 3.0, order_id=4)


# ---------------------------------------------------------------------------------- retention
def test_forgetting_a_guest_drops_its_proposals_and_executions_only(ledger):
    mine, other = proposal("g1"), proposal("g2")
    for p in (mine, other):
        ledger.put_proposal(p)
        ledger.start_execution(p["id"], 1.0)
    assert ledger.forget("g1") == [mine["thread_id"]]
    assert ledger.proposal(mine["id"]) is None and ledger.execution(mine["id"]) is None
    assert ledger.proposal(other["id"]) and ledger.execution(other["id"])


def test_old_proposals_lapse(ledger):
    old, new = proposal(created=1000.0), proposal()
    for p in (old, new):
        ledger.put_proposal(p)
    assert ledger.lapse(time.time() - 3600) == [old["thread_id"]]
    assert ledger.proposal(old["id"]) is None and ledger.proposal(new["id"])


# ------------------------------------------------------------------------------ the audit chain
def guard(ledger) -> ACT.ActionGuard:
    return ACT.ActionGuard(secret_key=SECRET, audit=ledger)


def test_the_chain_links_every_record_to_the_one_before(ledger):
    g = guard(ledger)
    g.trigger_emergency_stop(actor="sensor", reason="light curtain")
    g.reset_emergency_stop(actor="ana")
    g.execute_alarm_ack(code="OVN-D02", actor="ana")
    recs = g.records()
    assert [r.action for r in recs] == ["emergency_stop", "reset_emergency_stop", "alarm_ack"]
    assert recs[0].prev_sig == ""
    assert [r.prev_sig for r in recs[1:]] == [r.signature for r in recs[:-1]]
    assert g.verify_chain() is True
    assert g.list_audit_records(limit=1)[0]["action"] == "alarm_ack"
    assert [r.action for r in g.records(action="alarm_ack")] == ["alarm_ack"]


def test_an_edited_or_removed_record_breaks_the_chain(ledger):
    g = guard(ledger)
    for code in ("OVN-D01", "OVN-D02", "OVN-D03"):
        g.execute_alarm_ack(code=code, actor="ana")
    recs = g.records()
    edited = [recs[0], ACT.AuditRecord(**{**recs[1].as_dict(), "actor": "mallory"}), recs[2]]
    assert g.verify_chain(edited) is False
    assert g.verify_chain([recs[0], recs[2]]) is False  # the middle one gone
    assert g.verify_chain(recs[1:]) is True  # pruned at its start: still verifies


def test_another_key_cannot_verify_the_chain(ledger):
    guard(ledger).execute_alarm_ack(code="OVN-D02", actor="ana")
    assert ACT.ActionGuard(secret_key="x" * 40, audit=ledger).verify_chain() is False


def test_concurrent_writers_never_fork_the_chain(ledger):
    g = guard(ledger)
    start = threading.Barrier(12)

    def write(i: int) -> None:
        start.wait()
        g.execute_alarm_ack(code=f"OVN-D{i:02d}", actor="ana")

    threads = [threading.Thread(target=write, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    recs = g.records()
    assert len(recs) == 12
    assert len({r.prev_sig for r in recs}) == 12  # no two records claim the same parent
    assert g.verify_chain() is True


def test_the_store_refuses_to_edit_a_record(ledger):
    guard(ledger).execute_alarm_ack(code="OVN-D02", actor="ana")
    with pytest.raises(Exception, match="append-only"):
        ledger._run(f"UPDATE {ledger._t('action_audit')} SET actor = 'mallory'")


def test_pruning_never_takes_a_young_record(ledger):
    guard(ledger).execute_alarm_ack(code="OVN-D02", actor="ana")
    assert ledger.prune_audit(time.time() + 1) == 0
    assert len(ledger.audit(limit=None)) == 1


def test_postgres_itself_refuses_to_delete_a_young_record(ledger):
    if not isinstance(ledger, L.PgLedger):
        pytest.skip("the delete trigger is the Postgres migration's")
    guard(ledger).execute_alarm_ack(code="OVN-D02", actor="ana")
    with pytest.raises(Exception, match="at least 30 days"):
        ledger._run("DELETE FROM agent.action_audit")


def test_the_chain_survives_a_restart(tmp_path):
    path = str(tmp_path / "actions.db")
    first = L.SqliteLedger(path)
    guard(first).execute_alarm_ack(code="OVN-D01", actor="ana")
    first.close()
    again = L.SqliteLedger(path)  # a new process: the same file, the same key
    g = guard(again)
    g.execute_alarm_ack(code="OVN-D02", actor="ana")
    recs = g.records()
    assert len(recs) == 2 and recs[1].prev_sig == recs[0].signature
    assert g.verify_chain() is True
    again.close()


def test_an_audit_that_cannot_be_written_stops_the_order_before_it_moves():
    from services.api.runtime import SimRuntime

    class Broken(ACT.MemoryAudit):
        def append_audit(self, row, sign):
            raise ConnectionError("ledger down")

    rt = SimRuntime()
    with pytest.raises(ConnectionError):
        ACT.ActionGuard(secret_key=SECRET, audit=Broken()).execute_order(
            rt, op="retrieve", slot="B2", actor="ana"
        )
    assert not rt._pending  # nothing queued


# ------------------------------------------------------------------- the key and the stores
def test_a_deployment_without_a_strong_key_reports_it(monkeypatch):
    for env in (
        {"K_SERVICE": "stf-live"},
        {"K_SERVICE": "stf-live", "STF_AUDIT_SECRET": "short"},
        {"RENDER": "true", "STF_AUDIT_SECRET": ACT.OLD_DEFAULT_SECRET},
    ):
        key, problem = ACT.audit_secret(env)
        assert problem and len(key) == 64
        assert ACT.audit_secret(env)[0] != key  # a key for this process only
    assert ACT.audit_secret({"K_SERVICE": "stf-live", "STF_AUDIT_SECRET": SECRET}) == (
        SECRET.encode(), None
    )


def test_a_local_run_keeps_its_key_beside_its_data(tmp_path):
    env = {"STF_DATA_DIR": str(tmp_path)}
    key, problem = ACT.audit_secret(env)
    assert problem is None and ACT.audit_secret(env) == (key, None)
    assert (tmp_path / "audit_secret").stat().st_mode & 0o777 == 0o600


def test_which_ledger_where(tmp_path):
    lg, note = L.ledger_from_env({"SUPABASE_DB_URL": "postgresql://u@h/db"})
    assert isinstance(lg, L.PgLedger) and "Postgres" in note  # not connected until used
    assert L.ledger_from_env({"K_SERVICE": "stf-live"})[0] is None
    lg, note = L.ledger_from_env({"STF_DATA_DIR": str(tmp_path)})
    assert isinstance(lg, L.SqliteLedger) and lg.path == str(tmp_path / "actions.db")
    lg.close()


def test_the_process_guard_keeps_its_chain_in_the_ledger(monkeypatch, tmp_path):
    monkeypatch.setattr(ACT, "_GUARD", None)
    g = ACT.get_guard()
    assert isinstance(g.audit, L.SqliteLedger) and g.ledger is g.audit
    assert g.ledger_note == "SQLite" and g.secret_problem is None
    g.execute_alarm_ack(code="OVN-D02", actor="ana")
    assert L.SqliteLedger(str(tmp_path / "actions.db")).audit()[0]["action"] == "alarm_ack"
    monkeypatch.setattr(ACT, "_GUARD", None)
