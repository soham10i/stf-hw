// A small line-icon set (24 px grid, 1.8 stroke), drawn inline so the app
// needs no icon library. Colour follows currentColor.
import { useEffect, useRef, useState } from "react";
import { THEMES, type ThemeDef, type ThemeId } from "./theme";

const P: Record<string, string> = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  calendar: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
  brain: "M9 3a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3h1V3zM15 3a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3h-1V3z",
  bolt: "M13 2 4 14h7l-1 8 9-12h-7z",
  gauge: "M12 14l4-4M3.5 15a9 9 0 1 1 17 0M12 14a1 1 0 1 0 0 .01",
  shield: "M12 3 4 6v6c0 4.5 3.4 8.2 8 9 4.6-.8 8-4.5 8-9V6z",
  factory: "M3 21V10l6 4V10l6 4V6h6v15zM7 17h2M12 17h2M17 17h2",
  heart: "M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z",
  wrench: "M14.5 6.5a4 4 0 0 0 5 5L21 13l-8 8-3-3 8-8-1.5-1.5zM10 18l-6 3 3-6",
  check: "M4 12.5 9 17l11-11",
  bell: "M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 21h4",
  cog: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 13a7.5 7.5 0 0 0 0-2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-1.7-1L15 3h-4l-.3 2.9a7 7 0 0 0-1.7 1l-2.4-1-2 3.4L6.6 11a7.5 7.5 0 0 0 0 2l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 1.7 1L11 21h4l.3-2.9a7 7 0 0 0 1.7-1l2.4 1 2-3.4z",
  database: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  list: "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01",
  activity: "M3 12h4l3-8 4 16 3-8h4",
  cpu: "M7 7h10v10H7zM10 10h4v4h-4zM9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4",
  monitor: "M3 4h18v12H3zM8 20h8M12 16v4",
  plug: "M9 2v5M15 2v5M6 7h12v4a6 6 0 0 1-12 0zM12 17v5",
  up: "M12 19V5M5 12l7-7 7 7",
  cube: "M12 2 3 7v10l9 5 9-5V7zM3 7l9 5 9-5M12 12v10",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  external: "M14 4h6v6M20 4 10 14M18 14v6H4V6h6",
  panel: "M3 4h18v16H3zM9 4v16",
  pin: "M9 3h6l-1 6 3 3v2H7v-2l3-3zM12 14v7",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4",
  down: "m6 9 6 6 6-6",
  plus: "M12 5v14M5 12h14",
  chevron: "m9 6 6 6-6 6",
  info: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01",
  layers: "m12 3 9 5-9 5-9-5zM3 13l9 5 9-5",
  zap: "M13 2 4 14h7l-1 8 9-12h-7z",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  eyeoff: "M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6C3.9 8.4 2 12 2 12s3.5 7 10 7c1.6 0 3-.4 4.3-1",
  play: "M7 4v16l13-8z",
  pause: "M7 4h4v16H7zM14 4h4v16h-4z",
  menu: "M4 6h16M4 12h16M4 18h16",
  lock: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
  network: "M9 3h6v5H9zM3 16h6v5H3zM15 16h6v5h-6zM12 8v4M6 16v-4h12v4",
  // a viewfinder: what the camera frames
  scope: "M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M12 9v6M9 12h6",
  // the copilot: a spark
  spark: "M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z",
  close: "M6 6l12 12M18 6 6 18",
  move: "M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3",
  // the second set: one glyph per page and panel, in the same outline style
  overview: "M5 4h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM15 4h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM5 14h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1zM15 14h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1z",
  seal: "M12 3l2.2 1.6 2.7-.1.8 2.6 2.2 1.6-.9 2.6.9 2.6-2.2 1.6-.8 2.6-2.7-.1L12 21l-2.2-1.6-2.7.1-.8-2.6-2.2-1.6.9-2.6-.9-2.6 2.2-1.6.8-2.6 2.7.1zM8.8 12.2l2.2 2.2 4.2-4.6",
  viewfinder: "M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  pulse: "M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10zM6 12h3l1.4-2.6 2.2 5 1.4-2.4H18",
  shuffle: "M4 7h3c4.5 0 5.5 10 10 10h3M4 17h3c1.6 0 2.8-1.3 3.8-3M13.2 10c1-1.7 2.2-3 3.8-3h3M18 4.5 20.5 7 18 9.5M18 14.5l2.5 2.5-2.5 2.5",
  leaf: "M5 19c0-8.5 5.5-14 15-14 0 9.5-5.5 15-14 15zM5 19c2.5-4 6-7 9.5-8.5",
  shieldlock: "M12 3 4 6v6c0 4.5 3.4 8.2 8 9 4.6-.8 8-4.5 8-9V6zM9.5 11.5h5v4h-5zM10.5 11.5V10a1.5 1.5 0 0 1 3 0v1.5",
  checklist: "M10 6h10M10 12h10M10 18h10M3.5 6l1.3 1.3L7.5 4.7M3.5 12l1.3 1.3 2.7-2.6M3.5 18l1.3 1.3 2.7-2.6",
  book: "M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5zM5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3M9 7h6",
  cart: "M3 4h2.5l2.2 10.2a1 1 0 0 0 1 .8h8.6a1 1 0 0 0 1-.8L20 7.5H6.4M9.5 20a1 1 0 1 0 0-.01M17 20a1 1 0 1 0 0-.01",
  wave: "M3 12h3l2-6 3.5 12 3-9 2 3H21",
  chip: "M8 8h8v8H8zM10 4v4M14 4v4M10 16v4M14 16v4M4 10h4M4 14h4M16 10h4M16 14h4",
  ruler: "M4 15.5 15.5 4 20 8.5 8.5 20zM8 11.5l1.5 1.5M10.5 9l2.5 2.5M13 6.5l1.5 1.5",
  bars: "M4 20h16M6.5 17v-5M11 17V7M15.5 17v-8M20 17V4",
  palette: "M12 3a9 9 0 0 0 0 18c1.1 0 1.8-.9 1.5-1.9-.3-1.1.5-2.1 1.6-2.1H17a4 4 0 0 0 4-4c0-5.5-4-10-9-10zM7.5 12a1 1 0 1 0 0-.01M9.5 7.5a1 1 0 1 0 0-.01M14.5 7.5a1 1 0 1 0 0-.01M17 11a1 1 0 1 0 0-.01",
  // the copilot's message actions: copy (two sheets), copied, read aloud (a speaker and its
  // waves), stop (a rounded square)
  copy: "M9 9h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1zM5 15H4.5A1.5 1.5 0 0 1 3 13.5v-9A1.5 1.5 0 0 1 4.5 3h9A1.5 1.5 0 0 1 15 4.5V5",
  copied: "M9 9h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1zM5 15H4.5A1.5 1.5 0 0 1 3 13.5v-9A1.5 1.5 0 0 1 4.5 3h9A1.5 1.5 0 0 1 15 4.5V5M10.8 14.6l1.9 1.9 3.6-3.9",
  speaker: "M4 9.5h3.2L12 5.5v13l-4.8-4H4a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1zM15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11",
  stop: "M8 7h8a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1z",
  // the copilot: a speech bubble with a spark in it - the assistant that answers, in words
  copilot: "M5.5 4h13A2.5 2.5 0 0 1 21 6.5v8a2.5 2.5 0 0 1-2.5 2.5H12l-4.6 3.6V17H5.5A2.5 2.5 0 0 1 3 14.5v-8A2.5 2.5 0 0 1 5.5 4zM12 7.2l1.05 2.55 2.55 1.05-2.55 1.05L12 14.4l-1.05-2.55L8.4 10.8l2.55-1.05z",
  broadcast: "M12 12h.01M8.5 8.5a5 5 0 0 0 0 7M15.5 8.5a5 5 0 0 1 0 7M5.6 5.6a9 9 0 0 0 0 12.8M18.4 5.6a9 9 0 0 1 0 12.8",
};

/** The copilot's mark: the bubble drawn, its spark filled - the avatar beside an answer, the
    empty chat, and wherever the copilot is named. */
export function CopilotMark({ size = 18, className }: { size?: number; className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5.5 4h13A2.5 2.5 0 0 1 21 6.5v8a2.5 2.5 0 0 1-2.5 2.5H12l-4.6 3.6V17H5.5A2.5 2.5 0 0 1 3 14.5v-8A2.5 2.5 0 0 1 5.5 4z" />
      <path d="M12 6.9l1.1 2.7 2.7 1.1-2.7 1.1-1.1 2.7-1.1-2.7-2.7-1.1 2.7-1.1z" fill="currentColor" strokeWidth={1} />
    </svg>
  );
}

export function Icon({ name, size = 18, className }: { name: keyof typeof P | string; size?: number; className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={P[name] ?? P.info} />
    </svg>
  );
}

/** The theme menu: a pop-up button that names the theme; the menu shows each with its swatch. */
export function ThemeMenu({ theme, setTheme }: { theme: ThemeId; setTheme: (t: ThemeId) => void }) {
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
  const cur = THEMES.find((t) => t.id === theme) ?? THEMES[0];
  const swatch = (t: ThemeDef) => (
    <span className="theme-sw" aria-hidden="true">{t.swatch.map((c, i) => <i key={i} style={{ background: c }} />)}</span>
  );
  return (
    <div className="theme-menu" ref={box}>
      <button className="ui-btn icon" onClick={() => setOpen(!open)} aria-haspopup="menu" aria-expanded={open}
        title={`Theme: ${cur.label}`} aria-label={`Theme: ${cur.label}`}>
        <Icon name="palette" size={17} />
      </button>
      {open && (
        <div className="theme-pop" role="menu" aria-label="Theme"
          onKeyDown={(e) => {
            if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
            e.preventDefault();
            const items = [...(box.current?.querySelectorAll<HTMLButtonElement>("[role=menuitemradio]") ?? [])];
            const i = items.indexOf(document.activeElement as HTMLButtonElement);
            items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length]?.focus();
          }}>
          <em>Theme</em>
          {THEMES.map((t, i) => (
            <button key={t.id} role="menuitemradio" aria-checked={t.id === theme} className={i === 0 ? "sep" : ""}
              onClick={() => { setTheme(t.id); setOpen(false); }}>
              <span className="theme-check">{t.id === theme ? "✓" : ""}</span>
              {swatch(t)}
              <span className="theme-txt"><b>{t.label}</b><small>{t.say}</small></span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
