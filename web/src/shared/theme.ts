// Light / dark theme, shared by the twin and the dashboard. The choice is
// remembered per browser; with none saved it follows the system setting.
// index.html and dashboard.html set data-theme before first paint (no flash).
import { useEffect, useState } from "react";

export type Theme = "light" | "dark";
const KEY = "stf.theme";

export function initialTheme(): Theme {
  try {
    const t = localStorage.getItem(KEY);
    if (t === "light" || t === "dark") return t;
  } catch { /* private mode */ }
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme as Theme) || initialTheme());
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem(KEY, theme); } catch { /* private mode */ }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}
