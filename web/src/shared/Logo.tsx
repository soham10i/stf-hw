// The STF logo, drawn inline so it takes the theme's colours: no background of its own, the
// wordmark in the page's text colour, the cube's gradient and node in the theme's logo tokens
// (--logo-a, --logo-b: brighter on dark, deeper on light, see shared/studio.css).
import { useId } from "react";

function Cube({ id }: { id: string }) {
  return (
    <>
      <defs>
        <linearGradient id={`${id}g`} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style={{ stopColor: "var(--logo-a, #00b8d9)" }} />
          <stop offset="100%" style={{ stopColor: "var(--logo-b, #0a66f0)" }} />
        </linearGradient>
      </defs>
      <g stroke={`url(#${id}g)`} strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" fill="none">
        <polygon points="40,8.5 69,25.2 69,54.8 40,71.5 11,54.8 11,25.2" />
        <line x1="40" y1="8.5" x2="40" y2="40" />
        <line x1="40" y1="40" x2="11" y2="54.8" />
        <line x1="40" y1="40" x2="69" y2="54.8" />
      </g>
      <circle cx="40" cy="40" r="6.2" style={{ fill: "var(--logo-a, #00b8d9)" }} />
      <circle cx="69" cy="25.2" r="2.8" style={{ fill: "var(--text, currentColor)" }} />
    </>
  );
}

/** The cube alone: the favicon's mark, for narrow places. */
export function StfMark({ className, size = 32 }: { className?: string; size?: number }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg className={className} viewBox="0 0 80 80" width={size} height={size} role="img" aria-label="STF">
      <Cube id={id} />
    </svg>
  );
}

/** The cube and the wordmark: STF over FACTORY SIMULATION. */
export function StfLogo({ className, height = 34 }: { className?: string; height?: number }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg className={className} viewBox="0 0 252 80" height={height} width={(height * 252) / 80} role="img" aria-label="STF Factory Simulation">
      <Cube id={id} />
      <text x="88" y="46" style={{ fill: "var(--text, currentColor)", font: "800 40px var(--font, system-ui)", letterSpacing: "0.02em" }}>STF</text>
      <text x="89" y="65" style={{ fill: "var(--muted, currentColor)", font: "600 10.5px var(--font, system-ui)", letterSpacing: "0.22em" }}>FACTORY SIMULATION</text>
    </svg>
  );
}
