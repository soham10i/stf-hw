// The twin's two registries. Adding a view or a side panel is one entry here;
// the shell (App, TopBar, SidePanel) never names a view or a panel itself.
import type { ReactNode } from "react";
import type { CadDoc } from "../shared/model";
import type { SceneDescriptor } from "../types";
import { OrdersPanel } from "../panels/OrdersPanel";
import { TelemetryPanel } from "../panels/TelemetryPanel";
import { SafetyPanel } from "../panels/SafetyPanel";
import { HealthPanel } from "../panels/HealthPanel";
import { VcPanel } from "../panels/VcPanel";
import { HmiPanel } from "../panels/HmiPanel";
import { IoPanel } from "../panels/IoPanel";
import { AiPanel } from "../panels/AiPanel";
import { EnergyPanel } from "../panels/EnergyPanel";
import { ThroughputPanel } from "../panels/ThroughputPanel";
import { NetSecurityPanel } from "../panels/NetSecurityPanel";
import { HardeningPanel } from "../panels/HardeningPanel";
import { PlcPanel } from "../panels/PlcPanel";
import { VisionPanel } from "../panels/VisionPanel";
import { GeometryPanel } from "../panels/GeometryPanel";

// ---------------------------------------------------------------- views
export type ViewKind = "machine" | "controller" | "component";
export type View = { id: string; label: string; kind: ViewKind; group: string; about: string };

export const MACHINE_VIEW: View = {
  id: "factory", label: "Factory · Upgrade 12", kind: "machine", group: "Factory",
  about: "The machine with every upgrade (U1-U12): guarded, on remote I/O, run by the generated PLC program, "
    + "commissioned, monitored, hardened. Open the side panels for each layer.",
};
export const CONTROLLER_VIEW: View = {
  id: "controller", label: "Controller board · PLC I/O", kind: "controller", group: "Factory",
  about: "The 24 V adapter PCB and the PLC interface, pin by pin.",
};

export function componentViews(components: Record<string, { name: string; ft: string }> | undefined): View[] {
  return Object.entries(components ?? {}).map(([id, c]) => ({
    id, label: `${c.name} (${c.ft})`, kind: "component" as const, group: "Components",
    about: `${c.name}: sourced dimensions, materials, how it works`,
  }));
}

// --------------------------------------------------------------- panels
export type PanelCtx = {
  doc: CadDoc; scene: SceneDescriptor | null;
  showZones: boolean; setShowZones: (v: boolean) => void;
};
export type Panel = {
  id: string; label: string; icon: string;
  /** shown only when the export (or the live backend) has what it needs */
  available: (c: PanelCtx) => boolean;
  render: (c: PanelCtx) => ReactNode;
  /** 3D overlays this panel turns on while it is open */
  overlays?: { netZones?: boolean };
};

export const PANELS: Panel[] = [
  { id: "orders", label: "Orders", icon: "list", available: () => true,
    render: (c) => <OrdersPanel scene={c.scene} slots={Object.keys(c.doc.slots)} /> },
  { id: "telemetry", label: "Telemetry", icon: "activity", available: () => true,
    render: (c) => <TelemetryPanel scene={c.scene} /> },
  { id: "safety", label: "Safety", icon: "shield", available: (c) => !!c.doc.safety,
    render: (c) => <SafetyPanel sf={c.doc.safety!} showZones={c.showZones} setShowZones={c.setShowZones} /> },
  { id: "io", label: "Remote I/O", icon: "plug", available: (c) => !!(c.doc.io3 && c.doc.chains),
    render: (c) => <IoPanel io={c.doc.io3!} ch={c.doc.chains!} /> },
  { id: "hmi", label: "PLC program & HMI", icon: "monitor", available: (c) => !!c.doc.control,
    render: (c) => <HmiPanel c={c.doc.control!} /> },
  { id: "plc", label: "PLC program (live)", icon: "play", available: () => true, render: () => <PlcPanel /> },
  { id: "vision", label: "Vision inspection", icon: "eye", available: () => true, render: () => <VisionPanel /> },
  { id: "vc", label: "Commissioning", icon: "cpu", available: (c) => !!c.doc.vc, render: (c) => <VcPanel vc={c.doc.vc!} /> },
  { id: "health", label: "Health", icon: "heart", available: (c) => !!c.doc.health, render: (c) => <HealthPanel doc={c.doc} /> },
  { id: "ai", label: "AI maintenance", icon: "brain", available: () => true, render: () => <AiPanel /> },
  { id: "energy", label: "Microgrid", icon: "bolt", available: () => true, render: () => <EnergyPanel /> },
  { id: "throughput", label: "Throughput", icon: "gauge", available: () => true, render: () => <ThroughputPanel /> },
  { id: "security", label: "OT security", icon: "lock", available: (c) => !!(c.doc.io3 && c.doc.safety),
    render: () => <NetSecurityPanel />, overlays: { netZones: true } },
  { id: "hardening", label: "Defence in depth", icon: "layers", available: () => true, render: () => <HardeningPanel /> },
  { id: "geometry", label: "Geometry", icon: "cube", available: () => true, render: (c) => <GeometryPanel doc={c.doc} /> },
];
