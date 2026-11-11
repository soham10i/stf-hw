// The theme, shared by the twin and the dashboard: the "Zero" design system (shared/zero.css,
// docs/12-design-blueprint.md) in its light or dark appearance, which the stylesheets key on as
// data-theme on <html>. Three choices, as the blueprint asks: System (follows the operating system,
// the default), Light and Dark, remembered per browser. Applied before the first paint
// (public/theme-init.js) and on every change.
import { useEffect, useState } from "react";

export type Appearance = "light" | "dark";
export type ThemeId = "system" | "light" | "dark";
export type ThemeDef = { id: ThemeId; label: string; say: string; appearance: Appearance | "system"; swatch: [string, string, string] };

export const THEMES: ThemeDef[] = [
  { id: "system", label: "System", say: "Follows the system setting: light or dark", appearance: "system", swatch: ["#f2f2f2", "#000000", "#0fff4f"] },
  { id: "light", label: "Light", say: "Off-white surfaces, black ink, lime highlights", appearance: "light", swatch: ["#f2f2f2", "#ffffff", "#0fff4f"] },
  { id: "dark", label: "Dark", say: "Black surfaces, off-white ink, lime primary", appearance: "dark", swatch: ["#000000", "#1f1f1f", "#0fff4f"] },
];
const KEY = "stf.theme.v2";
/** the browser chrome's colour per appearance (the blueprint's --bg) */
const CHROME: Record<Appearance, string> = { light: "#f2f2f2", dark: "#000000" };

// --- retired themes
// Every visitor had the old default (Obsidian) stored, so it maps to System rather than pinning
// everyone to dark; the other themes were picked on purpose and keep their appearance. The same
// table is in public/theme-init.js, which runs before this module loads.
const RETIRED: Record<string, ThemeId> = {
  studio: "system", obsidian: "system", elevenlabs: "system", "glass-dusk": "system",
  "studio-light": "light", "studio-dark": "dark", "glass-noir": "dark", "glass-frost": "dark",
};

function saved(): ThemeId {
  try {
    const t = localStorage.getItem(KEY);
    if (THEMES.some((x) => x.id === t)) return t as ThemeId;
    if (t && RETIRED[t]) return RETIRED[t];
  } catch { /* private mode */ }
  return "system";
}
const systemDark = () => !!window.matchMedia?.("(prefers-color-scheme: dark)").matches;
const appearanceOf = (id: ThemeId): Appearance => (id === "system" ? (systemDark() ? "dark" : "light") : id);

/** Put the theme on the document: its appearance, and the browser chrome's colour to match. */
export function applyTheme(id: ThemeId = saved()) {
  const root = document.documentElement;
  const appearance = appearanceOf(id);
  // The swap itself is instant: with every element's colour transition running at once, the page
  // passes through a half-old, half-new state (and stays there in a window that paints no frames).
  // Transitions are suspended (zero.css, .theme-switch), the new values committed with one style
  // flush, and transitions restored.
  const swap = root.dataset.theme !== undefined && root.dataset.theme !== appearance;
  if (swap) root.classList.add("theme-switch");
  root.dataset.theme = appearance;
  if (swap) {
    void getComputedStyle(root).color;
    root.classList.remove("theme-switch");
  }
  // the stylesheets scope the design system under one palette name
  root.dataset.palette = "studio";
  let meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (!meta) {
    meta = document.createElement("meta");
    meta.name = "theme-color";
    document.head.appendChild(meta);
  }
  meta.content = CHROME[appearance];
}

export function useTheme() {
  const [theme, setTheme] = useState<ThemeId>(saved);
  const [appearance, setAppearance] = useState<Appearance>(() => appearanceOf(theme));
  useEffect(() => {
    // the colour change itself cross-fades across the page (View Transitions, where supported)
    const apply = () => { applyTheme(theme); setAppearance(appearanceOf(theme)); };
    // The cross-fade only where it can run and is wanted. The browser runs the transition's callback
    // on its next frame, and a covered or background window may not paint one for a long time (the
    // theme was saved but not shown), so after 250 ms the change is applied without the fade. Under
    // reduced motion the blueprint asks for no fade at all. A skipped transition's promise rejects,
    // which is expected and not an error.
    let done = false;
    const once = () => { if (!done) { done = true; apply(); } };
    // (older browsers have no View Transitions: the typed DOM says it always exists, so ask at runtime)
    const fade = typeof document.startViewTransition === "function"
      && !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (fade) {
      const vt = document.startViewTransition(once);
      vt.ready.catch(() => {});
      window.setTimeout(() => { if (!done) { vt.skipTransition(); once(); } }, 250);
    } else once();
    try { localStorage.setItem(KEY, theme); } catch { /* private mode */ }
    if (theme !== "system") return;
    // System: follow the operating system as it changes
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const on = () => { applyTheme(theme); setAppearance(appearanceOf(theme)); };
    mq?.addEventListener("change", on);
    return () => mq?.removeEventListener("change", on);
  }, [theme]);
  return { theme, appearance, setTheme };
}
