"""
Serialisation between the kernel and the browser.

Two payloads:

* the *scene descriptor* (:func:`scene_descriptor`) is sent once, over REST. It
  is the layout reduced to what a renderer needs to build its scene graph -
  slot poses, joint axes and limits, conveyor placement. The browser draws the
  factory from this and from nothing hardcoded, so moving a shelf in the layout
  YAML moves it in 3D with no front-end change.

* the *frame* (:func:`frame`) is the live hot state, sent many times a second
  over the WebSocket. It carries only what changes: joint positions, tracking
  error, per-motor telemetry, belt and sensors.

JSON for now. The binary hot-frame codec in the plan is a bandwidth
optimisation for later; correctness first.
"""

from __future__ import annotations

from stf_kernel import WorldState
from stf_layout import Layout


def _axis(ax) -> dict:
    return {"count": ax.count, "pitch": ax.pitch, "labels": ax.labels}


def scene_descriptor(layout: Layout) -> dict:
    """Everything the front end needs to build the scene, once."""
    rack = layout.main_rack
    return {
        "fingerprint": layout.fingerprint(),
        "scene_scale": layout.render.scene_scale,
        "up": layout.frame.up,
        "joint_refs": layout.joint_refs(),
        "devices": {
            name: {
                "kind": dev.kind.value,
                "base": list(dev.base.xyz),
                "tool": dev.tool,
                "joints": {
                    jname: {
                        "kind": joint.kind.value,
                        "axis": joint.axis.value,
                        "limits": list(joint.limits),
                        "home": joint.home,
                        "positions": dict(joint.positions),
                        "motor_id": joint.motor_id,
                    }
                    for jname, joint in dev.joints.items()
                },
            }
            for name, dev in layout.devices.items()
        },
        "rack": {
            "origin": list(rack.origin.xyz),
            "rows": _axis(rack.rows),
            "cols": _axis(rack.cols),
            "order": rack.order.value,
            "slot_envelope": list(rack.slot_envelope),
            "slots": {slot: list(layout.slot_pose(slot).xyz) for slot in rack.slot_names},
        },
        "conveyor": {
            "pose": list(layout.conveyor.pose.xyz),
            "length": layout.conveyor.length_mm,
            "width": layout.conveyor.width_mm,
            "axis": layout.conveyor.axis.value,
            "sensors": {
                name: {"at_mm": s.at_mm, "kind": s.kind.value}
                for name, s in layout.conveyor.sensors.items()
            },
        },
        "stations": {
            name: {"pose": list(st.pose.xyz), "description": st.description}
            for name, st in layout.stations.items()
        },
        "modules": {
            name: {"origin": list(m.origin.xyz), "size": list(m.size), "label": m.label}
            for name, m in layout.modules.items()
        },
    }


def frame(state: WorldState, seq: int) -> dict:
    """The live hot state for one broadcast tick."""
    return {
        "type": "frame",
        "seq": seq,
        "t": round(state.sim_time, 3),
        "busy": state.busy,
        "joints": {ref: round(v, 3) for ref, v in state.joints.items()},
        "tracking_error": {ref: round(v, 4) for ref, v in state.tracking_error.items()},
        "motors": {
            cid: {
                "amps": m["current_amps"],
                "health": m["health_score"],
                "phase": m["phase"],
            }
            for cid, m in state.motors.items()
        },
        "belt": {
            "position": round(state.belt_position_mm, 2),
            "object": (
                round(state.belt_object_mm, 2) if state.belt_object_mm is not None else None
            ),
        },
        "sensors": state.sensors,
    }
