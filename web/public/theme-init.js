// Sets the theme before first paint (src/shared/theme.ts owns it afterwards): the appearance
// (data-theme: light or dark) and the palette over it (data-palette), as theme.ts's THEMES say.
// A file, not an inline script, so the Content-Security-Policy needs no 'unsafe-inline' for scripts.
(function () {
  var t = null;
  try { t = localStorage.getItem("stf.theme"); } catch (e) { /* private mode */ }
  var dark = { dark: 1, midnight: 1, graphite: 1, contrast: 1 }, light = { light: 1, hmi: 1 };
  var sysLight = window.matchMedia && matchMedia("(prefers-color-scheme: light)").matches;
  var root = document.documentElement;
  root.dataset.theme = dark[t] ? "dark" : light[t] ? "light" : sysLight ? "light" : "dark";
  if (t && t !== "light" && t !== "dark" && (dark[t] || light[t])) root.dataset.palette = t;
})();
