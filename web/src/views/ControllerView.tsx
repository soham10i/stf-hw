// Controller tab: the fischertechnik 24V adaptor PCB between each module and its
// PLC, replicated from 536634-Factory-simulation-24V-extended-description.pdf.
//
// public/controller.json is written by stf-cad/hbw/controller.py, which also
// reconciles the document's wiring plan against the factory model. Everything
// here - board layout, pin headers, relay roles, circuits - reads that file.
//
// The simulator follows the document's electrics: inputs are P-reading (the
// sensor puts +24 V on the terminal); outputs are P-switching; a bidirectional
// motor is two outputs driving two changeover relays, each relay putting one
// motor lead on +24V Motor or GND - so both outputs on is a STOP, not a short.

import { useEffect, useMemo, useRef, useState } from "react";

import { Relay, ControllerDoc, KIND, POWER, RELAY_X, signalInfo } from "./controllerModel";
import { Scope, Circuits } from "./ControllerCircuits";

export function ControllerView({ doc }: { doc: ControllerDoc }) {
  const [mid, setMid] = useState<string>("hbw");
  const m = doc.modules[mid];
  const info = useMemo(() => signalInfo(m), [m]);
  const [on, setOn] = useState<Record<string, boolean>>({});
  const [analog, setAnalog] = useState(0);
  const [hover, setHover] = useState<string | null>(null);   // a signal, or "T<n>"
  const [enc, setEnc] = useState<Record<string, number>>({});
  const phase = useRef<Record<string, number>>({});
  useEffect(() => { setOn({}); setEnc({}); setAnalog(0); phase.current = {}; }, [mid]);

  const motors = useMemo(
    () => Object.entries(m.relays).filter(([, r]) => r).map(([pair, r]) => ({ pair, ...(r as NonNullable<Relay>) })),
    [m],
  );
  const dirOf = (a: string, b: string) => (on[a] && !on[b] ? 1 : on[b] && !on[a] ? -1 : 0);

  // Encoders: 75 pulses/rev at the motor, ~7 rev/s at 440 rpm; shown slowed 10x.
  useEffect(() => {
    const t = window.setInterval(() => {
      const next: Record<string, number> = {};
      let changed = false;
      for (const [mot, [ba]] of Object.entries(m.encoders)) {
        const mo = motors.find((x) => x.motor === mot);
        const d = mo ? dirOf(mo.a, mo.b) : 0;
        if (d) {
          phase.current[ba] = (phase.current[ba] ?? 0) + d * 0.18;
          changed = true;
        }
        next[mot] = Math.floor(phase.current[ba] ?? 0);
      }
      if (changed) setEnc(next);
    }, 50);
    return () => window.clearInterval(t);
  }, [m, motors, on]);  // eslint-disable-line react-hooks/exhaustive-deps

  // A-signals are analogue only where the module lists them so (sorting A4); the
  // warehouse's A1/A2 are the DIGITAL trail sensor and switch like any input.
  const analogSigs = useMemo(() => new Set(Object.values(m.req.analog_in).flat()), [m]);
  const switchable = (s: string) => /^[IQA]\d+$/.test(s) && !analogSigs.has(s);
  const toggle = (s: string) => {
    if (!s || !switchable(s) || (!info[s] && !Object.values(m.st3).includes(s))) return;
    setOn((o) => ({ ...o, [s]: !o[s] }));
  };
  const level = (s: string | null | undefined) => {
    if (!s) return false;
    if (s.startsWith("B")) {
      const mot = Object.entries(m.encoders).find(([, ch]) => ch.includes(s));
      if (!mot) return false;
      const ph = phase.current[m.encoders[mot[0]][0]] ?? 0;
      const k = s === m.encoders[mot[0]][0] ? 0 : 0.25;         // B lags A by 90 degrees
      return ((((ph + k) % 1) + 1) % 1) >= 0.5;               // low while idle
    }
    if (analogSigs.has(s)) return analog > 0.2;
    return !!on[s];
  };

  // ------------------------------------------------ highlight set for hover
  const hi = useMemo(() => {
    const h = new Set<string>();
    if (!hover) return h;
    const sig = hover.startsWith("T") ? m.st3[hover.slice(1)] : hover;
    h.add(hover);
    if (sig) {
      h.add(sig);
      const t = info[sig]?.terminal ?? Object.entries(m.st3).find(([, v]) => v === sig)?.[0];
      if (t) h.add(`T${t}`);
    }
    return h;
  }, [hover, info, m]);

  const hs = hover ? (hover.startsWith("T") ? m.st3[hover.slice(1)] ?? null : hover) : null;
  const hTerm = hover?.startsWith("T") ? Number(hover.slice(1)) : null;
  const hInfo = hs ? info[hs] : null;
  const recon = doc.reconciliation.modules.find((r) => r.module === mid)!;

  const st3pin = (n: number) => (n <= 30 ? m.st3[String(n)] ?? POWER[n] ?? null : n >= 33 ? "GND" : null);
  const kind = (s: string | null | undefined) =>
    s && s.startsWith("A") && !analogSigs.has(s) ? "in" : KIND(s);
  const cls = (s: string | null | undefined, key: string) =>
    `k-${kind(s)} ${level(s) ? "lvl" : ""} ${hi.has(key) || (s && hi.has(s)) ? "hl" : ""}`;

  return (
    <div className="body">
      <div className="viewport ctl-main">
        <div className="ctl-modules">
          {Object.entries(doc.modules).map(([id, x]) => (
            <button key={id} className={id === mid ? "on" : ""} onClick={() => setMid(id)}>
              {x.name.replace(" 24V", "")} <span>{x.ft}</span>
            </button>
          ))}
        </div>

        <h2 className="ctl-title">
          Adaptor PCB 24V · {m.short} {m.ft} <span className="clock">supply {m.req.supply} · doc p.{m.pages.join(", ")}</span>
        </h2>

        {/* ------------------------------------------------ the board */}
        <svg viewBox="-12 -8 570 372" className="pcb" role="img" aria-label="adaptor PCB">
          <rect x="0" y="0" width="545" height="350" rx="14" className="board" />
          {[[50, 72], [490, 72], [50, 282], [490, 282]].map(([x, y]) => (
            <circle key={`${x}${y}`} cx={x} cy={y} r="6" className="hole" />
          ))}
          {/* ST1 / ST2 ribbon headers to the model */}
          {([["ST1", m.st1, 105], ["ST2", m.st2, 295]] as const).map(([name, pins, x0]) => {
            const n = pins.length, w = 165, pitch = (w - 12) / Math.max(1, n / 2);
            return (
              <g key={name}>
                <rect x={x0} y="10" width={w} height="36" rx="3" className="hdr" />
                <text x={x0 + 4} y="8" className="lbl">{name} · {n}-pin · model</text>
                {pins.map((p, i) => {
                  const col = Math.floor(i / 2), row = i % 2;
                  const key = `${name}:${p.pin}`;
                  return (
                    <rect key={key} x={x0 + 6 + col * pitch} y={16 + row * 14} width="9" height="9" rx="1.5"
                      className={`pin ${cls(p.signal, key)}`}
                      onMouseEnter={() => setHover(p.signal && /^[IQAB]\d+$/.test(p.signal) ? p.signal : key)}
                      onMouseLeave={() => setHover(null)} onClick={() => p.signal && toggle(p.signal)}>
                      <title>{`${name} pin ${p.pin}: ${p.signal ?? "n/c"} — ${p.function}${p.terminal ? ` (terminal ${p.terminal})` : ""}`}</title>
                    </rect>
                  );
                })}
              </g>
            );
          })}
          {/* valve terminals */}
          {["V1", "V2", "V3", "V4"].map((v, i) => {
            const val = m.valves[v];
            return (
              <g key={v} className={`valve ${val ? "" : "unused"} ${val && on[val.q] ? "lvl" : ""} ${val && hi.has(val.q) ? "hl" : ""}`}
                onMouseEnter={() => val && setHover(val.q)} onMouseLeave={() => setHover(null)}
                onClick={() => val && toggle(val.q)}>
                <rect x="0" y={112 + i * 34} width="34" height="28" rx="3" />
                <circle cx="10" cy={126 + i * 34} r="5" /><circle cx="24" cy={126 + i * 34} r="5" />
                <text x="40" y={130 + i * 34} className="lbl strong">{v}</text>
                <title>{val ? `${v}: ${val.role} (${val.q}, terminal ${val.terminal})` : `${v}: not used on this module`}</title>
              </g>
            );
          })}
          {/* relays */}
          {Object.entries(m.relays).map(([pair, r], k) => {
            const [ra, rb] = pair.split("/");
            return [ra, rb].map((rn, j) => {
              const x = RELAY_X[k * 2 + j];
              const sig = r ? (j === 0 ? r.a : r.b) : null;
              const act = !!(sig && on[sig]);
              return (
                <g key={rn} className={`relay ${r ? "" : "unused"} ${act ? "lvl" : ""} ${sig && hi.has(sig) ? "hl" : ""}`}
                  onMouseEnter={() => sig && setHover(sig)} onMouseLeave={() => setHover(null)}
                  onClick={() => sig && toggle(sig)}>
                  <rect x={x} y="110" width="36" height="92" rx="3" />
                  <text x={x + 18} y="152" textAnchor="middle" className="lbl strong">{rn}</text>
                  <text x={x + 18} y="168" textAnchor="middle" className="lbl">{sig ?? "—"}</text>
                  <text x={x + 18} y="188" textAnchor="middle" className="lbl">{act ? "ON" : ""}</text>
                  <title>{r ? `${rn}: ${r.role} (${r.motor}), driven by ${sig}` : `${rn}: not used on this module`}</title>
                </g>
              );
            });
          })}
          {Object.entries(m.relays).map(([pair, r], k) => (
            <text key={pair} x={RELAY_X[k * 2] + 38} y="218" textAnchor="middle" className="lbl role">
              {r ? r.role : "—"}
            </text>
          ))}
          {/* ST3: 17x2 header to the PLC */}
          <rect x="150" y="238" width="240" height="44" rx="3" className="hdr" />
          <text x="154" y="234" className="lbl">ST3 · 17×2 · PLC</text>
          {Array.from({ length: 34 }, (_, i) => i + 1).map((n) => {
            const col = Math.floor((n - 1) / 2), row = (n - 1) % 2;
            const s = st3pin(n);
            return (
              <rect key={n} x={156 + col * 13.6} y={244 + row * 16} width="9" height="9" rx="1.5"
                className={`pin ${cls(s, `T${n}`)}`}
                onMouseEnter={() => setHover(n <= 30 ? `T${n}` : null)} onMouseLeave={() => setHover(null)}
                onClick={() => s && toggle(s)}>
                <title>{`ST3 pin ${n}: ${s ?? "n/c"}`}</title>
              </rect>
            );
          })}
          {/* terminals 1..30 */}
          {Array.from({ length: 30 }, (_, i) => i + 1).map((n) => {
            const s = n <= 4 ? POWER[n] : m.st3[String(n)] ?? null;
            const x = 5 + (n - 1) * 17.8;
            return (
              <g key={n} className={`term ${cls(n <= 4 ? (n <= 2 ? "PWR" : "GND") : s, `T${n}`)}`}
                onMouseEnter={() => setHover(`T${n}`)} onMouseLeave={() => setHover(null)}
                onClick={() => s && toggle(s)}>
                <rect x={x} y="300" width="16" height="22" rx="2" />
                <circle cx={x + 8} cy="309" r="4" />
                <text x={x + 8} y="336" textAnchor="middle" className="lbl">{n}</text>
                <text x={x + 8} y="346" textAnchor="middle" className="lbl sig">{n <= 4 ? (n <= 2 ? "+24" : "0V") : s ?? ""}</text>
              </g>
            );
          })}
        </svg>

        <div className="ctl-info">
          {hs || hTerm ? (
            <span>
              {hTerm ? <b>terminal {hTerm}</b> : null}
              {hs ? <> <b>{hs}</b> · {hInfo?.function ?? (hTerm && hTerm <= 4 ? POWER[hTerm] : "")}</> : hTerm && hTerm <= 4 ? <> · {POWER[hTerm]}</> : " · not used"}
              {hInfo?.terminal && !hTerm ? <> · terminal {hInfo.terminal}</> : null}
              {hInfo?.header ? <> · {hInfo.header}</> : null}
              {hInfo?.relay ? <> · relay {hInfo.relay}</> : null}
              {hInfo?.valve ? <> · valve terminal {hInfo.valve}</> : null}
              {hs && switchable(hs) ? <> · <i>click to switch</i></> : null}
            </span>
          ) : (
            <span className="clock">Hover a terminal, pin, relay or valve to trace it through the board; click an I or Q to switch it.</span>
          )}
        </div>

        <Circuits doc={doc} />

        <section className="panel">
          <h2>Ribbon cables to the model</h2>
          <div className="ctl-cols">
            {([["ST1", m.st1], ["ST2", m.st2]] as const).map(([name, pins]) => (
              <table key={name} className="tbl">
                <thead><tr><th>{name}</th><th>term.</th><th>signal</th><th>function</th></tr></thead>
                <tbody>
                  {pins.map((p) => (
                    <tr key={p.pin} className={p.signal && hi.has(p.signal) ? "hl-row" : ""}
                      onMouseEnter={() => p.signal && /^[IQAB]\d+$/.test(p.signal) && setHover(p.signal)}
                      onMouseLeave={() => setHover(null)}>
                      <td className="num">{p.pin}</td><td>{p.terminal ?? "—"}</td>
                      <td><span className={`sigchip k-${kind(p.signal)}`}>{p.signal ?? "n/c"}</span></td>
                      <td>{p.function}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ))}
          </div>
        </section>
      </div>

      <aside className="sidebar">
        <section className="panel">
          <h2>I/O simulator</h2>
          <p className="clock">Inputs are P-reading (a closed sensor puts +24 V on the terminal); outputs are P-switching.</p>
          <h3>Inputs</h3>
          <div className="io-grid">
            {Object.entries({ ...m.req.digital_in }).flatMap(([kind, sigs]) =>
              sigs.map((s) => (
                <button key={s} className={`io ${on[s] ? "on" : ""}`} onClick={() => toggle(s)}
                  onMouseEnter={() => setHover(s)} onMouseLeave={() => setHover(null)} title={kind}>
                  <b>{s}</b> <span>{info[s]?.function ?? kind}</span> <em>{on[s] ? "24 V" : "0 V"}</em>
                </button>
              )),
            )}
          </div>
          {Object.keys(m.req.analog_in).length > 0 && (
            <>
              <h3>Analogue</h3>
              <label className="ana">
                A4 colour sensor <input type="range" min={0} max={10} step={0.05} value={analog}
                  onChange={(e) => setAnalog(Number(e.target.value))} />
                <b>{analog.toFixed(2)} V</b>
              </label>
              <p className="clock warn">Range disputed: this document says 0–10 V, the sensor datasheet 0–2 V.</p>
            </>
          )}
          <h3>Outputs</h3>
          {motors.map((mo) => {
            const d = dirOf(mo.a, mo.b);
            const both = on[mo.a] && on[mo.b];
            return (
              <div key={mo.pair} className="motor-row">
                <div className="motor-head"><b>{mo.motor}</b> {mo.role} <span className="clock">{mo.pair}</span></div>
                <div className="motor-btns">
                  {[mo.a, mo.b].map((q) => (
                    <button key={q} className={`io ${on[q] ? "on" : ""}`} onClick={() => toggle(q)}
                      onMouseEnter={() => setHover(q)} onMouseLeave={() => setHover(null)}>
                      <b>{q}</b> <span>{info[q]?.function ?? ""}</span>
                    </button>
                  ))}
                </div>
                <div className={`motor-state ${both ? "warn" : ""}`}>
                  {both ? "both relays energised → both leads at +24 V → motor STOPPED (no short)"
                    : d ? `running: ${info[d > 0 ? mo.a : mo.b]?.function ?? ""}` : "stopped: both leads on GND"}
                  {m.encoders[mo.motor] && (
                    <span className="enc"> · encoder {m.encoders[mo.motor].join("/")} count {enc[mo.motor] ?? 0}
                      <Scope a={level(m.encoders[mo.motor][0])} b={level(m.encoders[mo.motor][1])} /></span>
                  )}
                </div>
              </div>
            );
          })}
          <div className="io-grid">
            {Object.entries(m.req.outputs).filter(([k]) => k !== "bidirectional motors").flatMap(([kind, sigs]) =>
              sigs.map((s) => (
                <button key={s} className={`io ${on[s] ? "on" : ""}`} onClick={() => toggle(s)}
                  onMouseEnter={() => setHover(s)} onMouseLeave={() => setHover(null)} title={kind}>
                  <b>{s}</b> <span>{info[s]?.function ?? kind}</span> <em>{on[s] ? "24 V" : "off"}</em>
                </button>
              )),
            )}
          </div>
          <button className="op home" onClick={() => setOn({})}>All outputs and inputs off</button>
        </section>

        <section className="panel">
          <h2>Wiring plan vs model <span className={`tag ${recon.ok ? "run" : "warn"}`}>{recon.ok ? "MATCH" : "GAP"}</span></h2>
          <p className="clock">
            {recon.plan_signals.length} signals in the official plan · missing in the 3D model:{" "}
            {recon.missing_in_model.length ? recon.missing_in_model.join(", ") : "none"}
          </p>
          {Object.keys(recon.extra_in_model).length > 0 && (
            <p className="clock warn">
              In the model but not in the plan: {Object.entries(recon.extra_in_model).map(([s, p]) => `${s} (${p.join(", ")})`).join("; ")}
            </p>
          )}
          <table className="tbl">
            <thead><tr><th>factory total</th><th className="num">doc p.2</th><th className="num">modules</th></tr></thead>
            <tbody>
              {doc.reconciliation.totals.map((t) => (
                <tr key={t.what}><td>{t.what}</td><td className="num">{t.doc_p2}</td>
                  <td className={`num ${t.ok ? "" : "warn"}`}>{t.sum_of_modules}</td></tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="panel">
          <h2>PLC requirements</h2>
          <table className="tbl"><tbody>
            <tr><th>inputs</th><td>{doc.plc.inputs}</td></tr>
            <tr><th>outputs</th><td>{doc.plc.outputs}</td></tr>
            <tr><th>other controllers</th><td>{doc.plc.other_controllers.join("; ")}</td></tr>
          </tbody></table>
          <ul className="safety">{doc.plc.rules.map((r) => <li key={r}>{r}</li>)}</ul>
        </section>

        <section className="panel">
          <h2>Document discrepancies <span className="tag warn">{doc.discrepancies.length}</span></h2>
          {doc.discrepancies.map((d) => (
            <div key={d.what} className="disc">
              <b>{d.what}</b>
              <div>• {d.a}</div><div>• {d.b}</div>
              <div className="clock">→ {d.impact}</div>
            </div>
          ))}
        </section>
      </aside>
    </div>
  );
}
