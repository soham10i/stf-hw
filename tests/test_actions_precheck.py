"""The precheck as named rules (actuation.RULES): every rule has a payload that only it refuses,
and with that one rule removed the same payload gets through - so each test pins its own rule,
and a rule nobody tests cannot be added. Also the fixes that came with it: a real postcondition
for a submit, one slot range, and no cancellation without a named order."""

from __future__ import annotations

import pydantic
import pytest

from services.api import actuation as ACT
from services.api.app import CommandRequest
from services.api.cycle import Order
from services.api.runtime import SimRuntime

OP = "operator"


def _full_queue(rt: SimRuntime) -> None:
    for _ in range(ACT.MAX_PENDING_ORDERS):
        rt.submit("home", None)


def _active_order(rt: SimRuntime) -> None:
    rt._active = Order(id=5, op="cycle", slot="B2", status="running")


def _latch(guard: ACT.ActionGuard) -> None:
    guard._emergency_latched = True


# rule -> (action, params, actor, set up the runtime, set up the guard): refused by that rule only
CASES = {
    "actor_present": ("order_submit", {"op": "home"}, " ", None, None),
    "estop_clear": ("order_submit", {"op": "home"}, OP, None, _latch),
    "op_known": ("order_submit", {"op": "fly"}, OP, None, None),
    "slot_required": ("order_submit", {"op": "retrieve"}, OP, None, None),
    "slot_in_rack": ("order_submit", {"op": "retrieve", "slot": "C4"}, OP, None, None),
    "queue_room": ("order_submit", {"op": "home"}, OP, _full_queue, None),
    "cancel_target_named": ("order_cancel", {"order_id": None}, OP, None, None),
    "cancel_not_active": ("order_cancel", {"order_id": 5}, OP, _active_order, None),
    "cancel_target_pending": ("order_cancel", {"order_id": 99}, OP, None, None),
    "alarm_code_valid": ("alarm_ack", {"code": "BAD!"}, OP, None, None),
    "bake_temp_envelope": ("recipe_adjust", {"bake_temp_c": 300}, OP, None, None),
    "conveyor_speed_envelope": ("recipe_adjust", {"conveyor_speed": 9}, OP, None, None),
    "bake_time_envelope": ("recipe_adjust", {"bake_time_s": 1}, OP, None, None),
    "page_known": ("twin_navigate", {"page": "nowhere"}, OP, None, None),
}

# one payload per action that every rule lets through
VALID = {
    "order_submit": {"op": "retrieve", "slot": "B2"},
    "order_cancel": {"order_id": 1},
    "alarm_ack": {"code": "OVN-D02"},
    "recipe_adjust": {"bake_temp_c": 200, "conveyor_speed": 1.0, "bake_time_s": 30},
    "twin_navigate": {"page": "oven"},
}


def _setup(name: str):
    action, params, actor, rt_setup, guard_setup = CASES[name]
    rt, guard = SimRuntime(), ACT.ActionGuard(secret_key="t" * 32)
    for fn, target in ((rt_setup, rt), (guard_setup, guard)):
        if fn:
            fn(target)
    return action, params, actor, rt, guard


def test_every_rule_has_a_case():
    assert {r.name for r in ACT.RULES} == set(CASES)
    assert len({r.name for r in ACT.RULES}) == len(ACT.RULES)


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_payload_is_refused_by_its_rule_alone(name):
    action, params, actor, rt, guard = _setup(name)
    refused = [v for v in guard.precheck(action, params, actor, rt) if not v.ok]
    assert [v.rule for v in refused] == [name]
    assert refused[0].why
    ok, why = guard.validate_preconditions(action, params, actor, rt)
    assert (ok, why) == (False, refused[0].why)


@pytest.mark.parametrize("name", sorted(CASES))
def test_without_its_rule_the_payload_gets_through(name, monkeypatch):
    action, params, actor, rt, guard = _setup(name)
    monkeypatch.setattr(ACT, "RULES", [r for r in ACT.RULES if r.name != name])
    assert guard.validate_preconditions(action, params, actor, rt) == (True, None)


@pytest.mark.parametrize("action", sorted(VALID))
def test_a_valid_payload_passes_every_rule_that_applies(action):
    rt = SimRuntime()
    rt.submit("home", None)  # order #1, waiting: what the valid cancel names
    verdicts = ACT.ActionGuard(secret_key="t" * 32).precheck(action, VALID[action], OP, rt)
    assert verdicts and all(v.ok for v in verdicts)
    assert {v.rule for v in verdicts} == {r.name for r in ACT.RULES if r.applies(action)}


def test_a_latched_estop_allows_the_reset_and_moving_the_view_only():
    guard = ACT.ActionGuard(secret_key="t" * 32)
    _latch(guard)
    assert guard.validate_preconditions("reset_emergency_stop", {}, OP) == (True, None)
    # during a stop the operator most needs to look: navigation changes nothing in the factory
    assert guard.validate_preconditions("twin_navigate", {"page": "alarms"}, OP) == (True, None)
    assert not guard.validate_preconditions("order_submit", {"op": "home"}, OP)[0]


# ------------------------------------------------------------------------- the fixes with it
class HidesOrders(SimRuntime):
    """A runtime that accepts an order and then does not hold it."""

    def submit(self, op, slot):
        order = Order(id=self._next_id, op=op, slot=slot)
        self._next_id += 1
        self._history.append(order)
        return order


def test_a_submit_the_machine_does_not_hold_is_not_verified():
    guard = ACT.ActionGuard(secret_key="t" * 32)
    res = guard.execute_order(HidesOrders(), op="retrieve", slot="B2", actor=OP)
    assert res["verified"] is False
    assert guard.list_audit_records()[-1]["status"] == "FAILED"


def test_a_submit_the_machine_queues_is_verified():
    guard = ACT.ActionGuard(secret_key="t" * 32)
    res = guard.execute_order(SimRuntime(), op="retrieve", slot="B2", actor=OP)
    assert res["verified"] is True
    assert guard.list_audit_records()[-1]["status"] == "EXECUTED"


def test_observe_order_reads_the_machine_queue():
    rt = SimRuntime()
    order = rt.submit("retrieve", "B2")
    assert ACT.observe_order(rt, order.id, "retrieve", "B2") == "queued"
    assert ACT.observe_order(rt, order.id, "retrieve", "C3") is None  # another payload
    assert ACT.observe_order(rt, order.id + 1, "retrieve", "B2") is None
    rt._pending.clear()
    rt._active = order
    assert ACT.observe_order(rt, order.id, "retrieve", "B2") == "running"
    rt._active, order.status = None, "completed"
    assert ACT.observe_order(rt, order.id, "retrieve", "B2") == "completed"


def test_command_accepts_the_rack_slots_only():
    assert CommandRequest(op="retrieve", slot="C3").slot == "C3"
    with pytest.raises(pydantic.ValidationError):
        CommandRequest(op="retrieve", slot="C4")


def test_a_cancel_without_an_order_number_cancels_nothing():
    rt = SimRuntime()
    rt.submit("home", None)
    rt.submit("home", None)
    res = ACT.ActionGuard(secret_key="t" * 32).execute_order_cancel(rt, order_id=None, actor=OP)
    assert res["accepted"] is False
    assert "name the order" in res["error"]
    assert [o.id for o in rt._pending] == [1, 2]
