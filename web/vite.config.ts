import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

// The API runs on :8000; proxy REST and the WebSocket so the browser talks to
// a single origin and there are no CORS surprises.
// changeOrigin MUST stay false: the API decides who may command the machine from the Host
// the browser asked for (localhost vs a tunnel). Vite's string shorthand rewrites Host to
// the target - which made every tunnelled request look local. xfwd passes the client address.
const API = { target: "http://127.0.0.1:8000", changeOrigin: false, xfwd: true };
const API_PROXY = {
  "/layout": API,
  "/command": API,
  "/orders": API,
  "/health": API,
  "/ws": { target: "ws://127.0.0.1:8000", ws: true, changeOrigin: false, xfwd: true },
};

// The Content-Security-Policy of the built app. 'unsafe-inline' is for STYLE attributes only
// (React's style={}), never for scripts; three.js textures and decoded GLB images need
// blob:/data: images. The standalone build talks to no server, so it allows no WebSocket.
const csp = (live: boolean) => [
  "default-src 'self'",
  "script-src 'self' 'wasm-unsafe-eval'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com",
  "img-src 'self' data: blob:",
  `connect-src 'self' blob: data:${live ? " ws: wss:" : ""}`,
  "worker-src 'self' blob:",
  "base-uri 'self'",
  "form-action 'none'",
  "object-src 'none'",
];

// Served as headers by `vite preview` (make share).
const SECURITY_HEADERS = {
  "Content-Security-Policy": [...csp(true), "frame-ancestors 'none'"].join("; "),
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "X-Frame-Options": "DENY",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), usb=(), serial=()",
  "Cross-Origin-Opener-Policy": "same-origin",
};

// A static host (GitHub Pages) cannot send headers, so the standalone build carries its
// policy as a <meta> tag instead (frame-ancestors is not allowed there; Pages adds nosniff).
// Build only: the dev server injects an inline script (React refresh) the policy would block.
const cspMeta = (): Plugin => ({
  name: "stf-csp-meta",
  apply: "build",
  transformIndexHtml: () => [
    { tag: "meta", attrs: { "http-equiv": "Content-Security-Policy", content: csp(false).join("; ") }, injectTo: "head-prepend" },
    { tag: "meta", attrs: { name: "referrer", content: "no-referrer" }, injectTo: "head-prepend" },
  ],
});

// The theme pre-paint script (public/theme-init.js): a file, not inline, so the CSP needs no
// 'unsafe-inline' for scripts. Injected here because only the config knows the base path.
const themeInit = (): Plugin => {
  let base = "/";
  return {
    name: "stf-theme-init",
    configResolved: (c) => { base = c.base; },
    transformIndexHtml: () => [{ tag: "script", attrs: { src: `${base}theme-init.js` }, injectTo: "head" }],
  };
};

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const standalone = env.VITE_LIVE_API === "0";
  return {
    // where the app is served: /stf/ locally, /<repo>/ on GitHub Pages (STF_BASE)
    base: env.STF_BASE || "/stf/",
    plugins: [react(), themeInit(), ...(standalone ? [cspMeta()] : [])],
    // two pages: the 3D twin (index.html) and the operations dashboard (dashboard.html)
    build: {
      rollupOptions: {
        input: { main: resolve(__dirname, "index.html"), dashboard: resolve(__dirname, "dashboard.html") },
      },
    },
    // The production build, as served to anyone outside this machine (vite preview behind a
    // tunnel on this machine). The dev server below is for this machine only: it serves the
    // source and has HMR, so it is never tunnelled. Both listen on loopback only.
    preview: {
      port: 4173,
      host: "localhost",
      allowedHosts: [".ngrok-free.dev", ".ngrok.app", ".ngrok.io"],
      headers: SECURITY_HEADERS,
      proxy: API_PROXY,
    },
    server: {
      port: 5173,
      host: "localhost",
      proxy: API_PROXY,
      // STF_TUNNEL_DEV=1 (launch config "web-tunnel"): the dev server behind ngrok, on request.
      // It serves the source and HMR, so it is off by default; the shared build is 4173.
      ...(env.STF_TUNNEL_DEV === "1"
        ? { allowedHosts: [".ngrok-free.dev", ".ngrok.app", ".ngrok.io"], hmr: { clientPort: 443 } }
        : {}),
    },
  };
});
