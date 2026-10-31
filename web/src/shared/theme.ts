// The theme, shared by the twin and the dashboard: Studio (shared/studio.css) in its light or dark
// appearance, which the stylesheets key on as data-theme; and the glass tones (shared/glass.css:
// Studio's layout with data-tone obsidian, noir or frost). "Studio" follows the system's appearance,
// as an app should by default; light or dark can be pinned from the theme menu, remembered per
// browser. Applied before the first paint (public/theme-init.js) and on every change.
import { useEffect, useState } from "react";

export type Appearance = "light" | "dark";
export type ThemeId = "studio" | "studio-light" | "studio-dark" | "obsidian" | "glass-noir" | "glass-frost";
/** the Glass tones (shared/glass.css): Studio's layout under a tone of frosted glass */
export type Tone = "obsidian" | "noir" | "frost";
export type ThemeDef = { id: ThemeId; label: string; say: string; appearance: Appearance | "system"; swatch: [string, string, string] };

export const THEMES: ThemeDef[] = [
  { id: "studio", label: "Auto (System)", say: "Follows system: Light (Image 1) or Dark (Image 2)", appearance: "system", swatch: ["#b7c8d8", "#030303", "#090e21"] },
  { id: "studio-light", label: "Apple Tinted · Light", say: "Cool ice-blue gradient with Apple tinted glassmorphism (Image 1 & 3)", appearance: "light", swatch: ["#b7c8d8", "#f6f8ff", "#090e21"] },
  { id: "obsidian", label: "Obsidian Glass · Dark", say: "Sleek graphite gradient with Apple liquid glassmorphism (Image 2 & 3)", appearance: "dark", swatch: ["#030303", "#4a4a4a", "#ffffff"] },
  { id: "glass-noir", label: "Glass · Noir", say: "Extreme dark: smoked glass on near-black, cool steel-blue light", appearance: "dark", swatch: ["#020204", "#14161d", "#4f8bff"] },
  { id: "glass-frost", label: "Glass · Steel", say: "Steel glass over slate gradient, light typography", appearance: "dark", swatch: ["#262b33", "#5a6873", "#cfe4f7"] },
];
const TONES: Partial<Record<ThemeId, Tone>> = { obsidian: "obsidian", "glass-noir": "noir", "glass-frost": "frost" };
const KEY = "stf.theme.v2";

function saved(): ThemeId {
  try {
    const t = localStorage.getItem(KEY);
    if (t === "elevenlabs" || t === "glass-dusk") return "obsidian"; // retired theme ids
    if (THEMES.some((x) => x.id === t)) return t as ThemeId;
  } catch { /* private mode */ }
  return "obsidian";
}
const systemDark = () => !window.matchMedia?.("(prefers-color-scheme: light)").matches;
const appearanceOf = (id: ThemeId): Appearance => {
  const a = THEMES.find((x) => x.id === id)?.appearance ?? "system";
  return a === "system" ? (systemDark() ? "dark" : "light") : a;
};

/** Put the theme on the document: its appearance, and the glass tone if it is one. */
export function applyTheme(id: ThemeId = saved()) {
  const root = document.documentElement;
  root.dataset.theme = appearanceOf(id);
  const tone = TONES[id];
  root.dataset.palette = "studio";
  if (tone) root.dataset.tone = tone;
  else delete root.dataset.tone;
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
