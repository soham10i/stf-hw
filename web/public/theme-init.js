// Sets the theme before first paint (src/shared/theme.ts owns it afterwards): Studio, light or dark
// (data-theme) - pinned, or following the system. A file, not an inline script, so the
// Content-Security-Policy needs no 'unsafe-inline' for scripts.
(function () {
  var root = document.documentElement;
  var t = null;
  try { t = localStorage.getItem("stf.theme.v2"); } catch (e) { /* private mode */ }
  if (!t) t = "elevenlabs";
  var sysLight = window.matchMedia && matchMedia("(prefers-color-scheme: light)").matches;
  root.dataset.theme = t === "studio-light" ? "light" : "dark";
  root.dataset.palette = t === "elevenlabs" ? "elevenlabs" : "studio";
})();
