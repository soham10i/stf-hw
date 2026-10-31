// Sets the theme before first paint (src/shared/theme.ts owns it afterwards): Studio, light or dark
// (data-theme) - pinned, or following the system; a glass tone (Obsidian included) adds data-tone. A file, not an inline script, so the
// Content-Security-Policy needs no 'unsafe-inline' for scripts.
(function () {
  var root = document.documentElement;
  var t = null;
  try { t = localStorage.getItem("stf.theme.v2"); } catch (e) { /* private mode */ }
  if (!t || t === "elevenlabs" || t === "glass-dusk") t = "obsidian";
  var tone = { "obsidian": "obsidian", "glass-noir": "noir", "glass-frost": "frost" }[t];
  root.dataset.theme = t === "studio-light" ? "light" : "dark";
  root.dataset.palette = "studio";
  if (tone) root.dataset.tone = tone;
})();
