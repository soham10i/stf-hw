// The theme, shared by the twin and the dashboard: Studio (shared/studio.css) in its light or dark
// appearance, which the stylesheets key on as data-theme. "Studio" follows the system's appearance,
// as an app should by default; light or dark can be pinned from the theme menu, remembered per
// browser. Applied before the first paint (public/theme-init.js) and on every change.
import { useEffect, useState } from "react";

export type Appearance = "light" | "dark";
export type ThemeId = "studio" | "studio-light" | "studio-dark" | "elevenlabs";
export type ThemeDef = { id: ThemeId; label: string; say: string; appearance: Appearance | "system"; swatch: [string, string, string] };

export const THEMES: ThemeDef[] = [
  { id: "studio", label: "Studio", say: "Light or dark, following the system - the default", appearance: "system", swatch: ["#e4e9f1", "#030509", "#2f5bea"] },
  { id: "studio-light", label: "Studio · light", say: "Cool-grey ground, white glass", appearance: "light", swatch: ["#e4e9f1", "#ffffff", "#2f5bea"] },
  { id: "studio-dark", label: "Studio · dark", say: "Near-black ground, smoked glass", appearance: "dark", swatch: ["#030509", "#121a2a", "#7fb0ff"] },
  { id: "elevenlabs", label: "ElevenLabs", say: "Deep obsidian dark, crisp dark cards, neon violet accent", appearance: "dark", swatch: ["#08080a", "#121217", "#a855f7"] },
];
const KEY = "stf.theme.v2";

function saved(): ThemeId {
  try {
    const t = localStorage.getItem(KEY);
    if (THEMES.some((x) => x.id === t)) return t as ThemeId;
  } catch { /* private mode */ }
  return "studio";
}
const systemDark = () => !window.matchMedia?.("(prefers-color-scheme: light)").matches;
const appearanceOf = (id: ThemeId): Appearance => {
  const a = THEMES.find((x) => x.id === id)?.appearance ?? "system";
  return a === "system" ? (systemDark() ? "dark" : "light") : a;
};

/** Put the theme on the document: its appearance (Studio or ElevenLabs palette). */
export function applyTheme(id: ThemeId = saved()) {
  const root = document.documentElement;
  root.dataset.theme = appearanceOf(id);
  root.dataset.palette = id === "elevenlabs" ? "elevenlabs" : "studio";
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
