// Sets the theme before first paint (src/shared/theme.ts owns it afterwards): light or dark
// (data-theme), pinned or following the system, which is the default. Retired theme ids map as in
// theme.ts. A file, not an inline script, so the Content-Security-Policy needs no 'unsafe-inline'.
(function () {
  var root = document.documentElement;
  var t = null;
  try { t = localStorage.getItem("stf.theme.v2"); } catch (e) { /* private mode */ }
  var retired = { "studio-light": "light", "studio-dark": "dark", "glass-noir": "dark", "glass-frost": "dark" };
  if (retired[t]) t = retired[t];
  var dark = t === "dark" || (t !== "light" &&
    !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches));
  root.dataset.theme = dark ? "dark" : "light";
  root.dataset.palette = "studio";
  var meta = document.createElement("meta");
  meta.name = "theme-color";
  meta.content = dark ? "#000000" : "#f2f2f2";
  document.head.appendChild(meta);
})();
