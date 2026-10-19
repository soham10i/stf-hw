// The theme, shared by the twin and the dashboard: an appearance (light or dark, which the
// stylesheets key on as data-theme) and a palette over it (data-palette, shared/theme.css).
// "System" follows the system's appearance, as an app should by default; the others are chosen
// from the theme menu and remembered per browser. Applied before the first render (main.tsx).
import { useEffect, useState } from "react";

export type Appearance = "light" | "dark";
export type ThemeId = "lumen" | "lumen-day" | "lumen-night";
export type ThemeDef = { id: ThemeId; label: string; say: string; appearance: Appearance | "system"; swatch: [string, string, string] };

// Lumen is the product's one design - offered three ways: following the system (the default),
// pinned to the light blue day, or pinned to the deep night. All three render the same palette;
// only the appearance differs.
export const THEMES: ThemeDef[] = [
  { id: "lumen", label: "Lumen", say: "Soft sky by day, deep lumen night - follows the system", appearance: "system", swatch: ["#f4f8ff", "#0a1120", "#3b82f6"] },
  { id: "lumen-day", label: "Lumen · day", say: "The light blue UI, always", appearance: "light", swatch: ["#f4f8ff", "#ffffff", "#2563eb"] },
  { id: "lumen-night", label: "Lumen · night", say: "The deep lumen night, always", appearance: "dark", swatch: ["#0a1120", "#101a30", "#7db4ff"] },
];
const KEY = "stf.theme";

function saved(): ThemeId {
  try {
    const t = localStorage.getItem(KEY);
    if (THEMES.some((x) => x.id === t)) return t as ThemeId;
  } catch { /* private mode */ }
  return "lumen";
}
const systemDark = () => !window.matchMedia?.("(prefers-color-scheme: light)").matches;
const appearanceOf = (id: ThemeId): Appearance => {
  const a = THEMES.find((x) => x.id === id)?.appearance ?? "system";
  return a === "system" ? (systemDark() ? "dark" : "light") : a;
};

/** Put the theme on the document: its appearance and its palette. */
export function applyTheme(id: ThemeId = saved()) {
  const root = document.documentElement;
  root.dataset.theme = appearanceOf(id);
  // every lumen entry renders the one lumen palette; only data-theme (the appearance) differs
  root.dataset.palette = id.startsWith("lumen") ? "lumen" : id;
}

export function useTheme() {
  const [theme, setTheme] = useState<ThemeId>(saved);
  const [appearance, setAppearance] = useState<Appearance>(() => appearanceOf(theme));
  useEffect(() => {
    // the colour change itself cross-fades across the page (View Transitions, where supported)
    const apply = () => { applyTheme(theme); setAppearance(appearanceOf(theme)); };
    if (document.startViewTransition) document.startViewTransition(apply);
    else apply();
    try { localStorage.setItem(KEY, theme); } catch { /* private mode */ }
    if (THEMES.find((x) => x.id === theme)?.appearance !== "system") return;
    // System appearance: follow the system as it changes
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const on = () => { applyTheme(theme); setAppearance(appearanceOf(theme)); };
    mq?.addEventListener("change", on);
    return () => mq?.removeEventListener("change", on);
  }, [theme]);
  return { theme, appearance, setTheme };
}
