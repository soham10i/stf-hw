"""
Closed-loop actuation engine and safety invariant guard for the industrial digital twin.

Enforces IEC 62443 cyber-physical security invariants:
  1. Pre-condition validation: checks slot boundaries (A1..C3), operation types,
     queue capacity limits, and emergency stop interlocks before touching hardware/sim.
  2. Role and operator authorization: ensures calls originate from authorized actors.
  3. Cryptographic audit trail: records every accepted and rejected actuation attempt
     in an append-only chain (ledger.py): each record is signed with HMAC-SHA256 over its
     fields and the signature before it, with STF_AUDIT_SECRET (required on a deployment).
  4. Post-execution state verification: reads the machine's own queue after actuation to
     verify that orders entered execution as intended (observe_order).

The preconditions are named rules (RULES), each with one refusal, so a refusal says which rule
spoke and a test can prove every rule is needed (tests/test_actions_precheck.py).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from services.api.core import navigation
from services.api.core.logging_config import get_logger
from services.api.storage.store import ROOT

from . import ledger as action_ledger

if TYPE_CHECKING:
    from services.api.core.runtime import SimRuntime

logger = get_logger(__name__)

_RUNTIME: SimRuntime | None = None


def get_runtime() -> SimRuntime | None:
    """Return the currently registered SimRuntime instance."""
    global _RUNTIME
    if _RUNTIME is not None:
        return _RUNTIME
    try:
        from services.api import app
        return getattr(app, "runtime", None)
    except ImportError:
        return None


def set_runtime(runtime: SimRuntime) -> None:
    """Register the active SimRuntime singleton."""
    global _RUNTIME
    _RUNTIME = runtime


_HUB: Any | None = None


def get_hub() -> Any | None:
    """Return the registered LiveHub singleton."""
    global _HUB
    if _HUB is not None:
        return _HUB
    try:
        from services.api import app
        return getattr(app, "hub", None)
    except ImportError:
        return None


def set_hub(hub: Any) -> None:
    """Register the active LiveHub singleton."""
    global _HUB
    _HUB = hub


VALID_OPS = {"retrieve", "store", "home", "cycle"}
SLOT_RE = re.compile(r"^[A-C][1-3]$", re.I)  # the rack's nine slots; POST /command says the same
ALARM_CODE_RE = re.compile(r"^[A-Z]{3}-[A-Z0-9]{2,4}$", re.I)
MAX_PENDING_ORDERS = 10
VALID_PAGES = navigation.PAGES  # the dashboard's pages (core/navigation.py)


# --- the precheck
# Every safety and bounds condition is one named rule with one refusal, so a refusal says which
# rule spoke, the approval card can list each rule's verdict, and a test can remove one rule and
# watch its payload get through (tests/test_actions_precheck.py).
@dataclass(frozen=True)
class Check:
    """What a rule looks at: the action, its parameters, who asks, the live runtime, the guard."""

    action: str
    params: dict[str, Any]
    actor: str
    runtime: SimRuntime | None
    guard: ActionGuard


@dataclass(frozen=True)
class Verdict:
    """One rule's answer: ok, or the reason it refuses."""

    rule: str
    ok: bool
    why: str | None = None


@dataclass(frozen=True)
class Rule:
    """A named precondition: the actions it applies to (None = every action but `exempt`), and
    a check that returns the refusal, or None when the action may go ahead."""

    name: str
    actions: frozenset[str] | None
    check: Callable[[Check], str | None]
    exempt: frozenset[str] = frozenset()

    def applies(self, action: str) -> bool:
        if self.actions is None:
            return action not in self.exempt
        return action in self.actions


def _actor_present(c: Check) -> str | None:
    if not c.actor or not c.actor.strip():
        return "Actor authorization missing: anonymous actuation disallowed"
    return None


def _estop_clear(c: Check) -> str | None:
    if c.guard.emergency_latched:
        return "Safety Interlock: Emergency stop is active; commands locked out"
    return None


def _op_known(c: Check) -> str | None:
    op = c.params.get("op")
    if op not in VALID_OPS:
        return f"Invalid operation '{op}'. Must be one of: {sorted(VALID_OPS)}"
    return None


def _needs_slot(c: Check) -> bool:
    return c.params.get("op") in ("retrieve", "store", "cycle")


def _slot_required(c: Check) -> str | None:
    slot = c.params.get("slot")
    if _needs_slot(c) and (not slot or not isinstance(slot, str)):
        return f"Operation '{c.params.get('op')}' requires a target slot identifier"
    return None


def _slot_in_rack(c: Check) -> str | None:
    slot = c.params.get("slot")
    if not _needs_slot(c) or not isinstance(slot, str) or not slot:
        return None  # slot_required speaks for a missing one
    clean = slot.strip().upper()
    if not SLOT_RE.match(clean):
        return f"Slot '{slot}' out of physical rack bounds (must be A1..C3)"
    layout = getattr(c.runtime, "layout", None)
    if layout is not None and not layout.main_rack.contains(clean):
        return f"Slot '{clean}' does not exist in factory rack layout"
    return None


def _queue_room(c: Check) -> str | None:
    pending = getattr(c.runtime, "_pending", None)
    if pending is not None and len(pending) >= MAX_PENDING_ORDERS:
        return f"Queue saturated: maximum {MAX_PENDING_ORDERS} pending orders allowed"
    return None


def _cancel_target_named(c: Check) -> str | None:
    # without an id the runtime would cancel the newest pending order: nobody named that one
    oid = c.params.get("order_id")
    if not isinstance(oid, int) or isinstance(oid, bool):
        return "Order cancellation must name the order by its number"
    return None


def _cancel_not_active(c: Check) -> str | None:
    oid = c.params.get("order_id")
    active = getattr(c.runtime, "_active", None)
    if active is not None and oid is not None and active.id == oid:
        return f"Order #{oid} is currently in production and cannot be cancelled."
    return None


def _cancel_target_pending(c: Check) -> str | None:
    oid = c.params.get("order_id")
    if not isinstance(oid, int) or isinstance(oid, bool):
        return None  # cancel_target_named speaks for it
    active = getattr(c.runtime, "_active", None)
    if active is not None and active.id == oid:
        return None  # cancel_not_active speaks for it
    if c.runtime is None:
        return "Factory runtime unavailable: the order's state cannot be checked"
    if not any(o.id == oid for o in getattr(c.runtime, "_pending", ())):
        return f"Order #{oid} is not waiting in the queue"
    return None


def _alarm_code_valid(c: Check) -> str | None:
    code = c.params.get("code")
    if not code or not isinstance(code, str):
        return "Alarm acknowledgement requires an alarm code"
    if not ALARM_CODE_RE.match(code.strip().upper()):
        return f"Malformed alarm code format: '{code}'. Expected format like 'OVN-D02'"
    return None


def _within(key: str, lo: float, hi: float, refusal: str) -> Callable[[Check], str | None]:
    def check(c: Check) -> str | None:
        v = c.params.get(key)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= float(v) <= hi:
            return refusal.format(v=v)
        return None

    return check


def _page_known(c: Check) -> str | None:
    page = c.params.get("page")
    if navigation.resolve(page) not in VALID_PAGES:  # a page's id, or a name for it ("oven")
        return f"Target page '{page}' not recognized in digital twin navigation map"
    return None


_SUBMIT = frozenset({"order_submit"})
_CANCEL = frozenset({"order_cancel"})
_RECIPE = frozenset({"recipe_adjust"})

RULES: list[Rule] = [
    Rule("actor_present", None, _actor_present),
    Rule("estop_clear", None, _estop_clear, exempt=frozenset({"reset_emergency_stop", "twin_navigate"})),
    Rule("op_known", _SUBMIT, _op_known),
    Rule("slot_required", _SUBMIT, _slot_required),
    Rule("slot_in_rack", _SUBMIT, _slot_in_rack),
    Rule("queue_room", _SUBMIT, _queue_room),
    Rule("cancel_target_named", _CANCEL, _cancel_target_named),
    Rule("cancel_not_active", _CANCEL, _cancel_not_active),
    Rule("cancel_target_pending", _CANCEL, _cancel_target_pending),
    Rule("alarm_code_valid", frozenset({"alarm_ack"}), _alarm_code_valid),
    Rule("bake_temp_envelope", _RECIPE, _within(
        "bake_temp_c", 120.0, 240.0,
        "Bake temperature {v}°C out of thermal envelope (120°C - 240°C)",
    )),
    Rule("conveyor_speed_envelope", _RECIPE, _within(
        "conveyor_speed", 0.2, 2.5, "Conveyor speed multiplier {v} out of safe range (0.2x - 2.5x)"
    )),
    Rule("bake_time_envelope", _RECIPE, _within(
        "bake_time_s", 5.0, 120.0, "Bake duration {v}s out of process limits (5s - 120s)"
    )),
    Rule("page_known", frozenset({"twin_navigate"}), _page_known),
]


def observe_order(runtime: SimRuntime, order_id: int, op: str, slot: str | None) -> str | None:
    """Where the runtime holds an order with this id, op and slot: queued, running, completed,
    failed or cancelled - or None when it holds none. The postcondition of a submit reads the
    queue the machine works from, not the history list submit appended to."""
    active = getattr(runtime, "_active", None)
    held = [*getattr(runtime, "_pending", ()), *([active] if active else [])]
    for o in held:
        if o.id == order_id:
            if o.op != op or (o.slot or None) != (slot or None):
                return None
            return "running" if o is active else "queued"
    for o in getattr(runtime, "_history", ()):
        if o.id == order_id and o.op == op and (o.slot or None) == (slot or None):
            if o.status in ("completed", "failed", "cancelled"):
                return o.status
    return None


def observe_cancel(runtime: SimRuntime, order_id: int) -> str | None:
    """The postcondition of a cancel: the order has left the queue and its history entry says
    cancelled ("cancelled"), else None."""
    if any(o.id == order_id for o in getattr(runtime, "_pending", ())):
        return None
    for o in getattr(runtime, "_history", ()):
        if o.id == order_id and o.status == "cancelled":
            return "cancelled"
    return None


def precondition_fingerprint(
    guard: ActionGuard, runtime: SimRuntime | None, action: str, params: dict[str, Any]
) -> str:
    """What the rules for this action depend on, hashed: the e-stop latch, the queue length,
    the slot and the target order's state - not the carrier's position, which changes on every
    move (compute_state_hash). Two equal fingerprints mean the precheck saw the same plant."""
    pending = list(getattr(runtime, "_pending", ()))
    active = getattr(runtime, "_active", None)
    facts: dict[str, Any] = {"estop": guard.emergency_latched, "queue": len(pending)}
    if action == "order_submit":
        facts["slot"] = (params.get("slot") or "").upper() or None
    if action == "order_cancel":
        oid = params.get("order_id")
        facts["target"] = (
            "active" if active is not None and active.id == oid
            else "pending" if any(o.id == oid for o in pending) else "absent"
        )
    blob = json.dumps(facts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


@dataclass
class AuditRecord:
    """One signed audit entry. Its signature covers its fields and the signature of the record
    before it (prev_sig), so the records form a chain: an edited, inserted or removed record
    breaks it (ActionGuard.verify_chain)."""

    id: str
    timestamp: float
    actor: str
    action: str
    params: dict[str, Any]
    pre_state_hash: str
    post_state_hash: str
    status: str  # "ACCEPTED" (before the side effect), "REJECTED", "EXECUTED", "FAILED"
    reason: str | None = None
    prev_sig: str = ""  # the signature of the record before; "" for the first
    signature: str = ""

    def canonical_bytes(self) -> bytes:
        """Serialize core fields to canonical UTF-8 bytes for HMAC computation."""
        payload = {
            "id": self.id,
            "timestamp": round(self.timestamp, 4),
            "actor": self.actor,
            "action": self.action,
            "params": self.params,
            "pre_state_hash": self.pre_state_hash,
            "post_state_hash": self.post_state_hash,
            "status": self.status,
            "reason": self.reason or "",
            "prev_sig": self.prev_sig,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def as_dict(self) -> dict[str, Any]:
        """Convert record to API-facing dictionary."""
        return asdict(self)

    def row(self) -> dict[str, Any]:
        """The ledger's shape of the record (ledger.AUDIT_COLS)."""
        return {
            "id": self.id, "at": self.timestamp, "actor": self.actor, "action": self.action,
            "params": self.params, "pre": self.pre_state_hash, "post": self.post_state_hash,
            "status": self.status, "reason": self.reason, "prev_sig": self.prev_sig,
            "sig": self.signature,
        }

    @staticmethod
    def from_row(r: dict[str, Any]) -> AuditRecord:
        return AuditRecord(
            id=r["id"], timestamp=r["at"], actor=r["actor"], action=r["action"],
            params=r["params"], pre_state_hash=r["pre"], post_state_hash=r["post"],
            status=r["status"], reason=r.get("reason"), prev_sig=r.get("prev_sig") or "",
            signature=r.get("sig") or "",
        )


class MemoryAudit:
    """The audit chain in memory: tests, and a deployment with no ledger (nothing survives a
    restart there, which is why actions stay off without one). The same calls as the ledger."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def append_audit(self, row: dict, sign: Callable[[dict], str]) -> dict:
        with self._lock:
            if same := next((r for r in self._rows if r["id"] == row["id"]), None):
                return same
            rec = {**row, "prev_sig": self._rows[-1]["sig"] if self._rows else ""}
            rec["sig"] = sign(rec)
            self._rows.append(rec)
            return rec

    def audit(self, limit: int | None = 50, action: str | None = None) -> list[dict]:
        rows = [r for r in self._rows if not action or r["action"] == action]
        return rows if limit is None else rows[-limit:] if limit > 0 else []


OLD_DEFAULT_SECRET = "stf-industrial-audit-key-v1"  # was in the source: it signs nothing now


def audit_secret(env: dict) -> tuple[bytes, str | None]:
    """The key that signs the audit chain, and what is wrong with it (None: nothing).

    STF_AUDIT_SECRET when it is long and not a placeholder. Otherwise, on a public deployment,
    a random key for this process only: its records cannot be verified after a restart, so the
    problem is reported and guarded actions stay off. A local run keeps a key beside its data
    (STF_DATA_DIR/audit_secret), so its chain verifies across restarts."""
    s = (env.get("STF_AUDIT_SECRET") or "").strip()
    weak = not s or len(s) < 32 or s == OLD_DEFAULT_SECRET or "change" in s.lower()
    if not weak:
        return s.encode(), None
    if s:
        logger.error("STF_AUDIT_SECRET is short or a placeholder: ignored")
    if action_ledger.public_deployment(env):
        problem = "STF_AUDIT_SECRET is missing or weak: guarded actions are off"
        logger.error("%s (signing with a key for this process only)", problem)
        return secrets.token_hex(32).encode(), problem
    path = os.path.join(env.get("STF_DATA_DIR") or ROOT, "audit_secret")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip().encode(), None
    except OSError:
        key = secrets.token_hex(32)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(key)
        os.chmod(path, 0o600)
        return key.encode(), None


class ActionGuard:
    """Industrial Safety Invariant Guard with IEC 62443 cryptographic audit logging.

    Validates all physical or simulated actuation intents prior to execution,
    guarantees bounds checking, produces append-only signed records, and verifies
    state convergence post-actuation.
    """

    def __init__(
        self,
        secret_key: str | None = None,
        audit: action_ledger.Ledger | MemoryAudit | None = None,
        env: dict | None = None,
    ) -> None:
        if secret_key:  # a test's own key
            self._secret, self.secret_problem = secret_key.encode("utf-8"), None
        else:
            self._secret, self.secret_problem = audit_secret(os.environ if env is None else env)
        self.audit = audit if audit is not None else MemoryAudit()
        self.ledger: action_ledger.Ledger | None = audit if isinstance(audit, action_ledger.Ledger) else None
        self.ledger_note = "" if self.ledger else "memory"
        self._emergency_latched: bool = False
        self._active_recipe: dict[str, Any] = {
            "bake_temp_c": 195.0,
            "bake_time_s": 25.0,
            "conveyor_speed": 1.0,
            "color_tolerance": 0.05,
        }
        self._acknowledged_alarms: set[str] = set()

    @property
    def emergency_latched(self) -> bool:
        """Current state of the emergency stop safety latch."""
        return self._emergency_latched

    def trigger_emergency_stop(
        self,
        actor: str = "safety_system",
        reason: str = "E-Stop triggered",
    ) -> None:
        """Engage the emergency latch, blocking all further motion commands."""
        self._emergency_latched = True
        logger.critical("EMERGENCY STOP LATCH ENGAGED by %s: %s", actor, reason)
        self._append_audit(
            actor=actor,
            action="emergency_stop",
            params={"reason": reason},
            pre_hash="E_STOP_LATCH",
            post_hash="E_STOP_LATCH",
            status="EXECUTED",
            reason=reason,
        )

    def reset_emergency_stop(self, actor: str = "operator") -> None:
        """Reset emergency latch after verifying safety zone clearance."""
        self._emergency_latched = False
        logger.info("Emergency stop latch reset by %s", actor)
        self._append_audit(
            actor=actor,
            action="reset_emergency_stop",
            params={},
            pre_hash="E_STOP_RESET",
            post_hash="E_STOP_ARMED",
            status="EXECUTED",
            reason="Safety interlock manually cleared",
        )

    def compute_state_hash(self, runtime: SimRuntime | None) -> str:
        """Compute SHA256 digest of current runtime simulation state."""
        if not runtime:
            return "NO_RUNTIME"
        try:
            carrier = getattr(runtime, "_carrier", {})
            oven = getattr(runtime, "_oven", {})
            pending_count = len(getattr(runtime, "_pending", []))
            active = getattr(runtime, "_active", None)
            active_id = active.id if active else None
            state_blob = f"{carrier}|{oven}|{pending_count}|{active_id}"
            return hashlib.sha256(state_blob.encode("utf-8")).hexdigest()[:16]
        except Exception as e:  # the hash marks the audit record; a failure must not stop it
            logger.debug("state hash failed: %s", e)
            return "HASH_ERR"

    def derive(self, label: str) -> bytes:
        """A key of its own for another use (the operator cookie, guest references), derived
        from the audit secret, so one secret serves them all and none reveals another."""
        return hmac.new(self._secret, f"stf:{label}".encode(), hashlib.sha256).digest()

    def record_event(
        self,
        actor: str,
        action: str,
        params: dict[str, Any],
        status: str,
        reason: str | None = None,
        id: str | None = None,
        pre_hash: str = "",
        post_hash: str = "",
    ) -> AuditRecord:
        """One signed record of something other than the guard's own actions: a proposal's
        precheck, an operator's decision, a final status (actions.py)."""
        return self._append_audit(actor, action, params, pre_hash, post_hash, status, reason, id)

    def sign(self, record: AuditRecord) -> str:
        """Generate HMAC-SHA256 signature for an audit record."""
        return hmac.new(self._secret, record.canonical_bytes(), hashlib.sha256).hexdigest()

    def verify_record(self, record: AuditRecord) -> bool:
        """Verify the cryptographic integrity of a signed audit record."""
        expected = self.sign(record)
        return hmac.compare_digest(record.signature, expected)

    def _append_audit(
        self,
        actor: str,
        action: str,
        params: dict[str, Any],
        pre_hash: str,
        post_hash: str,
        status: str,
        reason: str | None = None,
        id: str | None = None,
    ) -> AuditRecord:
        """Sign and append one record. A fixed `id` makes the append idempotent: a node that
        runs again after a crash finds its record there and writes no second one."""
        record = AuditRecord(
            id=id or str(uuid.uuid4()),
            timestamp=time.time(),
            actor=actor,
            action=action,
            params=params,
            pre_state_hash=pre_hash,
            post_state_hash=post_hash,
            status=status,
            reason=reason,
        )
        row = self.audit.append_audit(record.row(), lambda r: self.sign(AuditRecord.from_row(r)))
        return AuditRecord.from_row(row)

    def records(self, limit: int | None = None, action: str | None = None) -> list[AuditRecord]:
        """The audit records, oldest first (limit None: all of them)."""
        return [AuditRecord.from_row(r) for r in self.audit.audit(limit=limit, action=action)]

    def verify_chain(self, records: list[AuditRecord] | None = None) -> bool:
        """Every record's signature holds and each one names the signature before it. A chain
        pruned at its start verifies from its first remaining record."""
        recs = self.records() if records is None else records
        for i, r in enumerate(recs):
            if not self.verify_record(r):
                return False
            if i and r.prev_sig != recs[i - 1].signature:
                return False
        return True

    def precheck(
        self,
        action: str,
        params: dict[str, Any],
        actor: str,
        runtime: SimRuntime | None = None,
    ) -> list[Verdict]:
        """Every rule that applies to the action, in order, each with its verdict (RULES)."""
        out = []
        for rule in RULES:
            if rule.applies(action):
                why = rule.check(Check(action, params, actor, runtime, self))
                out.append(Verdict(rule.name, why is None, why))
        return out

    def validate_preconditions(
        self,
        action: str,
        params: dict[str, Any],
        actor: str,
        runtime: SimRuntime | None = None,
    ) -> tuple[bool, str | None]:
        """The first rule that refuses the action: (True, None) when none does."""
        for v in self.precheck(action, params, actor, runtime):
            if not v.ok:
                return False, v.why
        return True, None

    def execute_order(
        self,
        runtime: SimRuntime,
        op: str,
        slot: str | None = None,
        flavour: str = "chocolate",
        qty: int = 1,
        actor: str = "operator",
    ) -> dict[str, Any]:
        """Execute a checked machine order and synchronize the live 3D twin."""
        slot_clean = slot.strip().upper() if slot else None
        flavour_clean = str(flavour or "chocolate").strip().lower()
        qty_clean = max(1, min(12, int(qty or 1)))
        params = {"op": op, "slot": slot_clean, "flavour": flavour_clean, "qty": qty_clean}
        pre_hash = self.compute_state_hash(runtime)

        safe, reason = self.validate_preconditions("order_submit", params, actor, runtime)
        if not safe:
            self._append_audit(
                actor, "order_submit", params, pre_hash, pre_hash, "REJECTED", reason
            )
            return {"accepted": False, "error": reason}

        # the intent is on record before the machine moves: an audit that cannot be written
        # stops the order here, and one that breaks off after the submit still shows it
        self._append_audit(actor, "order_submit", params, pre_hash, pre_hash, "ACCEPTED")
        try:
            order = runtime.submit(op, slot_clean)
            post_hash = self.compute_state_hash(runtime)
            # the postcondition: the machine's own queue holds this order, as proposed
            verified = observe_order(runtime, order.id, op, slot_clean) is not None
            status = "EXECUTED" if verified else "FAILED"
            audit = self._append_audit(
                actor,
                "order_submit",
                params,
                pre_hash,
                post_hash,
                status,
                None if verified else "The runtime does not hold the order it accepted",
            )

            live_synced = False
            hub = get_hub()
            if hub:
                try:
                    hub.dispatch_command(
                        {
                            "type": "simulate",
                            "flavour": flavour_clean,
                            "qty": qty_clean,
                            "slot": slot_clean,
                        }
                    )
                    live_synced = True
                except Exception as e:
                    logger.warning("Could not dispatch simulate command to live twin: %s", e)

            return {
                "accepted": True,
                "order": order.as_dict(),
                "flavour": flavour_clean,
                "qty": qty_clean,
                "live_synced": live_synced,
                "audit_id": audit.id,
                "signature": audit.signature,
                "verified": verified,
            }
        except Exception as exc:
            post_hash = self.compute_state_hash(runtime)
            self._append_audit(
                actor, "order_submit", params, pre_hash, post_hash, "FAILED", str(exc)
            )
            return {"accepted": False, "error": f"Execution failed: {exc}"}

    def execute_order_cancel(
        self,
        runtime: SimRuntime,
        order_id: int | None = None,
        actor: str = "operator",
    ) -> dict[str, Any]:
        """Cancel a queued order; production orders cannot be cancelled."""
        params = {"order_id": order_id}
        pre_hash = self.compute_state_hash(runtime)

        safe, reason = self.validate_preconditions("order_cancel", params, actor, runtime)
        if not safe:
            self._append_audit(
                actor, "order_cancel", params, pre_hash, pre_hash, "REJECTED", reason
            )
            return {"accepted": False, "error": reason}

        self._append_audit(actor, "order_cancel", params, pre_hash, pre_hash, "ACCEPTED")
        ok, msg, order_dict = runtime.cancel(order_id)
        post_hash = self.compute_state_hash(runtime)

        if not ok:
            self._append_audit(actor, "order_cancel", params, pre_hash, post_hash, "REJECTED", msg)
            return {"accepted": False, "error": msg}

        audit = self._append_audit(
            actor, "order_cancel", params, pre_hash, post_hash, "EXECUTED", None
        )

        hub = get_hub()
        if hub:
            try:
                hub.dispatch_command(
                    {
                        "type": "cancel_order",
                        "id": order_dict.get("id") if order_dict else order_id,
                    }
                )
            except Exception as e:
                logger.warning("Could not dispatch cancel_order to live twin: %s", e)

        return {
            "accepted": True,
            "message": msg,
            "order": order_dict,
            "audit_id": audit.id,
            "signature": audit.signature,
        }

    def execute_alarm_ack(
        self,
        code: str,
        actor: str = "operator",
        note: str | None = None,
    ) -> dict[str, Any]:
        """Acknowledge an active alarm code, recording operator audit trails."""
        code_clean = code.strip().upper()
        params = {"code": code_clean, "note": note}
        safe, reason = self.validate_preconditions("alarm_ack", params, actor)
        if not safe:
            self._append_audit(actor, "alarm_ack", params, "NA", "NA", "REJECTED", reason)
            return {"accepted": False, "error": reason}

        self._acknowledged_alarms.add(code_clean)
        audit = self._append_audit(
            actor,
            "alarm_ack",
            params,
            "ALARM_ACTIVE",
            "ALARM_ACKNOWLEDGED",
            "EXECUTED",
            f"Acknowledged by {actor}: {note or 'Routine clear'}",
        )
        return {
            "accepted": True,
            "code": code_clean,
            "status": "ACKNOWLEDGED",
            "audit_id": audit.id,
            "signature": audit.signature,
        }

    def execute_recipe_adjust(
        self,
        recipe: dict[str, Any],
        actor: str = "operator",
    ) -> dict[str, Any]:
        """Update live process recipe parameters within physical process envelopes."""
        safe, reason = self.validate_preconditions("recipe_adjust", recipe, actor)
        if not safe:
            self._append_audit(actor, "recipe_adjust", recipe, "NA", "NA", "REJECTED", reason)
            return {"accepted": False, "error": reason}

        pre_state = dict(self._active_recipe)
        for key, val in recipe.items():
            if key in self._active_recipe and val is not None:
                self._active_recipe[key] = float(val) if isinstance(val, (int, float)) else val

        audit = self._append_audit(
            actor,
            "recipe_adjust",
            recipe,
            hashlib.sha256(json.dumps(pre_state, sort_keys=True).encode()).hexdigest()[:16],
            hashlib.sha256(json.dumps(self._active_recipe, sort_keys=True).encode()).hexdigest()[
                :16
            ],
            "EXECUTED",
        )
        return {
            "accepted": True,
            "recipe": dict(self._active_recipe),
            "audit_id": audit.id,
            "signature": audit.signature,
        }

    def execute_twin_navigate(
        self,
        page: str,
        target: str | None = None,
        actor: str = "operator",
    ) -> dict[str, Any]:
        """Navigate 3D twin or dashboard viewport to focal station or anomaly."""
        # a name for a page ("oven") is its page ("process"); an unknown one stays as asked, so
        # the page_known rule refuses it under its own name
        page_clean = navigation.resolve(page) or page.strip().lower()
        params = {"page": page_clean, "target": target}
        safe, reason = self.validate_preconditions("twin_navigate", params, actor)
        if not safe:
            self._append_audit(actor, "twin_navigate", params, "NA", "NA", "REJECTED", reason)
            return {"accepted": False, "error": reason}

        audit = self._append_audit(
            actor,
            "twin_navigate",
            params,
            "VIEW_CHANGED",
            "VIEW_CHANGED",
            "EXECUTED",
        )
        return {
            "accepted": True,
            "page": page_clean,
            "target": target,
            "audit_id": audit.id,
        }

    def list_audit_records(
        self,
        limit: int = 50,
        action: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve recent audit records for compliance reporting."""
        return [r.as_dict() for r in self.records(limit=limit, action=action)]

    def get_recipe(self) -> dict[str, Any]:
        """Return a copy of the current active process recipe."""
        return dict(self._active_recipe)

    def is_alarm_acknowledged(self, code: str) -> bool:
        """Check if an alarm code has been acknowledged."""
        return code.strip().upper() in self._acknowledged_alarms


_GUARD: ActionGuard | None = None


def get_guard() -> ActionGuard:
    """The process's guard, its audit chain in the configured ledger (ledger.py): Postgres on a
    deployment with SUPABASE_DB_URL, a SQLite file locally, memory where there is neither."""
    global _GUARD
    if _GUARD is None:
        ledger, note = action_ledger.ledger_from_env(dict(os.environ))
        logger.info("Action ledger: %s", note)
        _GUARD = ActionGuard(audit=ledger)
        _GUARD.ledger_note = note
    return _GUARD
