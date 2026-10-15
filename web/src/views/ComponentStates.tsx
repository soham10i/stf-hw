// The small state diagrams beside a component: switch contacts, valve ports, pump, cylinder,
// motor and the IR track sensor - each drawn from its datasheet.












/** Contact state of the mini switch, straight from its datasheet: contact 1 is
    the common; released it touches 2 (normally closed), pressed it touches 3
    (normally open). */
export function SwitchState({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  // blade from the common (1) to 3 when pressed, to 2 when released
  const tip = on ? { x: 92, y: 22 } : { x: 92, y: 78 };
  return (
    <section className="panel">
      <h2>
        Switch state <span className={`tag ${on ? "run" : "idle"}`}>{on ? "ON" : "OFF"}</span>
      </h2>
      <button className={`tick-toggle big ${on ? "on" : ""}`} role="switch" aria-checked={on} onClick={onToggle}>
        <span className="tick-box">{on ? "✓" : ""}</span>
        {on ? "Pressed — click to release" : "Released — click to press"}
      </button>
      <svg viewBox="0 0 150 100" className="switch-schematic" aria-label="contact schematic">
        <line x1="10" y1="50" x2="40" y2="50" className="wire" />
        <circle cx="40" cy="50" r="4" className="node" />
        <text x="30" y="68">1</text>
        <line x1="40" y1="50" x2={tip.x} y2={tip.y} className={`blade ${on ? "on" : ""}`} />
        <line x1="100" y1="22" x2="140" y2="22" className={`wire ${on ? "live" : ""}`} />
        <circle cx="100" cy="22" r="4" className="node" />
        <text x="104" y="14">3 (NO)</text>
        <line x1="100" y1="78" x2="140" y2="78" className={`wire ${on ? "" : "live"}`} />
        <circle cx="100" cy="78" r="4" className="node" />
        <text x="104" y="96">2 (NC)</text>
      </svg>
      <table className="tbl">
        <tbody>
          <tr><th>contacts 1–3 (NO)</th><td className={on ? "ok" : ""}>{on ? "closed" : "open"}</td></tr>
          <tr><th>contacts 1–2 (NC)</th><td className={on ? "" : "ok"}>{on ? "open" : "closed"}</td></tr>
          <tr><th>input, wired NO</th><td className="num">{on ? "1" : "0"}</td></tr>
          <tr><th>input, wired NC</th><td className="num">{on ? "0" : "1"}</td></tr>
        </tbody>
      </table>
      <p className="clock">Digital input, 5 kΩ (TXT / RevPi DIO). Rated 2 A / 50 V.</p>
    </section>
  );
}

/** 3/2-way valve, drawn after the booklet's Abb. 5: energised, the plunger (b)
    lifts against the spring (c) and 1 (P) feeds 2 (A); released, the spring
    closes P and 2 (A) vents through 3 (R). */
export function ValveState({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <section className="panel">
      <h2>Valve state <span className={`tag ${on ? "run" : "idle"}`}>{on ? "ENERGISED" : "OFF"}</span></h2>
      <button className={`tick-toggle big ${on ? "on" : ""}`} role="switch" aria-checked={on} onClick={onToggle}>
        <span className="tick-box">{on ? "✓" : ""}</span>
        {on ? "Coil energised — click to release" : "Coil off — click to energise"}
      </button>
      <svg viewBox="0 0 200 120" className="switch-schematic valve-svg" aria-label="valve flow">
        <rect x="70" y="20" width="60" height="80" rx="4" className="body" />
        <text x="100" y="14" textAnchor="middle">1 (P)</text>
        <line x1="100" y1="0" x2="100" y2="20" className={`pipe ${on ? "live" : "dead"}`} />
        <text x="178" y="52" textAnchor="middle">2 (A)</text>
        <line x1="130" y1="60" x2="200" y2="60" className={`pipe ${"live"}`} />
        <text x="100" y="118" textAnchor="middle">3 (R)</text>
        <line x1="100" y1="100" x2="100" y2="110" className={`pipe ${on ? "dead" : "live"}`} />
        <rect x="92" y={on ? 30 : 38} width="16" height="40" className="core" />
        <path d={on ? "M100 22 L100 58 L150 58" : "M150 62 L100 62 L100 108"} className="flow" markerEnd="url(#arr)" />
        <defs>
          <marker id="arr" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" className="arrowhead" />
          </marker>
        </defs>
      </svg>
      <table className="tbl"><tbody>
        <tr><th>1 (P) → 2 (A)</th><td className={on ? "ok" : ""}>{on ? "open — the cylinder is pressurised" : "closed by the spring"}</td></tr>
        <tr><th>2 (A) → 3 (R)</th><td className={on ? "" : "ok"}>{on ? "closed" : "open — the cylinder vents"}</td></tr>
        <tr><th>plunger (b)</th><td>{on ? "pulled up by the coil (a)" : "pushed down by the spring (c)"}</td></tr>
      </tbody></table>
      <p className="clock">Normally closed. Two wires: a P-switching PLC output and ground.</p>
    </section>
  );
}

/** The membrane pump of the booklet's Abb. 4, phase by phase. */
export function PumpState({ on }: { on: boolean }) {
  return (
    <section className="panel">
      <h2>Membrane pump <span className={`tag ${on ? "run" : "idle"}`}>{on ? "PUMPING" : "OFF"}</span></h2>
      <ol className="pump-steps">
        <li><b>Kurbeltrieb</b> (crank): the motor turns an eccentric; its pin drives the con-rod.</li>
        <li><b>Kolben</b> (piston) moves right: the <b>Membran</b> is pulled back and air enters through the
          <b> Einlassventil</b>.</li>
        <li>Piston moves left: the membrane pushes the air out through the <b>Auslassventil</b> in the
          <b> Deckel</b> (cover) to the nipple.</li>
      </ol>
      <table className="tbl"><tbody>
        <tr><th>overpressure</th><td>0.7 bar</td></tr>
        <tr><th>current</th><td>max 70 mA at 24 VDC</td></tr>
      </tbody></table>
      <p className="clock">Tick X-ray to watch the crank, piston and membrane inside the housing.</p>
    </section>
  );
}

export function CylinderState({ on }: { on: boolean }) {
  return (
    <section className="panel">
      <h2>Cylinder <span className={`tag ${on ? "run" : "idle"}`}>{on ? "EXTENDED" : "RETRACTED"}</span></h2>
      <table className="tbl"><tbody>
        <tr><th>valve</th><td>{on ? "energised: P → A, the rear chamber is pressurised" : "off: A → R, vented"}</td></tr>
        <tr><th>piston rod</th><td>{on ? "out by the full stroke" : "held in by the spring"}</td></tr>
        <tr><th>spring</th><td>{on ? "compressed" : "relaxed"}</td></tr>
      </tbody></table>
      <p className="clock">
        Vacuum without a vacuum pump (booklet p.10): two cylinders coupled back to back. Pressurise one,
        both rods extend, and the chamber closed off by the suction cup grows, so its pressure drops below
        ambient.
      </p>
    </section>
  );
}

export function MotorState({ on }: { on: boolean }) {
  return (
    <section className="panel">
      <h2>Drive train <span className={`tag ${on ? "run" : "idle"}`}>{on ? "RUNNING" : "OFF"}</span></h2>
      <table className="tbl"><tbody>
        <tr><th>motor (no load)</th><td className="num">10 700 rpm</td></tr>
        <tr><th>U-Getriebe</th><td className="num">64.8 : 1</td></tr>
        <tr><th>side output (no load)</th><td className="num">165 rpm</td></tr>
        <tr><th>torque at the motor</th><td className="num">max 5 mNm</td></tr>
      </tbody></table>
      <p className="clock">The animation is slowed: the worm really turns 65× faster than the wheel. Tick X-ray to see them mesh.</p>
    </section>
  );
}

/** Two channels: each window has an IR emitter and receiver; a black track in
    front of a window absorbs the IR and that channel reports it. */
export function TrackState({ track, xs, r }: { track: number; xs: number[]; r: number }) {
  const sees = xs.map((x) => Math.abs(track - x) < 5 + r);
  return (
    <section className="panel">
      <h2>Track sensor</h2>
      <table className="tbl"><tbody>
        {sees.map((s, i) => (
          <tr key={i}>
            <th>channel {i + 1} ({i === 0 ? "black wire" : "yellow wire"})</th>
            <td className={s ? "ok" : ""}>{s ? "track under the window" : "white ground"}</td>
          </tr>
        ))}
      </tbody></table>
      <p className="clock">
        Range 5–30 mm; the card here is 15 mm away. Which logic level means “black” is not printed in the
        booklet — check it on the machine before writing the PLC program.
      </p>
    </section>
  );
}
