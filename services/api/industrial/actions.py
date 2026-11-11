"""
Guarded actions (docs/plans/guarded-action-plan.md, loop 5): the copilot proposes a typed
action, the named rules check it, the graph pauses until an operator approves the exact payload,
the rules run again on fresh state, the action runs at most once, and its result is observed.

    propose -> precheck -> approval (interrupt) -> revalidate -> execute -> observe -> report
                  |              |                    |            |
                  +- refused     +- rejected/expired  +- refused   +- claimed before: reconcile
                                         \\-----------------------------------------> report

One LangGraph thread per proposal (thread_id "act-<uuid>"), checkpointed after every step
(durability "sync") by the ledger's saver: Postgres schema `agent` on a deployment, a SQLite
file locally. A restart while an approval is pending loses nothing: the next decision resumes
the thread from its checkpoint. The question graph (agent.py) stays uncheckpointed.

Each node may run again (a resume re-runs the interrupted node from its start; a crash re-runs
the step whose checkpoint was not written), so each one is idempotent:
  - the ledger's moves are conditional (ledger.TRANSITIONS): a re-run's move does nothing, and
    the node takes the ledger's recorded answer
  - audit records have fixed ids, one per (proposal, status): a re-run writes no second one
  - `execute` claims the proposal's execution row BEFORE acting; a re-run that finds the row
    goes to `reconcile`, which compares the ledger with the runtime and never acts

decide() is the decision endpoint's logic, failing closed at the first miss: an operator (403),
the proposal (404), unexpired (410), the payload hash it was shown (409), then the one
conditional move pending -> approved|rejected. A replay of the recorded decision answers 200
with the outcome and moves nothing; a different decision answers 409.

STF_AGENT_ACTUATION   off (default) | propose: actions need this, a ledger, a strong
                      STF_AUDIT_SECRET on a deployment, and a checkpointer (status())
STF_ACTION_TTL_S      a proposal's lifetime, default 300
STF_ACTION_OBSERVE_S  how long `observe` waits for the postcondition, default 5
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    model_validator,
)

from services.api.core.logging_config import get_logger

from . import actuation
from . import ledger as action_ledger

logger = get_logger(__name__)

PROPOSER = "copilot"  # the actor of a proposal and its precheck; an operator's name decides
AUDIT_NS = uuid.UUID("5f1c6a52-6b1e-4d7a-9d43-1d0c7a3e2b10")  # fixed audit ids (audit_id)
DECIDED = {"approve": "approved", "reject": "rejected"}


def _upper(v: Any) -> Any:
    return v.strip().upper() if isinstance(v, str) else v


def _lower(v: Any) -> Any:
    return v.strip().lower() if isinstance(v, str) else v


# F5: one range for a slot, everywhere
SlotId = Annotated[str, BeforeValidator(_upper), StringConstraints(pattern=r"^[A-C][1-3]$")]


class OrderSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    op: Annotated[Literal["retrieve", "store", "home", "cycle"], BeforeValidator(_lower)]
    slot: SlotId | None = None


class OrderCancel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    order_id: StrictInt  # F6: a cancel names its order, and "7" is not an order number


PARAMS: dict[str, type[BaseModel]] = {"order_submit": OrderSubmit, "order_cancel": OrderCancel}


class ActionProposal(BaseModel):
    """What the copilot asks an operator to approve. Everything the card shows comes from here;
    the hash of its canonical form is what an approval binds to."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    v: Literal[1] = 1
    id: UUID
    kind: Literal["order_submit", "order_cancel"]
    params: OrderSubmit | OrderCancel
    reason: str = Field(default="", max_length=300)  # the model's words, shown as such
    evidence: list[Annotated[str, StringConstraints(max_length=200)]] = Field(
        default_factory=list, max_length=8
    )
    guest: str = Field(min_length=1, max_length=64)  # guest_ref(): never the raw guest id
    created_at: float
    expires_at: float

    @model_validator(mode="before")
    @classmethod
    def _params_for_kind(cls, data: Any) -> Any:
        # the kind picks the parameters' type, so {"order_id": 3} can never pass as a submit
        if isinstance(data, dict) and isinstance(data.get("params"), dict):
            model = PARAMS.get(data.get("kind"))
            if model is not None:
                data = {**data, "params": model.model_validate(data["params"])}
        return data

    @model_validator(mode="after")
    def _consistent(self) -> ActionProposal:
        if not isinstance(self.params, PARAMS[self.kind]):
            raise ValueError(f"{self.kind} takes {PARAMS[self.kind].__name__} parameters")
        if self.expires_at <= self.created_at:
            raise ValueError("a proposal expires after it is made")
        return self


def canonical(p: ActionProposal) -> bytes:
    """The bytes an approval binds to: version, id, kind, normalized parameters and expiry, as
    JSON with sorted keys and no spaces. The id is inside, so two identical orders are two
    approvals; the reason and evidence are not, since they change nothing the plant does."""
    doc = {
        "v": p.v, "id": str(p.id), "kind": p.kind,
        "params": p.params.model_dump(mode="json"), "expires_at": p.expires_at,
    }
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def payload_hash(p: ActionProposal) -> str:
    return hashlib.sha256(canonical(p)).hexdigest()


def describe(kind: str, params: dict[str, Any]) -> str:
    """The card's one line, from the payload itself, never from the model's words."""
    if kind == "order_cancel":
        return f"Cancel order #{params['order_id']}"
    op, slot = params.get("op"), params.get("slot")
    return {
        "retrieve": f"Retrieve from slot {slot}",
        "store": f"Store into slot {slot}",
        "cycle": f"Run a full cycle from slot {slot}",
        "home": "Send the carrier home",
    }.get(op, f"{op} {slot or ''}".strip())


def audit_id(proposal_id: str, status: str) -> str:
    """The one audit record a proposal gets for a status: a re-run node writes no second one."""
    return str(uuid.uuid5(AUDIT_NS, f"{proposal_id}:{status}"))


def _uuid(s: str) -> str | None:
    """A proposal id in its one spelling, or None (the ledger is never asked about junk)."""
    try:
        return str(UUID(str(s)))
    except ValueError:
        return None


def thread_id(proposal_id: str) -> str:
    return f"act-{proposal_id}"


class ActState(TypedDict, total=False):
    """The thread's state: JSON only, nothing bound to a request."""

    proposal: dict[str, Any]  # ActionProposal.model_dump(mode="json")
    payload_hash: str
    precheck: list[dict[str, Any]]  # [{rule, ok, why}] when proposed
    fingerprint: str  # actuation.precondition_fingerprint when proposed
    recheck: list[dict[str, Any]]  # the same rules after approval, on fresh state
    recheck_fingerprint: str
    decision: dict[str, Any]  # {verdict, actor, role, at}
    execution: dict[str, Any]  # {order_id, audit_id, seen, after_id}
    status: str  # the ledger's status as this thread last saw it
    route: str  # where execute goes next: observe, reconcile or report
    note: str


@dataclass(frozen=True)
class Outcome:
    """decide()'s answer: the HTTP status, the proposal as it now stands, and why."""

    code: int
    detail: str
    proposal: dict[str, Any] | None = None


class Actions:
    """The actuation graph over one guard, ledger and checkpointer."""

    def __init__(
        self,
        guard: actuation.ActionGuard,
        ledger: action_ledger.Ledger,
        saver: Any,
        runtime: Callable[[], Any] = actuation.get_runtime,
        now: Callable[[], float] = time.time,
        ttl_s: float | None = None,
        observe_s: float | None = None,
        poll_s: float = 0.05,
    ) -> None:
        self.guard, self.ledger, self.saver = guard, ledger, saver
        self.runtime, self.now = runtime, now
        env = os.environ
        self.ttl_s = float(ttl_s if ttl_s is not None else env.get("STF_ACTION_TTL_S") or 300)
        self.observe_s = float(
            observe_s if observe_s is not None else env.get("STF_ACTION_OBSERVE_S") or 5
        )
        self.poll_s = poll_s
        self.keep_s = float(env.get("STF_GUEST_DAYS") or 30) * 86400  # rows lapse with guests
        self._started = 0
        self._locks = [threading.Lock() for _ in range(64)]  # one stripe per proposal hash
        self.graph = self._build()

    # --- the graph
    def _build(self):
        from langgraph.graph import END, START, StateGraph

        g = StateGraph(ActState)
        for name in ("propose", "precheck", "approval", "revalidate", "execute", "observe",
                     "reconcile", "report"):
            g.add_node(name, getattr(self, f"_n_{name}"))
        g.add_edge(START, "propose")
        g.add_edge("propose", "precheck")
        g.add_conditional_edges(
            "precheck", lambda s: "approval" if s["status"] == "pending" else "report",
            ["approval", "report"],
        )
        g.add_conditional_edges(
            "approval", lambda s: "revalidate" if s["status"] == "approved" else "report",
            ["revalidate", "report"],
        )
        g.add_conditional_edges(
            "revalidate", lambda s: "execute" if s["status"] == "approved" else "report",
            ["execute", "report"],
        )
        g.add_conditional_edges("execute", lambda s: s["route"], ["observe", "reconcile", "report"])
        g.add_edge("observe", "report")
        g.add_edge("reconcile", "report")
        g.add_edge("report", END)
        return g.compile(checkpointer=self.saver, name="actuation")

    def _config(self, proposal_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id(proposal_id)}}

    def _record(self, state: ActState, actor: str, status: str, reason: str | None = None,
                fp: str = "") -> None:
        p = state["proposal"]
        self.guard.record_event(
            actor, "action_proposal",
            {"id": p["id"], "kind": p["kind"], "params": p["params"],
             "payload_hash": state.get("payload_hash", "")},
            status.upper(), reason, id=audit_id(p["id"], status), pre_hash=fp, post_hash=fp,
        )

    def _check(self, p: dict, actor: str) -> tuple[list[dict], str]:
        rt = self.runtime()
        verdicts = self.guard.precheck(p["kind"], p["params"], actor, rt)
        fp = actuation.precondition_fingerprint(self.guard, rt, p["kind"], p["params"])
        return [asdict(v) for v in verdicts], fp

    def _status(self, pid: str) -> str:
        row = self.ledger.proposal(pid)
        return row["status"] if row else "refused"

    def _n_propose(self, state: ActState) -> dict:
        p = ActionProposal.model_validate(state["proposal"])
        h = payload_hash(p)
        doc = p.model_dump(mode="json")
        self.ledger.put_proposal({
            "id": doc["id"], "thread_id": thread_id(doc["id"]), "guest": p.guest,
            "kind": p.kind, "params": doc["params"], "payload_hash": h, "reason": p.reason,
            "evidence": list(p.evidence), "precheck": [], "status": "proposed",
            "created_at": p.created_at, "expires_at": p.expires_at,
        })  # a re-run finds it there: no second row
        return {"proposal": doc, "payload_hash": h, "status": "proposed"}

    def _n_precheck(self, state: ActState) -> dict:
        p = state["proposal"]
        rows, fp = self._check(p, PROPOSER)
        refusal = next((r["why"] for r in rows if not r["ok"]), None)
        to = "refused" if refusal else "pending"
        if not self.ledger.transition(p["id"], "proposed", to, precheck=rows, note=refusal):
            row = self.ledger.proposal(p["id"])  # a re-run: the recorded answer stands
            to, rows, refusal = row["status"], row["precheck"], row.get("note")
        self._record(state, PROPOSER, to, refusal, fp)
        return {"precheck": rows, "fingerprint": fp, "status": to, "note": refusal or ""}

    def _n_approval(self, state: ActState) -> dict:
        # nothing before interrupt(): a resume re-runs this node from its start
        from langgraph.types import interrupt

        decision = interrupt({
            "proposal_id": state["proposal"]["id"],
            "payload_hash": state["payload_hash"],
            "expires_at": state["proposal"]["expires_at"],
        })
        return {"decision": decision, "status": decision["verdict"]}

    def _n_revalidate(self, state: ActState) -> dict:
        p, d = state["proposal"], state["decision"]
        if self.now() > p["expires_at"]:
            if not self.ledger.transition(p["id"], "approved", "expired", note="expired"):
                return {"status": self._status(p["id"])}
            return {"status": "expired", "note": "the proposal expired before it could run"}
        rows, fp = self._check(p, d["actor"])
        refusal = next((r["why"] for r in rows if not r["ok"]), None)
        if refusal:
            if not self.ledger.transition(p["id"], "approved", "refused", note=refusal):
                return {"status": self._status(p["id"]), "recheck": rows}
            return {"status": "refused", "note": refusal, "recheck": rows,
                    "recheck_fingerprint": fp}
        return {"recheck": rows, "recheck_fingerprint": fp}

    def _n_execute(self, state: ActState) -> dict:
        p, d = state["proposal"], state["decision"]
        rt = self.runtime()
        after_id = int(getattr(rt, "_next_id", 1)) - 1  # the last order id issued before this
        if not self.ledger.start_execution(p["id"], self.now(), {"after_id": after_id}):
            return {"route": "reconcile"}  # claimed by an earlier run: never act twice
        self.ledger.transition(p["id"], "approved", "executing")
        params = p["params"]
        if p["kind"] == "order_submit":
            res = self.guard.execute_order(rt, params["op"], params.get("slot"), actor=d["actor"])
            oid = res["order"]["id"] if res.get("accepted") else None
        else:
            res = self.guard.execute_order_cancel(rt, params["order_id"], actor=d["actor"])
            oid = params["order_id"]
        if not res.get("accepted"):
            why = res.get("error") or "refused"
            self.ledger.finish_execution(p["id"], "refused", self.now(),
                                         result={"after_id": after_id, "error": why})
            self.ledger.transition(p["id"], "executing", "refused", note=why)
            return {"status": "refused", "note": why, "route": "report"}
        return {
            "status": "executing", "route": "observe",
            "execution": {"order_id": oid, "audit_id": res.get("audit_id"), "after_id": after_id},
        }

    def _seen(self, p: dict, order_id: int | None) -> str | None:
        rt = self.runtime()
        if rt is None or order_id is None:
            return None
        if p["kind"] == "order_cancel":
            return actuation.observe_cancel(rt, order_id)
        return actuation.observe_order(rt, order_id, p["params"]["op"], p["params"].get("slot"))

    def _finish(self, pid: str, state_: str, ex: dict, seen: str | None) -> str:
        self.ledger.finish_execution(pid, state_, self.now(), order_id=ex.get("order_id"),
                                     result={"after_id": ex.get("after_id"), "seen": seen})
        if self._status(pid) == "approved":  # claimed, then the process died: catch up
            self.ledger.transition(pid, "approved", "executing")
        self.ledger.transition(pid, "executing", state_)
        return self._status(pid)

    def _n_observe(self, state: ActState) -> dict:
        p, ex = state["proposal"], dict(state["execution"])
        deadline = time.monotonic() + self.observe_s
        while (seen := self._seen(p, ex["order_id"])) is None and time.monotonic() < deadline:
            time.sleep(self.poll_s)
        status = self._finish(p["id"], "done" if seen else "unknown", ex, seen)
        note = "" if seen else "the runtime does not show the result: an operator reconciles"
        return {"status": status, "execution": {**ex, "seen": seen}, "note": note}

    def _n_reconcile(self, state: ActState) -> dict:
        """The execution was claimed by an earlier run: read what happened, never act."""
        p = state["proposal"]
        row = self.ledger.execution(p["id"]) or {}
        result = row.get("result") or {}
        ex = {"order_id": row.get("order_id"), "after_id": result.get("after_id"),
              "seen": result.get("seen")}
        if row.get("state") != "started":  # it ended before the crash: that outcome stands
            return {"status": self._status(p["id"]), "execution": ex}
        if p["kind"] == "order_cancel":
            ex["order_id"] = p["params"]["order_id"]
        else:
            ex["order_id"] = self._find_submitted(p, result.get("after_id"))
        seen = self._seen(p, ex["order_id"])
        status = self._finish(p["id"], "done" if seen else "unknown", ex, seen)
        note = "" if seen else "the earlier run's result cannot be seen: an operator reconciles"
        return {"status": status, "execution": {**ex, "seen": seen}, "note": note}

    def _find_submitted(self, p: dict, after_id: int | None) -> int | None:
        """The order an interrupted run submitted: issued after the claim, with this op and
        slot (the runtime numbers its orders in sequence)."""
        rt = self.runtime()
        if rt is None or after_id is None:
            return None
        active = getattr(rt, "_active", None)
        for o in [*getattr(rt, "_history", ()), *([active] if active else []),
                  *getattr(rt, "_pending", ())]:
            if o.id > after_id and o.op == p["params"]["op"] and (
                (o.slot or None) == (p["params"].get("slot") or None)
            ):
                return o.id
        return None

    def _n_report(self, state: ActState) -> dict:
        d = state.get("decision") or {}
        self._record(state, d.get("actor") or PROPOSER, state["status"], state.get("note") or None)
        return {}

    # --- the operations
    def guest_ref(self, guest: str) -> str:
        return guest_ref(self.guard, guest)

    def new_proposal(self, kind: str, params: dict[str, Any], guest: str, reason: str = "",
                     evidence: list[str] | None = None) -> ActionProposal:
        """A validated proposal (pydantic.ValidationError when the parameters are not one)."""
        t = self.now()
        return ActionProposal(
            id=uuid.uuid4(), kind=kind, params=params, reason=reason[:300],
            evidence=[e[:200] for e in (evidence or [])[:8]], guest=self.guest_ref(guest),
            created_at=t, expires_at=t + self.ttl_s,
        )

    def start(self, proposal: ActionProposal) -> dict[str, Any]:
        """Propose and precheck: the thread stops at the approval (or ends refused)."""
        pid = str(proposal.id)
        self._started += 1
        if self._started % 200 == 1:  # now and then, like the guests themselves (guests.py)
            self.lapse(self.now() - self.keep_s)
        self.graph.invoke({"proposal": proposal.model_dump(mode="json")}, self._config(pid),
                          durability="sync")
        return self.view(pid)

    def _lock(self, pid: str) -> threading.Lock:
        return self._locks[int(hashlib.sha256(pid.encode()).hexdigest()[:8], 16) % 64]

    def _drive(self, pid: str) -> None:
        """Carry a decided proposal's thread on, once: from the approval with the decision the
        ledger holds, or from wherever an earlier run stopped (a crash, an error). Whoever holds
        the proposal's lock and finds the thread waiting moves it; everyone after finds it
        moved. Across instances, the execution claim still keeps the action to one."""
        from langgraph.types import Command

        with self._lock(pid):
            snap = self.graph.get_state(self._config(pid))
            if not snap.next:
                return
            if "approval" in snap.next:
                row = self.ledger.proposal(pid)
                verdict = {"approved": "approved", "rejected": "rejected",
                           "expired": "expired"}.get(row["status"] if row else "")
                if verdict is None:
                    return  # still pending, or moved on without this thread
                decision = {"verdict": verdict, "actor": row.get("decided_by") or "clock",
                            "role": "operator" if row.get("decided_by") else "",
                            "at": row.get("decided_at") or self.now()}
                self.graph.invoke(Command(resume=decision), self._config(pid), durability="sync")
            else:
                self.graph.invoke(None, self._config(pid), durability="sync")

    def _expire(self, row: dict) -> None:
        if self.ledger.transition(row["id"], "pending", "expired", note="expired"):
            self.guard.record_event(
                "clock", "action_proposal",
                {"id": row["id"], "kind": row["kind"], "params": row["params"],
                 "payload_hash": row["payload_hash"]},
                "EXPIRED", "no decision before the proposal expired",
                id=audit_id(row["id"], "expired"),
            )
        self._drive(row["id"])

    @staticmethod
    def recorded_verdict(row: dict) -> str | None:
        """The decision a proposal row records: approved (whatever happened after), rejected,
        or None (undecided, refused by the precheck, expired)."""
        if row["status"] == "rejected":
            return "rejected"
        if row.get("decided_by") and row["status"] in ("approved", "executing", "done",
                                                       "unknown", "refused", "expired"):
            return "approved"
        return None

    def decide(self, proposal_id: str, verdict: str, presented_hash: str,
               operator: Any) -> Outcome:
        """An operator's decision on a proposal, checked in order and failing closed."""
        if operator is None or not getattr(operator, "may_approve", False):
            return Outcome(403, "only a signed-in operator decides")
        want = DECIDED.get(verdict)
        if want is None:
            return Outcome(422, "verdict is approve or reject")
        pid = _uuid(proposal_id)
        row = self.ledger.proposal(pid) if pid else None
        if row is None:
            return Outcome(404, "no such proposal")
        if row["status"] == "pending" and self.now() > row["expires_at"]:
            self._expire(row)
            return Outcome(410, "the proposal expired", self.view(pid))
        if row["status"] == "expired" and not row.get("decided_by"):
            return Outcome(410, "the proposal expired", self.view(pid))
        if not hmac.compare_digest(str(presented_hash or ""), row["payload_hash"]):
            return Outcome(409, "this is not the payload the proposal holds", self.view(pid))
        at = self.now()
        if self.ledger.transition(pid, "pending", want, decided_by=operator.name, decided_at=at):
            self.guard.record_event(
                operator.name, "action_proposal",
                {"id": pid, "kind": row["kind"], "params": row["params"],
                 "payload_hash": row["payload_hash"]},
                want.upper(), None, id=audit_id(pid, want),
            )
        else:
            row = self.ledger.proposal(pid)
            recorded = self.recorded_verdict(row)
            if recorded != want:
                return Outcome(409, f"the proposal is {row['status']}", self.view(pid))
        self._drive(pid)
        return Outcome(200, "decided", self.view(pid))

    def view(self, proposal_id: str) -> dict[str, Any] | None:
        """The proposal as the card shows it, its execution included; a pending one past its
        expiry is expired first."""
        row = self.ledger.proposal(proposal_id) if _uuid(proposal_id) else None
        if row is None:
            return None
        if row["status"] == "pending" and self.now() > row["expires_at"]:
            self._expire(row)
            row = self.ledger.proposal(proposal_id)
        ex = self.ledger.execution(proposal_id)
        return {
            "id": row["id"], "kind": row["kind"], "params": row["params"],
            "summary": describe(row["kind"], row["params"]), "reason": row["reason"],
            "evidence": row["evidence"], "payload_hash": row["payload_hash"],
            "status": row["status"], "precheck": row["precheck"], "note": row.get("note"),
            "created_at": row["created_at"], "expires_at": row["expires_at"],
            "decided_by": row.get("decided_by"), "decided_at": row.get("decided_at"),
            "final": row["status"] in action_ledger.FINAL,
            "execution": None if ex is None else {
                "state": ex["state"], "order_id": ex.get("order_id"),
                "seen": (ex.get("result") or {}).get("seen"),
            },
        }

    def owned_by(self, proposal_id: str, guest: str | None) -> bool:
        row = self.ledger.proposal(proposal_id) if _uuid(proposal_id) else None
        return bool(row and guest and hmac.compare_digest(row["guest"], self.guest_ref(guest)))

    def listing(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return [v for r in self.ledger.proposals(status, limit) if (v := self.view(r["id"]))]

    def forget(self, guest: str) -> int:
        """A guest asked to be forgotten: their proposals, executions and threads go; the audit
        keeps the operator's name and the guest only as the hash it always had."""
        threads = self.ledger.forget(self.guest_ref(guest))
        for t in threads:
            self.saver.delete_thread(t)
        return len(threads)

    def lapse(self, before: float) -> int:
        threads = self.ledger.lapse(before)
        for t in threads:
            self.saver.delete_thread(t)
        return len(threads)

    def history(self, proposal_id: str) -> list[tuple[str, ...]]:
        """The thread's steps, oldest first (what each checkpoint was about to run)."""
        snaps = list(self.graph.get_state_history(self._config(proposal_id)))
        return [s.next for s in reversed(snaps)]


# --- the switch
def mode(env: dict | None = None) -> str:
    """STF_AGENT_ACTUATION: propose turns guarded actions on; anything else is off."""
    env = os.environ if env is None else env
    return "propose" if env.get("STF_AGENT_ACTUATION", "").strip().lower() == "propose" else "off"


_ACTIONS: Actions | None = None
_LOCK = threading.Lock()


def guest_ref(guard: actuation.ActionGuard, guest: str) -> str:
    """A guest as the ledger knows it: a keyed hash, stable across restarts, never the id."""
    return hmac.new(guard.derive("guest"), guest.encode(), hashlib.sha256).hexdigest()[:32]


def forget_guest(guest: str) -> int:
    """DELETE /guest: the guest's proposals, executions and checkpoint threads go, whether
    actions are on now or were on before. The audit keeps the guest only as its hash."""
    if _ACTIONS is not None:
        return _ACTIONS.forget(guest)
    guard = actuation.get_guard()
    if guard.ledger is None:
        return 0
    threads = guard.ledger.forget(guest_ref(guard, guest))
    if threads:
        saver, _ = _saver(guard.ledger)
        for t in threads:
            saver.delete_thread(t)
    return len(threads)


def _saver(ledger: action_ledger.Ledger):
    try:
        return ledger.saver(), ""
    except ImportError:
        if isinstance(ledger, action_ledger.PgLedger):
            raise
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver(), " (langgraph-checkpoint-sqlite missing: approvals kept in memory)"


def status() -> tuple[Actions | None, str]:
    """The process's actions and a reason: (actions, "") when they are on, (None, why) when
    they are off. The why is safe to show anyone; it names settings, never values."""
    global _ACTIONS
    if mode() != "propose":
        return None, "STF_AGENT_ACTUATION is not propose"
    if _ACTIONS is not None:
        return _ACTIONS, ""
    guard = actuation.get_guard()
    if guard.secret_problem:
        return None, guard.secret_problem
    if guard.ledger is None:
        return None, guard.ledger_note or "no ledger"
    with _LOCK:
        if _ACTIONS is None:
            try:
                saver, note = _saver(guard.ledger)
            except Exception as exc:  # the database is down: every read question still works
                logger.warning("Actions unavailable, no checkpointer: %s", exc)
                return None, "actions unavailable: the checkpointer cannot be reached"
            if note:
                logger.warning("Actions%s", note)
            _ACTIONS = Actions(guard, guard.ledger, saver)
    return _ACTIONS, ""


def reset() -> None:
    """Forget the process's actions (tests; a changed configuration)."""
    global _ACTIONS
    _ACTIONS = None
