// The dashboard's shared widgets: headline figures, cards (with their guide hint), the page guide
// and the simple horizontal bars.
import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { motion, useMotionValue, useReducedMotion, useSpring } from "motion/react";

import { GUIDE, TERMS, cardHelp } from "./guide";

// cards rise into view once as the page settles (motion): transform + opacity only, and the
// MotionConfig at the dashboard's root reduces it to a fade under prefers-reduced-motion
const RISE = { initial: { opacity: 0, y: 12 }, whileInView: { opacity: 1, y: 0 },
  viewport: { once: true, margin: "-24px" }, transition: { duration: 0.3, ease: "easeOut" } } as const;

// the card light that follows the pointer (motion-primitives "Spotlight"): a soft accent glow
// on a spring, parked far off-card until the pointer arrives. Purely decorative.
const GLOW_SPRING = { stiffness: 220, damping: 26, mass: 0.6 };
function useGlow() {
  const calm = useReducedMotion();
  const x = useSpring(useMotionValue(-999), GLOW_SPRING);
  const y = useSpring(useMotionValue(-999), GLOW_SPRING);
  const move = (e: React.PointerEvent<HTMLElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    x.set(e.clientX - r.left);
    y.set(e.clientY - r.top);
  };
  const leave = () => { x.set(-999); y.set(-999); };
  const glow = calm ? null : <motion.i className="db-glow" style={{ x, y }} aria-hidden="true" />;
  return { move, leave, glow };
}

export function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  const { move, leave, glow } = useGlow();
  return <motion.div className={`db-kpi ${tone ?? ""}`} {...RISE} onPointerMove={move} onPointerLeave={leave}>{glow}<span>{label}</span><b>{value}</b>{sub && <em>{sub}</em>}</motion.div>;
}
export const PageCtx = createContext("overview");
export function Card({ title, children, wide, extra }: { title: string; children: React.ReactNode; wide?: boolean; extra?: React.ReactNode }) {
  const help = cardHelp(useContext(PageCtx), title);
  const { move, leave, glow } = useGlow();
  return (
    <motion.section className={`db-card ${wide ? "wide" : ""}`} {...RISE} onPointerMove={move} onPointerLeave={leave}>
      {glow}
      <h3>{title}{help && <i className="db-help" title={help} aria-label={help}>i</i>}{extra}</h3>
      {children}
    </motion.section>
  );
}

/** The page's guide, as a popover from its button: how to read the page, what is on it, the
    terms it uses and where its data comes from. The page's purpose is its lede, always shown;
    this is the rest, on request (popovers.md; offering-help.md). Portaled to document.body
    so that liquid glass backdrop-filter blurs across the whole page canvas without being
    isolated by sticky header stacking contexts. */
export function GuideBox({ page, onClose }: { page: string; onClose: () => void }) {
  const box = useRef<HTMLElement>(null);
  const [style, setStyle] = useState<React.CSSProperties>({});

  useLayoutEffect(() => {
    const updatePos = () => {
      const anchor = document.querySelector<HTMLElement>(".db-guide-anchor") || document.querySelector<HTMLElement>(".db-guide-btn");
      if (window.innerWidth <= 760) {
        setStyle({});
        return;
      }
      if (anchor) {
        const r = anchor.getBoundingClientRect();
        setStyle({
          position: "fixed",
          top: Math.round(r.bottom + 10),
          right: Math.max(16, Math.round(window.innerWidth - r.right)),
          left: "auto",
        });
      }
    };
    updatePos();
    window.addEventListener("resize", updatePos);
    window.addEventListener("scroll", updatePos, true);
    return () => {
      window.removeEventListener("resize", updatePos);
      window.removeEventListener("scroll", updatePos, true);
    };
  }, []);

  useEffect(() => {
    const away = (e: PointerEvent) => {
      const t = e.target as HTMLElement;
      if (!box.current?.contains(t) && !t.closest(".db-guide-btn")) onClose();
    };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("pointerdown", away);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("pointerdown", away); window.removeEventListener("keydown", esc); };
  }, [onClose]);

  const g = GUIDE[page];
  if (!g) return null;
  const terms = g.terms.filter((k) => TERMS[k]).map((k) => [k, TERMS[k]] as const);

  return createPortal(
    <aside className="db-guide" aria-label="Guide to this page" ref={box} style={style}>
      {/* the shell owns the glass and its rounded corners; the scroller sits inside them, so the
          corners stay smooth no matter how the content scrolls (overflow on the shell itself
          would cut the curve) */}
      <div className="db-guide-scroll" data-lenis-prevent>
        <div className="db-guide-cols">
          <div><h4>How to read it</h4><ol>{g.read.map((r) => <li key={r}>{r}</li>)}</ol></div>
          <div><h4>On this page</h4><dl>{g.sections.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl></div>
        </div>
        {terms.length > 0 && (
          <div className="db-guide-terms"><h4>Terms</h4>
            <dl>{terms.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl></div>
        )}
        <p className="db-guide-src">Data: {g.source}</p>
      </div>
    </aside>,
    document.body
  );
}
export function HBars({ rows, max, unit, hl }: { rows: [string, number, string?][]; max: number; unit: string; hl?: string }) {
  return (
    <div className="db-bars">
      {rows.map(([k, v, col]) => (
        <div key={k} className={k === hl ? "hl" : ""}><span>{k}</span>
          <i style={{ width: `${Math.max(0.5, (v / (max || 1)) * 100)}%`, background: col }} /><b>{Math.round(v * 10) / 10} {unit}</b></div>
      ))}
    </div>
  );
}
