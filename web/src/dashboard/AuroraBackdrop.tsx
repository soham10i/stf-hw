// A quiet aurora behind the dashboard: three soft blobs tinted by the theme's accent, drifting
// slowly (haikei.app-style backdrop). Purely decorative - pointer-events none, aria-hidden - and
// cheap: only transforms and opacity animate, nothing under it repaints. Reduced motion (system
// setting or MotionConfig) renders it still; reduced transparency drops it entirely.
import { motion, useReducedMotion } from "motion/react";

const BLOBS = [
  // x/y in vw/vh, size in px, the accent hue each blob leans on, its drift path and period
  { c: "var(--accent)", x: "-8%", y: "-12%", s: 560, o: 0.24, dx: 60, dy: 34, d: 26 },
  { c: "var(--accent-fill)", x: "58%", y: "22%", s: 640, o: 0.19, dx: -70, dy: 44, d: 32 },
  { c: "var(--accent-strong)", x: "22%", y: "62%", s: 520, o: 0.15, dx: 50, dy: -40, d: 38 },
] as const;

export function AuroraBackdrop() {
  const calm = useReducedMotion();
  return (
    <div className="db-aurora" aria-hidden="true">
      {BLOBS.map((b, i) => (
        <motion.i
          key={i}
          style={{
            left: b.x, top: b.y, width: b.s, height: b.s, opacity: b.o,
            background: `radial-gradient(circle at 40% 40%, color-mix(in srgb, ${b.c} 60%, transparent), transparent 68%)`,
          }}
          animate={calm ? undefined : { x: [0, b.dx, 0], y: [0, b.dy, 0] }}
          transition={calm ? undefined : { duration: b.d, repeat: Infinity, ease: "easeInOut" }}
        />
      ))}
    </div>
  );
}
