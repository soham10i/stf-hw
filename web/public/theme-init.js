// Sets the theme before first paint (src/shared/theme.ts owns it afterwards): Studio, light or dark
// (data-theme) - pinned, or following the system. A file, not an inline script, so the
// Content-Security-Policy needs no 'unsafe-inline' for scripts.
(function () {
  var t = null;
  try { t = localStorage.getItem("stf.theme.v2"); } catch (e) { /* private mode */ }
  var sysLight = window.matchMedia && matchMedia("(prefers-color-scheme: light)").matches;
  root.dataset.theme = t === "elevenlabs" || t === "studio-dark" ? "dark" : t === "studio-light" ? "light" : sysLight ? "light" : "dark";
  root.dataset.palette = t === "elevenlabs" ? "elevenlabs" : "studio";
})();
