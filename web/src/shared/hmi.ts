// Upgrade 4 helpers shared by the HMI panel and the U4 blueprint: what every
// unit is doing at time t of the orchestrator's nominal run (control.py).
import type { ControlDoc, GanttBar } from "../shared/model";

export const JOB_COL: Record<string, string> = {
  retrieve: "#4f8fd6", fetch_empty: "#7fb0e6", store: "#2d5f99",
  belt_fwd: "#9aa7b4", belt_back: "#6c7884",
  belt_to_oven: "#e0a02a", belt_to_buf: "#c9b458", buf_to_oven: "#d18a3a", bay_to_belt: "#b07ad6",
  bake: "#e0503a", to_tt: "#e07a5a", saw_eject: "#c05050",
  ovenbelt: "#3ea55a", sort: "#2f9e8f",
};

export const JOB_SAY: Record<string, string> = {
  retrieve: "crane: cookie mould rack → belt", fetch_empty: "crane: empty mould rack → belt",
  store: "crane: mould belt → rack", belt_fwd: "belt out (RP1, RP2)", belt_back: "belt back (RP2, RP1)",
  belt_to_oven: "VGR: belt → Ofenschieber", belt_to_buf: "VGR: belt → buffer", buf_to_oven: "VGR: buffer → Ofenschieber",
  bay_to_belt: "VGR: bay → empty mould", bake: "oven: in, bake, out", to_tt: "Sauger: slider → Drehtisch",
  saw_eject: "Drehtisch: saw, eject", ovenbelt: "oven belt → sorting", sort: "sort: A4 check, eject",
};

export type UnitNow = { unit: string; label: string; state: string; job?: string; step?: string; bar?: GanttBar };

export function unitsAt(c: ControlDoc, t: number): UnitNow[] {
  const bars = c.policies[c.policy].bars ?? [];
  return Object.entries(c.units).map(([u, d]) => {
    const bar = bars.find((b) => b.units.includes(u) && b.t0 <= t && t < b.t1);
    if (!bar) return { unit: u, label: d.label, state: "READY" };
    const mine = (bar.steps ?? []).filter((s) => s[0] === u);
    const k = mine.findIndex((s) => s[2] <= t && t < s[3]);
    // the SFC state of that step: the unit's k-th step of this job
    const sid = `${bar.job}.${String(k + 1).padStart(2, "0")}`;
    const say = k >= 0 ? d.states.find((s) => s.id === sid)?.say ?? mine[k][1] : undefined;
    // a unit held by a job whose current step belongs to another unit is waiting on it
    return { unit: u, label: d.label, state: k >= 0 ? "RUN" : "HELD", job: bar.job, step: say, bar };
  });
}

export function makespan(c: ControlDoc) {
  return c.policies[c.policy].makespan ?? 0;
}

export const fmtT = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
