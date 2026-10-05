// Upgrade 14, step 3: the cell on MQTT Sparkplug B and the Unified Namespace built from it
// (stf-cad/hbw/uns). The proofs ran a real broker, edge node and primary host; their verdicts
// and samples of the traffic are in uns.json. The static site has no broker, so the UNS values
// here come from the compiled PLC program running in this browser - the stream the edge publishes.
import { useEffect, useMemo, useState } from "react";
import { useJson } from "../shared/data";
import { Icon } from "../shared/icons";
import { useSil } from "./PlcPanel";
import { Empty, Stat } from "./kit";

const BASE = import.meta.env.BASE_URL;
const PHASES = ["homing", "running", "complete"];

type M = { name: string; alias: number | null; datatype: string; uns: string | null; properties?: Record<string, string | number> };
type Sample = { topic: string; qos: number; retain: boolean; bytes?: number; seq?: number | null; metrics?: Record<string, unknown>[];
  metric_count?: number; json?: Record<string, unknown> };
type Uns = {
  spec: string; seconds: number; traffic: Record<string, number>;
  namespace: { group: string; edge: string; host: string; uns_root: string; topics: Record<string, string>; devices: Record<string, M[]> };
  tck: { id: string; text: string; ok: boolean; checked: number; first_violation: string | null }[];
  live: { order_s: number; jobs: number; u13_order_s: number; u13_jobs: number };
  uns: { topics: number; metrics: number };
  security: Record<string, string | Record<string, string>>;
  death: { offline: boolean; stale: boolean };
  timeline: [number, string][];
  mutants: { id: string; what: string; caught: boolean; by: string | null }[];
  samples: Record<string, Sample>;
  broker: { server: string; tls: string; roles: string[] };
  fails: string[];
};
type Tree = { seg: string; topic?: string; m?: M; kids: Map<string, Tree> };
const TABS = ["Unified Namespace", "Sparkplug", "On the wire", "Specification", "Death & rebirth", "Security"] as const;

/** UNS topic -> the value the edge would publish now, from the PLC scanning in this browser. */
function useLive(ns: Uns["namespace"] | undefined, on: boolean) {
  const { sim, names, err, restart } = useSil();
  const [vals, setVals] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!sim || !on || !ns) return;
    const meta = sim.meta;
    const byAddr: Record<string, () => number | boolean> = {};
    meta.io.ix.forEach((e) => { byAddr[e.addr!] = () => !!sim.ix[e.bit!]; });
    meta.io.qx.forEach((e) => { byAddr[e.addr!] = () => !!sim.qx[e.bit!]; });
    meta.io.iw.forEach((e, i) => { byAddr[e.addr!] = () => sim.iw[i]; });
    meta.io.id.forEach((e, i) => { byAddr[e.addr!] = () => Math.round(sim.id[i] * 100) / 100; });
    const read: [string, () => unknown][] = [];
    for (const ms of Object.values(ns.devices)) for (const m of ms) {
      if (!m.uns) continue;
      const addr = m.properties?.address as string | undefined;
      const u = m.name.match(/^Units\/(\w+)\/(\w+)$/);
      if (addr && byAddr[addr]) read.push([m.uns, byAddr[addr]]);
      else if (u) {
        const i = meta.units.indexOf(u[1]);
        const sn = () => sim.mw[10 * (i + 1)], job = () => sim.mw[10 * (i + 1) + 1];
        const f: Record<string, () => unknown> = {
          State: sn, StateText: () => (sn() === 100 ? "ready" : names[u[1]]?.[sn()] ?? ""),
          Job: () => (job() ? meta.jobs[job() - 1] : ""), Busy: () => sn() >= 1000, Fault: () => sn() === 910,
          Alarm: () => sim.mw[10 * (i + 1) + 8],
        };
        if (f[u[2]]) read.push([m.uns, f[u[2]]]);
      } else {
        const f: Record<string, () => unknown> = {
          "Production/Phase": () => PHASES[sim.phase] ?? "?", "Production/JobsCompleted": () => sim.mw[1],
          "Production/MachineTime": () => sim.t.toFixed(1),
          "Production/OrderTime": () => (sim.homedAt === null ? 0 : (sim.t - sim.homedAt).toFixed(1)),
          "Production/State": () => (sim.faults.length || sim.plant.flags.length ? "OutOfService" : sim.phase === 1 ? "Executing" : "NotExecuting"),
          "Production/Run": () => 0,
        };
        if (f[m.name]) read.push([m.uns, f[m.name]]);
      }
    }
    let last = performance.now(), acc = 0, raf = 0, shown = 0;
    const frame = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      if (sim.phase !== 2 && !sim.faults.length) {
        acc += dt * 8;
        const n = Math.min(4000, Math.floor(acc / sim.dt));
        acc -= n * sim.dt;
        for (let k = 0; k < n; k++) sim.tick();
      }
      if (now - shown > 200) {
        shown = now;
        const v: Record<string, string> = {};
        for (const [t, f] of read) v[t] = String(f());
        setVals(v);
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [sim, on, ns, names]);
  return { vals, err, ready: !!sim, phase: sim?.phase ?? 0, restart };
}

function buildTree(ns: Uns["namespace"]): Tree {
  const root: Tree = { seg: ns.uns_root, kids: new Map() };
  for (const ms of Object.values(ns.devices)) for (const m of ms) {
    if (!m.uns) continue;
    let t = root;
    for (const s of m.uns.slice(ns.uns_root.length + 1).split("/")) {
      if (!t.kids.has(s)) t.kids.set(s, { seg: s, kids: new Map() });
      t = t.kids.get(s)!;
    }
    t.topic = m.uns;
    t.m = m;
  }
  return root;
}

function TopicRow({ t, depth, vals, q }: { t: Tree; depth: number; vals: Record<string, string>; q: string }) {
  const hit = (x: Tree): boolean => !q || x.seg.toLowerCase().includes(q) || [...x.kids.values()].some(hit);
  if (!hit(t)) return null;
  if (t.topic) {
    const v = vals[t.topic] ?? (t.m?.name.startsWith("Properties/") ? "" : undefined);
    const unit = t.m?.properties?.engUnit;
    return (
      <div className="ua-leaf" title={`${t.topic}\n${t.m?.properties?.description ?? ""}`}>
        <span className="ua-row"><i className="ua-cls variable">T</i><b>{t.seg}</b><em>{t.m?.datatype}</em>
          {v !== undefined && <span className={`ua-v live ${v === "true" ? "on" : ""}`}>{v}{unit && v !== "" ? ` ${unit}` : ""}</span>}</span>
      </div>
    );
  }
  // a folder that matches shows everything under it
  const sub = q && t.seg.toLowerCase().includes(q) ? "" : q;
  return (
    <details className="ua-node" open={!!q || depth < 1 || (sub === "" && q !== "")}>
      <summary><span className="ua-row"><i className="ua-cls object">/</i><b>{t.seg}</b><em>{t.kids.size}</em></span></summary>
      <div className="ua-kids">{[...t.kids.values()].map((k) => <TopicRow key={k.seg} t={k} depth={depth + 1} vals={vals} q={sub} />)}</div>
    </details>
  );
}

export function UnsPanel() {
  const { data: r, error } = useJson<Uns>("uns/uns.json");
  const [tab, setTab] = useState<(typeof TABS)[number]>("Unified Namespace");
  const [on, setOn] = useState(true);
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState("NBIRTH");
  const { vals, err, ready, phase, restart } = useLive(r?.namespace, on && tab === "Unified Namespace");
  const tree = useMemo(() => (r ? buildTree(r.namespace) : null), [r]);
  if (error) return <Empty text="No Unified Namespace: run uns/check.py." />;
  if (!r || !tree) return <Empty text="loading…" />;
  const ok = r.tck.filter((k) => k.ok).length, caught = r.mutants.filter((m) => m.caught).length;
  const metrics = Object.values(r.namespace.devices).reduce((n, ms) => n + ms.length, 0);
  const probes = (r.security["write probes"] ?? {}) as Record<string, string>;

  return (
    <div className="np ua uns">
      <div className="np-head">
        <div><b>MQTT Sparkplug B · Unified Namespace</b><span>{r.spec}</span></div>
        <a className="ui-btn" href={`${BASE}uns/uns.json`} download>JSON</a>
      </div>
      <div className="np-stats">
        <Stat label="Metrics" value={`${metrics}`} sub={`${Object.keys(r.namespace.devices).length - 1} devices + the edge node`} />
        <Stat label="Spec requirements" value={`${ok}/${r.tck.length}`} sub={`hold over ${r.traffic.messages.toLocaleString()} messages`} tone={ok === r.tck.length ? "ok" : "bad"} />
        <Stat label="Live order" value={`${r.live.order_s.toFixed(1)} s`} sub={`${r.live.jobs} jobs, as Upgrade 13`} tone="ok" />
        <Stat label="Mutants caught" value={`${caught}/${r.mutants.length}`} sub="the checks can fail" tone={caught === r.mutants.length ? "ok" : "bad"} />
      </div>

      <div className="uns-flow" aria-label="Data flow">
        <span><b>Edge node</b><small>{r.namespace.edge} · PLC (U13)</small></span><i>→</i>
        <span><b>Mosquitto</b><small>TLS 1.3 · access list</small></span><i>→</i>
        <span><b>Primary host</b><small>{r.namespace.host}</small></span><i>→</i>
        <span><b>Unified Namespace</b><small>retained JSON</small></span>
      </div>

      <div className="plc-speed aas-tabs" role="tablist">
        {TABS.map((t) => <button key={t} className={t === tab ? "on" : ""} onClick={() => setTab(t)}>{t}</button>)}
      </div>

      {tab === "Unified Namespace" && (
        <>
          <div className="plc-bar">
            <button className="ui-btn icon" onClick={() => setOn(!on)} aria-label={on ? "Pause values" : "Run values"}><Icon name={on ? "pause" : "play"} size={15} /></button>
            <button className="ui-btn" onClick={restart}>Restart order</button>
            <span className="tag">{err ? `PLC: ${err}` : !ready ? "compiling the PLC…" : `values: PLC in this browser · ${PHASES[phase]}`}</span>
          </div>
          <input className="ui-select ua-q" placeholder="Filter topics (e.g. crane, inputs, phase)" value={q}
            onChange={(e) => setQ(e.target.value.trim().toLowerCase())} aria-label="Filter topics" />
          <div className="ua-tree"><TopicRow t={tree} depth={0} vals={vals} q={q} /></div>
          <p className="np-foot">ISA-95 levels: enterprise / site / area / line / cell / module / signal. Every topic is retained, so a
            dashboard, an MES or an AI agent that subscribes late gets the whole state at once; in the proof run a late subscriber
            received {r.uns.topics} of {r.uns.metrics} topics, each equal to the host's value.</p>
        </>
      )}

      {tab === "Sparkplug" && (
        <div className="uns-sp">
          <div className="aas-ids"><span>node</span><code>{r.namespace.topics.node}</code><span>device</span><code>{r.namespace.topics.device}</code>
            <span>host</span><code>{r.namespace.topics.state}</code></div>
          {Object.entries(r.namespace.devices).map(([dev, ms]) => (
            <details key={dev} className="uns-dev" open={dev === "(node)"}>
              <summary><b>{dev === "(node)" ? `${r.namespace.edge} (edge node)` : dev}</b><em>{ms.length} metrics</em></summary>
              <table className="uns-table">
                <thead><tr><th>alias</th><th>metric</th><th>type</th></tr></thead>
                <tbody>{ms.map((m) => (
                  <tr key={m.name} title={String(m.properties?.description ?? "")}><td>{m.alias ?? "—"}</td><td>{m.name}</td><td>{m.datatype}</td></tr>
                ))}</tbody>
              </table>
            </details>
          ))}
          <p className="np-foot">Births carry every metric with name, alias and datatype; data carries only what changed, by alias.
            'Node Control/Rebirth' has no alias, as the specification requires.</p>
        </div>
      )}

      {tab === "On the wire" && (
        <>
          <div className="plc-speed aas-tabs">
            {Object.keys(r.samples).map((k) => <button key={k} className={k === msg ? "on" : ""} onClick={() => setMsg(k)}>{k}</button>)}
          </div>
          {r.samples[msg] && (
            <div className="uns-msg">
              <div className="aas-ids"><span>topic</span><code>{r.samples[msg].topic}</code>
                <span>MQTT</span><code>QoS {r.samples[msg].qos} · retain {String(r.samples[msg].retain)}{r.samples[msg].bytes ? ` · ${r.samples[msg].bytes} bytes protobuf` : ""}</code>
                {r.samples[msg].seq !== undefined && <><span>seq</span><code>{r.samples[msg].seq ?? "none"}</code></>}</div>
              <pre>{JSON.stringify(r.samples[msg].json ?? r.samples[msg].metrics, null, 1)}</pre>
              {r.samples[msg].metric_count && r.samples[msg].metric_count! > 8 && <p className="np-foot">first 8 of {r.samples[msg].metric_count} metrics</p>}
            </div>
          )}
          <p className="np-foot">{Object.entries(r.traffic).filter(([k]) => /^[A-Z]/.test(k)).map(([k, v]) => `${k} ${v}`).join(" · ")} ·
            the 0-255 sequence wrapped {r.traffic.seq_wraps} times.</p>
        </>
      )}

      {tab === "Specification" && (
        <div className="uns-tck">
          {r.tck.map((k) => (
            <div key={k.id} className={k.ok ? "ok" : "bad"} title={k.first_violation ?? ""}>
              <i>{k.ok ? "✓" : "✗"}</i><div><code>{k.id}</code><span>{k.text}</span></div><em>×{k.checked}</em>
            </div>
          ))}
          <p className="np-foot">Each line is a testable requirement of Eclipse Sparkplug 3.0 (ids starting stf- are this project's),
            judged by an independent monitor on every message of the proof run.</p>
        </div>
      )}

      {tab === "Death & rebirth" && (
        <div className="uns-time">
          {r.timeline.map(([t, what], i) => <div key={i}><b>{t.toFixed(1)} s</b><span>{what}</span></div>)}
          <p className="np-foot">The edge started first and waited for the primary host. When the host went offline the edge ended its
            session; when the edge was killed the broker published its will and the host marked all {metrics} metrics stale. Each new
            session raised bdSeq by one.</p>
        </div>
      )}

      {tab === "Security" && (
        <div className="ua-sec">
          {["anonymous", "wrong password", "plain text (no TLS)", "server not signed by the cell's CA"].map((k) => (
            <div key={k}><span>{k}</span><code className={r.security[k] === "Success" ? "bad" : ""}>{String(r.security[k])}</code></div>
          ))}
          {Object.entries(probes).map(([k, v]) => (
            <div key={k}><span>{k}</span><code className={v === "DELIVERED" ? "bad" : ""}>{v}</code></div>
          ))}
          <div><span>the viewer reads Sparkplug</span><code>{String(r.security["viewer reads Sparkplug"])}</code></div>
        </div>
      )}
      {(tab === "Security" || tab === "Specification") && (
        <div className="uns-mut">
          {r.mutants.map((m) => <div key={m.id}><b>{m.id}</b><span>{m.what}</span><em className={m.caught ? "ok" : "bad"}>{m.caught ? "caught" : "survived"}</em></div>)}
        </div>
      )}
    </div>
  );
}
