"""
Comprehensive tests for the Industrial Cyber-Physical Agentic Twin Upgrade:
  - ActionGuard safety invariants & IEC 62443 cryptographic audit non-repudiation
  - Closed-loop actuation tools and intelligent routing
  - Proactive background telemetry watchdog anomaly detection
  - Industrial OT protocol bridges: OPC UA (IEC 62541) and AAS (IEC 63278)
  - Endpoints validation via FastAPI TestClient
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from services.api import actuation as ACT
from services.api import industrial_io as IIO
from services.api import tools as T
from services.api import watchdog as WD
from services.api.app import app, runtime


@pytest.fixture
def clean_guard():
    """Provide a fresh ActionGuard instance for isolated testing."""
    guard = ACT.ActionGuard(secret_key="test-iec-62443-secret-key")
    return guard


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)


# ============================================================================
# Phase 1: ActionGuard & Safety Invariants
# ============================================================================


def test_action_guard_order_execution_and_verification(clean_guard):
    res = clean_guard.execute_order(runtime, op="cycle", slot="B2", actor="operator")
    assert res["accepted"] is True
    assert res["verified"] is True
    assert "audit_id" in res
    assert "signature" in res

    # Check audit record
    records = clean_guard.list_audit_records()
    assert len(records) == 1
    rec = clean_guard._audit_trail[0]
    assert rec.status == "EXECUTED"
    assert clean_guard.verify_record(rec) is True


def test_action_guard_rejects_out_of_bounds_slot(clean_guard):
    res = clean_guard.execute_order(runtime, op="cycle", slot="Z9", actor="operator")
    assert res["accepted"] is False
    assert "out of physical rack bounds" in res["error"]

    # Rejection should still be recorded in the audit trail
    records = clean_guard.list_audit_records()
    assert len(records) == 1
    assert records[0]["status"] == "REJECTED"
    assert clean_guard.verify_record(clean_guard._audit_trail[0]) is True


def test_action_guard_rejects_missing_slot(clean_guard):
    res = clean_guard.execute_order(runtime, op="retrieve", slot=None, actor="operator")
    assert res["accepted"] is False
    assert "requires a target slot" in res["error"]


def test_action_guard_emergency_stop_interlock(clean_guard):
    clean_guard.trigger_emergency_stop(actor="safety_sensor", reason="Light curtain violated")
    assert clean_guard.emergency_latched is True

    # Attempt motion command while latched
    res = clean_guard.execute_order(runtime, op="cycle", slot="A1", actor="operator")
    assert res["accepted"] is False
    assert "Emergency stop is active" in res["error"]

    # Reset latch
    clean_guard.reset_emergency_stop(actor="authorized_operator")
    assert clean_guard.emergency_latched is False

    # Motion commands should succeed again
    res = clean_guard.execute_order(runtime, op="cycle", slot="A1", actor="operator")
    assert res["accepted"] is True


def test_action_guard_cryptographic_tamper_detection(clean_guard):
    clean_guard.execute_order(runtime, op="home", slot=None, actor="operator")
    rec = clean_guard._audit_trail[-1]
    assert clean_guard.verify_record(rec) is True

    # Tamper with the record params
    tampered_rec = ACT.AuditRecord(
        id=rec.id,
        timestamp=rec.timestamp,
        actor=rec.actor,
        action=rec.action,
        params={"op": "cycle", "slot": "C3"},  # altered params
        pre_state_hash=rec.pre_state_hash,
        post_state_hash=rec.post_state_hash,
        status=rec.status,
        reason=rec.reason,
        signature=rec.signature,  # original signature
    )
    assert clean_guard.verify_record(tampered_rec) is False


def test_action_guard_alarm_acknowledgement(clean_guard):
    res = clean_guard.execute_alarm_ack(code="OVN-D02", actor="operator", note="Door sensor cleaned")
    assert res["accepted"] is True
    assert clean_guard.is_alarm_acknowledged("OVN-D02") is True

    # Malformed alarm code rejected
    res = clean_guard.execute_alarm_ack(code="INVALID!", actor="operator")
    assert res["accepted"] is False
    assert "Malformed alarm code" in res["error"]


def test_action_guard_recipe_adjust(clean_guard):
    # Valid recipe change
    res = clean_guard.execute_recipe_adjust(
        {"bake_temp_c": 210.0, "conveyor_speed": 1.2, "bake_time_s": 30.0},
        actor="operator",
    )
    assert res["accepted"] is True
    assert res["recipe"]["bake_temp_c"] == 210.0

    # Out of envelope temperature rejected
    res = clean_guard.execute_recipe_adjust({"bake_temp_c": 350.0}, actor="operator")
    assert res["accepted"] is False
    assert "out of thermal envelope" in res["error"]


def test_action_guard_twin_navigate(clean_guard):
    res = clean_guard.execute_twin_navigate(page="oven", target="door_cylinder", actor="operator")
    assert res["accepted"] is True
    assert res["page"] == "oven"

    # Invalid page rejected
    res = clean_guard.execute_twin_navigate(page="nonexistent_space", actor="operator")
    assert res["accepted"] is False


# ============================================================================
# Phase 2: Actuation Tools & Intelligent Routing
# ============================================================================


def test_tool_order_submit_execution():
    ctx = T.Ctx(client="operator-1")
    res = T.call("order_submit", {"op": "cycle", "slot": "C2"}, ctx)
    assert "accepted and verified" in res.text
    facts = dict(res.facts)
    assert facts["Operation"] == "cycle"
    assert facts["Slot"] == "C2"


def test_tool_order_submit_rejects_invalid_slot():
    ctx = T.Ctx(client="operator-1")
    res = T.call("order_submit", {"op": "cycle", "slot": "X9"}, ctx)
    assert "rejected by Safety Invariant Guard" in res.text


def test_tool_alarm_ack_execution():
    ctx = T.Ctx(client="safety-admin")
    res = T.call("alarm_ack", {"code": "HBW-C01", "note": "Rack sensor checked"}, ctx)
    assert "acknowledged and cleared" in res.text
    facts = dict(res.facts)
    assert facts["Alarm Code"] == "HBW-C01"


def test_tool_recipe_adjust_execution():
    ctx = T.Ctx()
    res = T.call("recipe_adjust", {"bake_temp_c": 190.0, "conveyor_speed": 1.1}, ctx)
    assert "updated successfully" in res.text


def test_tool_twin_navigate_execution():
    ctx = T.Ctx()
    res = T.call("twin_navigate", {"page": "warehouse", "target": "crane"}, ctx)
    assert "warehouse" in res.text
    assert res.link["page"] == "warehouse"


def test_routing_actuation_intents():
    ctx = T.Ctx()
    # Order route
    routes = T.route("bake a cookie from slot B2", ctx)
    tool_names = [r[0] for r in routes]
    assert "order_submit" in tool_names
    order_args = next(r[1] for r in routes if r[0] == "order_submit")
    assert order_args["slot"] == "B2"
    assert order_args["op"] == "cycle"

    # Alarm ack route
    routes = T.route("acknowledge alarm OVN-D02", ctx)
    assert ("alarm_ack", {"code": "OVN-D02"}) in routes

    # Recipe adjust route
    routes = T.route("set bake temperature to 205", ctx)
    assert any(r[0] == "recipe_adjust" for r in routes)

    # Twin navigate route
    routes = T.route("navigate to oven view", ctx)
    assert ("twin_navigate", {"page": "oven"}) in routes


# ============================================================================
# Phase 3: Telemetry Watchdog
# ============================================================================


def test_telemetry_watchdog_anomaly_detection():
    wd = WD.TelemetryWatchdog(runtime=runtime, poll_interval=0.5)
    wd.clear_incidents()

    # Initial scan under nominal conditions
    incidents = wd.scan_once()
    status = wd.get_status()
    assert isinstance(status, dict)

    # Simulate safety e-stop trigger and verify detection
    ACT.get_guard().trigger_emergency_stop(actor="safety_system", reason="Emergency latch test")
    incidents = wd.scan_once()
    assert any(i.category == "SAFETY" for i in incidents)

    # Reset e-stop
    ACT.get_guard().reset_emergency_stop()

    # Verify deduplication: immediately scanning again should not duplicate within cooldown
    incidents_second_pass = wd.scan_once()
    safety_incidents = [i for i in incidents_second_pass if i.category == "SAFETY"]
    assert len(safety_incidents) == 0

    # Acknowledge incident
    all_incidents = wd.list_incidents()
    assert len(all_incidents) > 0
    inc_id = all_incidents[0]["id"]
    ok = wd.acknowledge_incident(inc_id)
    assert ok is True
    assert wd.list_incidents()[0]["acknowledged"] is True


# ============================================================================
# Phase 4: Industrial Protocols (OPC UA & AAS Bridges)
# ============================================================================


def test_opcua_bridge_browse_and_read():
    bridge = IIO.OpcUaBridge()
    nodes = bridge.browse_nodes()
    assert len(nodes) == 9
    node_ids = {n["node_id"] for n in nodes}
    assert "ns=2;s=HBW.Crane.Pos_X" in node_ids
    assert "ns=2;s=Oven.Temperature" in node_ids
    assert "ns=2;s=Safety.EmergencyStop" in node_ids

    # Read values
    temp = bridge.read_node("ns=2;s=Oven.Temperature", runtime)
    assert isinstance(temp, float)

    e_stop = bridge.read_node("ns=2;s=Safety.EmergencyStop", runtime)
    assert isinstance(e_stop, bool)


def test_opcua_bridge_write_and_method_call():
    bridge = IIO.OpcUaBridge()
    # Write to emergency stop
    bridge.write_node("ns=2;s=Safety.EmergencyStop", True, actor="opc_test")
    assert ACT.get_guard().emergency_latched is True
    bridge.write_node("ns=2;s=Safety.EmergencyStop", False, actor="opc_test")
    assert ACT.get_guard().emergency_latched is False

    # Readonly node write should raise PermissionError
    with pytest.raises(PermissionError):
        bridge.write_node("ns=2;s=Oven.Temperature", 300.0)

    # Call method submit_order
    res = bridge.call_method(
        "ns=2;s=Orders.Submit",
        {"op": "cycle", "slot": "A2"},
        actor="opc_client",
        runtime=runtime,
    )
    assert res["accepted"] is True


def test_aas_bridge_submodels_and_export():
    aas = IIO.AasBridge()
    # TechnicalData
    tech = aas.get_submodel("TechnicalData", runtime)
    assert tech["idShort"] == "TechnicalData"
    assert tech["submodelElements"]["power_supply_v"] == 24.0

    # OperationalData
    op = aas.get_submodel("OperationalData", runtime)
    assert op["idShort"] == "OperationalData"
    assert "oven_door_pos" in op["submodelElements"]

    # OperationalSafety
    safety = aas.get_submodel("OperationalSafety", runtime)
    assert safety["idShort"] == "OperationalSafety"
    assert "emergency_stop_latched" in safety["submodelElements"]

    # Full Environment Export
    env = aas.export_aas_env(runtime)
    assert "assetAdministrationShells" in env
    assert len(env["submodels"]) == 4


# ============================================================================
# Phase 5: FastAPI HTTP Endpoints
# ============================================================================


def test_api_watchdog_endpoints(client):
    r = client.get("/watchdog/status")
    assert r.status_code == 200
    assert "healthy" in r.json()

    r = client.get("/watchdog/incidents")
    assert r.status_code == 200
    assert "incidents" in r.json()

    r = client.post("/watchdog/scan")
    assert r.status_code == 200
    assert r.json()["scanned"] is True


def test_api_opcua_endpoints(client):
    r = client.get("/opcua/nodes")
    assert r.status_code == 200
    assert len(r.json()["nodes"]) == 9

    r = client.get("/opcua/nodes/ns=2;s=Oven.Temperature")
    assert r.status_code == 200
    assert "value" in r.json()


def test_api_aas_endpoints(client):
    r = client.get("/aas/env")
    assert r.status_code == 200
    assert len(r.json()["submodels"]) == 4

    r = client.get("/aas/submodels/TechnicalData")
    assert r.status_code == 200
    assert r.json()["idShort"] == "TechnicalData"

    r = client.get("/aas/submodels/NonExistent")
    assert r.status_code == 404
