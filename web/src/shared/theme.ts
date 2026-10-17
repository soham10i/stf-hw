// The theme, shared by the twin and the dashboard: an appearance (light or dark, which the
// stylesheets key on as data-theme) and a palette over it (data-palette, shared/theme.css).
// "System" follows the system's appearance, as an app should by default; the others are chosen
// from the theme menu and remembered per browser. Applied before the first render (main.tsx).
import { useEffect, useState } from "react";

export type Appearance = "light" | "dark";
export type ThemeId = "system" | "light" | "dark" | "midnight" | "graphite" | "hmi" | "contrast";
export type ThemeDef = { id: ThemeId; label: string; say: string; appearance: Appearance | "system"; swatch: [string, string, string] };

export const THEMES: ThemeDef[] = [
  { id: "system", label: "System", say: "Light or dark, as the system is set", appearance: "system", swatch: ["#f5f5f7", "#1c1c1e", "#0071e3"] },
  { id: "light", label: "Light", say: "Neutral greys, blue for what you can click", appearance: "light", swatch: ["#f5f5f7", "#ffffff", "#0071e3"] },
  { id: "dark", label: "Dark", say: "The default for the 3D twin", appearance: "dark", swatch: ["#0e0e10", "#1c1c1e", "#4ba3ff"] },
  { id: "midnight", label: "Midnight", say: "Navy surfaces for a dim room", appearance: "dark", swatch: ["#0a0f1a", "#121a2b", "#6cb4ff"] },
  { id: "graphite", label: "Graphite", say: "Grey controls: colour only for the machine's states", appearance: "dark", swatch: ["#0e0e10", "#2c2c2e", "#8e8e93"] },
  { id: "hmi", label: "HMI grey", say: "An operator screen's grey (ISA-101)", appearance: "light", swatch: ["#d4d6d9", "#e6e7e9", "#1f4e8c"] },
  { id: "contrast", label: "High contrast", say: "Black and white, strong outlines", appearance: "dark", swatch: ["#000000", "#ffffff", "#66b8ff"] },
];
const KEY = "stf.theme";

function saved(): ThemeId {
  try {
    const t = localStorage.getItem(KEY);
    if (THEMES.some((x) => x.id === t)) return t as ThemeId;
  } catch { /* private mode */ }
  return "system";
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
  if (id === "system" || id === "light" || id === "dark") delete root.dataset.palette;
  else root.dataset.palette = id;
}

export function useTheme() {
  const [theme, setTheme] = useState<ThemeId>(saved);
  const [appearance, setAppearance] = useState<Appearance>(() => appearanceOf(theme));
  useEffect(() => {
    applyTheme(theme);
    setAppearance(appearanceOf(theme));
    try { localStorage.setItem(KEY, theme); } catch { /* private mode */ }
    if (theme !== "system") return;
    // System: follow the system as it changes
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const on = () => { applyTheme("system"); setAppearance(appearanceOf("system")); };
    mq?.addEventListener("change", on);
    return () => mq?.removeEventListener("change", on);
  }, [theme]);
  return { theme, appearance, setTheme };
}
