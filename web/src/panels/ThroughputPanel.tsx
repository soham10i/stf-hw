// Upgrade 10: the same machine, a faster program (throughput.py).
import { useJson } from "../shared/data";
import { Empty, Head, Stat } from "./kit";

type Tp = {
  ablation: { name: string; vc_s: number; per_hour: number; cycle_s: number; busy: Record<string, number> }[];
  measures: { id: string; say: string; marginal_s: number }[];
  tours: Record<"before" | "after", Record<string, number>>;
  oee: Record<"before" | "after", { oee: number; bottleneck: string }>;
};

export function ThroughputPanel() {
  const { data: d, error: err } = useJson<Tp>("throughput/throughput.json");
  if (err) return <Empty text="No study yet: run throughput.py." />;
  if (!d) return <Empty text="loading…" />;
  const b = d.ablation[0], a = d.ablation[d.ablation.length - 1];
  const mx = Math.max(...d.measures.map((m) => m.marginal_s), 1);
  return (
    <div className="np">
      <Head title="Throughput" sub="the same machine, a faster program" page="throughput" />
      <div className="np-stats">
        <Stat label="12-cookie order" value={`${a.vc_s} s`} sub={`was ${b.vc_s} s`} tone="ok" />
        <Stat label="Cookies / hour" value={`${a.per_hour}`} sub={`was ${b.per_hour}`} tone="ok" />
        <Stat label="OEE" value={`${Math.round(d.oee.after.oee * 100)} %`} sub={`was ${Math.round(d.oee.before.oee * 100)} %`} />
        <Stat label="Bottleneck" value={d.oee.after.bottleneck} sub={`was ${d.oee.before.bottleneck}`} tone="warn" />
      </div>
      <h4 className="np-h">What each change is worth</h4>
      <div className="np-list">
        {d.measures.filter((m) => m.marginal_s > 0.5).map((m) => (
          <div key={m.id} className="np-row accent" title={m.say}><span>{m.id}</span><i><em style={{ width: `${(m.marginal_s / mx) * 100}%` }} /></i><b>{m.marginal_s} s</b></div>
        ))}
      </div>
      <h4 className="np-h">In the 3D view</h4>
      <p className="np-foot">The arm now flies the blended path: it crosses at the lowest height the collision sweep proves clear and swings
        while it climbs. Belt → oven tour {d.tours.before.belt_to_oven} s → {d.tours.after.belt_to_oven} s.</p>
    </div>
  );
}
