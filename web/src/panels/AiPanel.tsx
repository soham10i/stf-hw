// Upgrade 8: the trained network, running in this browser over the month (dashboard/ml.ts).
import { useEffect, useMemo, useState } from "react";
import { type Weights, predictAt } from "../dashboard/ml";
import { Icon } from "../shared/icons";
import { useJson } from "../shared/data";
import { Empty, Head } from "./kit";

const NICE: Record<string, string> = { cup: "VGR cup seal", door: "Oven door cyl.", lower: "Sauger cylinder", pusher: "Auswerfer cyl.",
  belt: "HBW belt", rfid: "RFID heads", spindle: "HBW spindle", gearbox: "VGR gearbox", air: "Air supply", colour: "Colour sensor" };

export function AiPanel() {
  const w = useJson<Weights>("ml/weights.json");
  const m = useJson<{ t: number[]; x: number[][]; rule_warnings: { t: number; comp: string }[];
                      maintenance: { t: number; comp: string }[] }>("ml/month_inputs.json");
  const [i, setI] = useState(-1);
  // open at the month's first U6 warning: the interesting moment, not day 1
  useEffect(() => {
    if (m.data && i < 0) {
      const w = m.data.rule_warnings[0]?.t ?? 0;
      setI(Math.max(0, m.data.t.findIndex((t) => t >= w)));
    }
  }, [m.data, i]);
  const n = m.data?.x.length ?? 1;
  const live = useMemo(() => (w.data && m.data ? predictAt(w.data, m.data.x, Math.min(i, n - 1)) : null), [w.data, m.data, i, n]);
  if (w.error || m.error) return <Empty text="No model yet: run ml.train, then ml.tune." />;
  if (!w.data || !live) return <Empty text="loading the network…" />;
  const cap = w.data.rul_cap, thr = w.data.alarm_rul;
  const rows = w.data.components.map((c, k) => ({ c, rul: live[k].rul, p: live[k].p })).sort((a, b) => a.rul - b.rul);
  const now = m.data?.t[Math.max(0, Math.min(i, n - 1))] ?? 0;
  const day = Math.floor(now / 24) + 1;
  const warn = m.data?.rule_warnings.filter((e) => e.t <= now && now - e.t < 48) ?? [];
  const next = m.data?.maintenance.find((e) => e.t >= now);
  return (
    <div className="np">
      <Head title="AI maintenance" sub="the trained network, running in this browser" page="ai" />
      <label className="np-slider"><span>Month</span>
        <input type="range" min={0} max={n - 1} value={Math.max(0, i)} onChange={(e) => setI(+e.target.value)} /><b>day {day}</b></label>
      <div className="np-events">
        {warn.map((e) => <span key={e.t} className="ui-chip warn"><Icon name="bell" size={12} />U6 rule warns: {NICE[e.comp] ?? e.comp}</span>)}
        {next && <span className="ui-chip accent"><Icon name="wrench" size={12} />next work order: {NICE[next.comp] ?? next.comp}, day {Math.floor(next.t / 24) + 1}</span>}
      </div>
      <div className="np-list">
        {rows.map((r) => {
          const tone = r.rul < thr ? "bad" : r.p[1] + r.p[2] > 0.5 ? "warn" : "ok";
          return (
            <div key={r.c} className={`np-row ${tone}`}>
              <span>{NICE[r.c] ?? r.c}</span>
              <i><em style={{ width: `${(r.rul / cap) * 100}%` }} /></i>
              <b>{Math.round(r.rul)}</b>
            </div>
          );
        })}
      </div>
      <p className="np-foot">Remaining life in orders, capped at {cap}. Red = below the tuned alarm ({thr}). Advisory beside the U6 rules.</p>
    </div>
  );
}
