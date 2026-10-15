// Sets the theme before first paint (src/theme.ts owns it afterwards).
// A file, not an inline script, so the Content-Security-Policy needs no 'unsafe-inline' for scripts.
(function () {
  var t = null;
  try { t = localStorage.getItem("stf.theme"); } catch (e) { /* private mode */ }
  document.documentElement.dataset.theme = t === "light" || t === "dark" ? t
    : (window.matchMedia && matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
})();
