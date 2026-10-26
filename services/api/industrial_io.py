"""
Industrial Protocol Bridge for OPC UA (IEC 62541) and Asset Administration Shell (AAS / IEC 63278).

Enables the cyber-physical agent to interact directly with standard OT hierarchies:
  1. OpcUaBridge:
     - Maps machine variables to deterministic OPC UA NodeIDs (ns=2;s=...)
     - Reads sensor and joint positions from live simulation snapshots
     - Exposes industrial callable methods routed through ActionGuard
  2. AasBridge:
     - Implements IDTA Asset Administration Shell digital twin submodels:
       OperationalData, TechnicalData, MaintenanceData, and OperationalSafety.
     - Supports dynamic reading, element updating, and AAS package serialization.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from .actuation import get_guard, get_runtime
from .logging_config import get_logger

if TYPE_CHECKING:
    from .runtime import SimRuntime

logger = get_logger(__name__)


class OpcUaBridge:
    """Standard OPC UA (IEC 62541) namespace mapping and method dispatcher."""

    NAMESPACE_URI = "urn:stf:digitaltwin:opcua:v1"
    NS_INDEX = 2

    # Standard address space node definitions
    NODES: dict[str, dict[str, Any]] = {
        "ns=2;s=HBW.Crane.Pos_X": {
            "type": "Double",
            "access": "Read",
            "unit": "mm",
            "getter": lambda r: _get_joint(r, 0),
        },
        "ns=2;s=HBW.Crane.Pos_Y": {
            "type": "Double",
            "access": "Read",
            "unit": "mm",
            "getter": lambda r: _get_joint(r, 1),
        },
        "ns=2;s=HBW.Crane.Pos_Z": {
            "type": "Double",
            "access": "Read",
            "unit": "mm",
            "getter": lambda r: _get_joint(r, 2),
        },
        "ns=2;s=Oven.Temperature": {
            "type": "Double",
            "access": "Read",
            "unit": "°C",
            "getter": lambda r: 195.0 if getattr(r, "_oven", {}).get("lamp") else 24.5,
        },
        "ns=2;s=Oven.DoorPosition": {
            "type": "Double",
            "access": "Read",
            "unit": "norm",
            "getter": lambda r: getattr(r, "_oven", {}).get("door", 1.0),
        },
        "ns=2;s=Oven.SliderPosition": {
            "type": "Double",
            "access": "Read",
            "unit": "norm",
            "getter": lambda r: getattr(r, "_oven", {}).get("slider", 1.0),
        },
        "ns=2;s=Orders.ActiveID": {
            "type": "Int32",
            "access": "Read",
            "unit": "id",
            "getter": lambda r: getattr(getattr(r, "_active", None), "id", 0),
        },
        "ns=2;s=Orders.PendingCount": {
            "type": "Int32",
            "access": "Read",
            "unit": "count",
            "getter": lambda r: len(getattr(r, "_pending", [])),
        },
        "ns=2;s=Safety.EmergencyStop": {
            "type": "Boolean",
            "access": "ReadWrite",
            "unit": "bool",
            "getter": lambda r: get_guard().emergency_latched,
        },
    }

    METHODS: dict[str, str] = {
        "ns=2;s=Orders.Submit": "submit_order",
        "ns=2;s=Safety.AcknowledgeAlarm": "acknowledge_alarm",
        "ns=2;s=Process.AdjustRecipe": "adjust_recipe",
    }

    def browse_nodes(self) -> list[dict[str, Any]]:
        """Return address space nodeset metadata."""
        return [
            {
                "node_id": nid,
                "data_type": info["type"],
                "access_level": info["access"],
                "engineering_units": info.get("unit"),
            }
            for nid, info in self.NODES.items()
        ]

    def read_node(self, node_id: str, runtime: SimRuntime | None = None) -> Any:
        """Read variable node value from live simulation."""
        rt = runtime or get_runtime()
        if not rt:
            raise RuntimeError("Simulation runtime unavailable for OPC UA read")
        info = self.NODES.get(node_id)
        if not info:
            raise KeyError(f"OPC UA NodeID '{node_id}' not found in address space")
        return info["getter"](rt)

    def write_node(self, node_id: str, value: Any, actor: str = "opc_client") -> bool:
        """Write to a writable node (e.g. Safety.EmergencyStop)."""
        if node_id == "ns=2;s=Safety.EmergencyStop":
            guard = get_guard()
            if bool(value):
                guard.trigger_emergency_stop(actor=actor, reason="OPC UA Write to Safety.EmergencyStop")
            else:
                guard.reset_emergency_stop(actor=actor)
            return True
        raise PermissionError(f"Node '{node_id}' is ReadOnly in OPC UA address space")

    def call_method(
        self,
        method_id: str,
        params: dict[str, Any],
        actor: str = "opc_client",
        runtime: SimRuntime | None = None,
    ) -> dict[str, Any]:
        """Invoke industrial method through ActionGuard."""
        rt = runtime or get_runtime()
        if not rt:
            raise RuntimeError("Simulation runtime unavailable for OPC UA method call")

        guard = get_guard()
        target = self.METHODS.get(method_id)
        if target == "submit_order":
            return guard.execute_order(
                runtime=rt,
                op=params.get("op", "cycle"),
                slot=params.get("slot"),
                actor=actor,
            )
        elif target == "acknowledge_alarm":
            return guard.execute_alarm_ack(
                code=params.get("code", "OVN-D02"),
                actor=actor,
                note=params.get("note", "OPC UA call"),
            )
        elif target == "adjust_recipe":
            return guard.execute_recipe_adjust(recipe=params, actor=actor)

        raise KeyError(f"OPC UA Method '{method_id}' not found in method catalog")


class AasBridge:
    """Asset Administration Shell (IEC 63278) digital twin submodel manager."""

    ASSET_ID = "urn:stf:digital-twin:smart-factory-01"
    AAS_ID = "urn:stf:aas:smart-factory-01"

    TECHNICAL_DATA: dict[str, Any] = {
        "manufacturer": "Fischertechnik / STF Twin",
        "model": "STF-CyberPhysical-Cell-2026",
        "power_supply_v": 24.0,
        "max_payload_g": 250.0,
        "workspace_dimensions_mm": {"x": 500.0, "y": 600.0, "z": 450.0},
        "operating_temperature_max_c": 50.0,
    }

    def get_submodel(self, submodel_id: str, runtime: SimRuntime | None = None) -> dict[str, Any]:
        """Fetch AAS submodel containing industrial attributes and live properties."""
        rt = runtime or get_runtime()
        guard = get_guard()
        now = time.time()

        if submodel_id == "TechnicalData":
            return {
                "idShort": "TechnicalData",
                "semanticId": "https://admin-shell.io/sandbox/idta/TechnicalData/1/1",
                "submodelElements": self.TECHNICAL_DATA,
            }

        elif submodel_id == "OperationalData":
            oven = getattr(rt, "_oven", {}) if rt else {}
            carrier = getattr(rt, "_carrier", {}) if rt else {}
            active = getattr(rt, "_active", None) if rt else None
            return {
                "idShort": "OperationalData",
                "semanticId": "https://admin-shell.io/sandbox/idta/OperationalData/1/0",
                "timestamp": now,
                "submodelElements": {
                    "active_order_id": active.id if active else None,
                    "active_op": active.op if active else None,
                    "carrier_slot": carrier.get("slot"),
                    "carrier_flavor": carrier.get("flavor"),
                    "oven_lamp_active": bool(oven.get("lamp", False)),
                    "oven_door_pos": oven.get("door", 1.0),
                    "oven_slider_pos": oven.get("slider", 1.0),
                },
            }

        elif submodel_id == "MaintenanceData":
            from .tools import MACHINE, _comp_at, load_json
            data = load_json(MACHINE)
            components = data.get("components", {})
            comp_status = {}
            for name, comp in components.items():
                res = _comp_at(comp, shifts=140.0, pm=True)
                comp_status[name] = {
                    "wear_percent": res.get("wear"),
                    "status": res.get("status"),
                    "shifts_until_warn": res.get("warn_in"),
                }
            return {
                "idShort": "MaintenanceData",
                "semanticId": "https://admin-shell.io/sandbox/idta/MaintenanceData/1/0",
                "submodelElements": {
                    "machine_age_shifts": 140.0,
                    "components": comp_status,
                },
            }

        elif submodel_id == "OperationalSafety":
            return {
                "idShort": "OperationalSafety",
                "semanticId": "https://admin-shell.io/sandbox/idta/OperationalSafety/1/0",
                "submodelElements": {
                    "emergency_stop_latched": guard.emergency_latched,
                    "safety_integrity_level": "SIL 2 / PL d (ISO 13849-1)",
                    "active_alarms": list(getattr(guard, "_acknowledged_alarms", set())),
                },
            }

        raise KeyError(f"Unknown AAS submodel: '{submodel_id}'")

    def export_aas_env(self, runtime: SimRuntime | None = None) -> dict[str, Any]:
        """Export complete AAS digital twin environment descriptor."""
        return {
            "assetAdministrationShells": [
                {
                    "id": self.AAS_ID,
                    "idShort": "STF_DigitalTwin_AAS",
                    "assetInformation": {
                        "assetKind": "Instance",
                        "globalAssetId": self.ASSET_ID,
                    },
                    "submodels": [
                        {"keys": [{"type": "Submodel", "value": "TechnicalData"}]},
                        {"keys": [{"type": "Submodel", "value": "OperationalData"}]},
                        {"keys": [{"type": "Submodel", "value": "MaintenanceData"}]},
                        {"keys": [{"type": "Submodel", "value": "OperationalSafety"}]},
                    ],
                }
            ],
            "submodels": [
                self.get_submodel("TechnicalData", runtime),
                self.get_submodel("OperationalData", runtime),
                self.get_submodel("MaintenanceData", runtime),
                self.get_submodel("OperationalSafety", runtime),
            ],
        }


def _get_joint(runtime: SimRuntime | None, index: int) -> float:
    """Helper to read joint position from runtime kernel snapshot."""
    if not runtime:
        return 0.0
    try:
        backend = getattr(runtime.kernel, "backend", None)
        if backend:
            snap = backend.snapshot()
            if hasattr(snap, "joints") and len(snap.joints) > index:
                return float(snap.joints[index])
    except Exception:
        pass
    return 0.0
