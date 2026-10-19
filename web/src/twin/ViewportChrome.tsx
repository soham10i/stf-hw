// The chrome that floats over the 3D view: what the cell is doing (with the running order's
// progress), the camera's focus menu, the loading screen and the one-time navigation tip.
import { useProgress } from "@react-three/drei";
import { useEffect, useRef, useState } from "react";
import { FOCUS, setFocus, useFocus } from "../scene/focus";
import { useStageReady } from "../scene/stageReady";
import { useCell } from "../scene/store/useCellStore";
import { RATE, FF } from "../scene/timeline";
import type { CadDoc } from "../shared/model";
import { Icon } from "../shared/icons";

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** What the cell is doing: idle, or which cookie of which order, its step and how far it is. */
export function CellStatus({ doc }: { doc: CadDoc | null }) {
  const m = useCell((s) => s.model);
  const current = m.queue.find((o) => o.started > o.done);
  const running = !m.idle && !!current;
  const colour = doc?.pipeline.flavours[m.cycle.flavour]?.colour;
  const step = (m.step || "Loading the machine…").split("   ·   ")[0].replace(/^VGR: /, "Robot arm: ");
  const pct = running ? Math.min(100, (m.cycle.t / Math.max(1, m.cycle.total)) * 100) : 0;
  return (
    <span className={`vp-status ${running ? "running" : ""}`} title={m.step} role="status">
      <i className={running ? "run" : "idle"} />
      <b title="Playback speed">{RATE * FF.value}×</b>
      {running && (
        <span className="vp-job">
          <i style={{ background: colour }} />
          {cap(m.cycle.flavour)} {current.done + 1} of {current.qty}
        </span>
      )}
      <span className="vp-phase">{running ? cap(step) : step}</span>
      {running && <span className="vp-progress" aria-hidden><i style={{ width: `${pct}%` }} /></span>}
    </span>
  );
}

/** Fast-forward: 1×/2×/4×/8× on top of the base rate, to watch a whole order without waiting
    on every motion. The multiplier lives on the module (FF), read by the frame loop each tick. */
export function SpeedControl() {
  const [x, setX] = useState(FF.value);
  const pick = (n: number) => { FF.value = n; setX(n); };
  return (
    <div className="vp-speed ui-seg" role="radiogroup" aria-label="Simulation speed" title="Fast-forward the simulation">
      {[1, 2, 4, 8].map((n) => (
        <button key={n} role="radio" aria-checked={x === n} className={x === n ? "on" : ""} onClick={() => pick(n)}
          title={n === 1 ? "Normal speed" : `Fast-forward ${n}×`}>
          {n}×
        </button>
      ))}
    </div>
  );
}

/** A pop-up button: the camera's current focus; choosing another flies the camera to it. */
export function FocusMenu() {

  const [focus] = useFocus();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("pointerdown", away);
    window.addEventListener("keydown", esc);
    box.current?.querySelector<HTMLButtonElement>("[aria-checked=true]")?.focus();
    return () => { window.removeEventListener("pointerdown", away); window.removeEventListener("keydown", esc); };
  }, [open]);
  const cur = FOCUS.find((f) => f.id === focus)!;
  return (
    <div className="vp-menu" ref={box}>
      <button className={`vp-btn ${open ? "open" : ""}`} onClick={() => setOpen(!open)} aria-haspopup="menu" aria-expanded={open}
        title="Fly the camera to a module">
        <Icon name="scope" size={15} />{cur.label}<Icon name="down" size={13} />
      </button>
      {open && (
        <div className="vp-pop" role="menu" aria-label="Camera focus"
          onKeyDown={(e) => {
            if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
            e.preventDefault();
            const items = [...(box.current?.querySelectorAll<HTMLButtonElement>("[role=menuitemradio]") ?? [])];
            const i = items.indexOf(document.activeElement as HTMLButtonElement);
            items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length]?.focus();
          }}>
          {FOCUS.map((f, i) => (
            <button key={f.id} role="menuitemradio" aria-checked={f.id === focus} className={i === 0 ? "sep" : ""}
              onClick={() => { setFocus(f.id); setOpen(false); }}>
              <span className="vp-check">{f.id === focus ? "✓" : ""}</span>{f.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** The loading screen: determinate while the machine's meshes download (loading.md). It lifts
    once the stage is ready, or after a while in any case, so a failed download never hides it. */
export function LoadingVeil({ hasDoc }: { hasDoc: boolean }) {
  const ready = useStageReady();
  const { progress, active } = useProgress();
  const [late, setLate] = useState(false);
  useEffect(() => { if (!hasDoc) return; const id = window.setTimeout(() => setLate(true), 20000); return () => window.clearTimeout(id); }, [hasDoc]);
  const done = (ready && !active) || late;
  const [gone, setGone] = useState(done);
  useEffect(() => { if (done) { const id = window.setTimeout(() => setGone(true), 450); return () => window.clearTimeout(id); } }, [done]);
  if (gone) return null;
  const pct = hasDoc ? Math.round(progress) : 0;
  return (
    <div className={`vp-veil ${done ? "out" : ""}`} aria-busy={!done} aria-live="polite">
      <div className="vp-veil-card">
        <span className="brand-mark">STF</span>
        <b>Building the machine</b>
        <span>{hasDoc ? (pct ? `Loading parts · ${pct} %` : "Placing the modules…") : "Reading the model…"}</span>
        <div className="vp-veil-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
          <i style={{ width: `${hasDoc ? Math.max(6, pct) : 3}%` }} />
        </div>
      </div>
    </div>
  );
}

const TIP_KEY = "stf.tip.camera";
/** One tip, once: how to move around the machine. It goes when dismissed or when people first
    drag the view, and does not come back (offering-help.md › Creating tips). */
export function CameraTip() {
  const ready = useStageReady();
  const [seen, setSeen] = useState(() => { try { return localStorage.getItem(TIP_KEY) === "1"; } catch { return true; } });
  const close = () => { setSeen(true); try { localStorage.setItem(TIP_KEY, "1"); } catch { /* private mode */ } };
  // flying to a module counts as having found the way around
  const [, seq] = useFocus();
  const firstSeq = useRef(seq);
  useEffect(() => { if (seq !== firstSeq.current && !seen) close(); });
  useEffect(() => {
    if (seen) return;
    const canvas = document.querySelector(".viewport canvas");
    if (!canvas) return;
    const id = window.setTimeout(() => canvas.addEventListener("pointerdown", close, { once: true }), 300);
    return () => { window.clearTimeout(id); canvas.removeEventListener("pointerdown", close); };
  });
  if (seen || !ready) return null;
  const touch = window.matchMedia?.("(pointer: coarse)").matches;
  return (
    <div className="vp-tip" role="note">
      <Icon name="move" size={18} />
      <p><b>Look around the machine</b>{touch
        ? "Drag to turn it, pinch to zoom, drag with two fingers to move. Pick a module above to fly to it."
        : "Drag to turn it, scroll to zoom, right-drag to move. Pick a module above to fly to it."}</p>
      <button className="ui-btn ghost" onClick={close}>Got it</button>
    </div>
  );
}
