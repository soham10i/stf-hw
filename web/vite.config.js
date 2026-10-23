var __assign = (this && this.__assign) || function () {
    __assign = Object.assign || function(t) {
        for (var s, i = 1, n = arguments.length; i < n; i++) {
            s = arguments[i];
            for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p))
                t[p] = s[p];
        }
        return t;
    };
    return __assign.apply(this, arguments);
};
var __spreadArray = (this && this.__spreadArray) || function (to, from, pack) {
    if (pack || arguments.length === 2) for (var i = 0, l = from.length, ar; i < l; i++) {
        if (ar || !(i in from)) {
            if (!ar) ar = Array.prototype.slice.call(from, 0, i);
            ar[i] = from[i];
        }
    }
    return to.concat(ar || Array.prototype.slice.call(from));
};
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
var __dirname = fileURLToPath(new URL(".", import.meta.url));
// The API runs on :8000; proxy REST and the WebSocket so the browser talks to
// a single origin and there are no CORS surprises.
// changeOrigin MUST stay false: the API decides who may command the machine from the Host
// the browser asked for (localhost vs a tunnel). Vite's string shorthand rewrites Host to
// the target - which made every tunnelled request look local. xfwd passes the client address.
var API = { target: "http://127.0.0.1:8000", changeOrigin: false, xfwd: true };
var API_PROXY = {
    "/layout": API,
    "/command": API,
    "/orders": API,
    "/health": API,
    "/chat": API,
    "/twin": __assign(__assign({}, API), { ws: true }), // REST and the live link (WS /twin/live)
    "/copilot": API,
    "/guest": API,
    "/notify": API,
    "/vision/captures": API,
    "/ws": { target: "ws://127.0.0.1:8000", ws: true, changeOrigin: false, xfwd: true },
};
// The Content-Security-Policy of the built app. 'unsafe-inline' is for STYLE attributes only
// (React's style={}), never for scripts; three.js textures and decoded GLB images need
// blob:/data: images. The standalone build talks to no server, so it allows no WebSocket.
var csp = function (live) { return [
    "default-src 'self'",
    "script-src 'self' 'wasm-unsafe-eval'",
    "style-src 'self' 'unsafe-inline'",
    "font-src 'self' data:",
    "img-src 'self' data: blob:",
    "media-src 'self' blob: data:",
    "connect-src 'self' blob: data:".concat(live ? " ws: wss:" : ""),
    "worker-src 'self' blob:",
    "base-uri 'self'",
    "form-action 'none'",
    "object-src 'none'",
]; };
// Served as headers by `vite preview` (make share).
var SECURITY_HEADERS = {
    "Content-Security-Policy": __spreadArray(__spreadArray([], csp(true), true), ["frame-ancestors 'none'"], false).join("; "),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(self), geolocation=(), usb=(), serial=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    // with COOP, makes the page cross-origin isolated: SharedArrayBuffer for the simulation bridge
    // (src/core/SimulationBridge.ts). Safe here: the CSP already loads nothing from another origin.
    "Cross-Origin-Embedder-Policy": "require-corp",
};
// The dev server sends only the isolation pair (its own scripts and HMR are same-origin), from a
// middleware: Vite's server.headers does not reach the pages it serves.
var ISOLATION_HEADERS = {
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
};
var isolation = function () { return ({
    name: "stf-cross-origin-isolation",
    apply: "serve",
    configureServer: function (server) {
        server.middlewares.use(function (_req, res, next) {
            for (var _i = 0, _a = Object.entries(ISOLATION_HEADERS); _i < _a.length; _i++) {
                var _b = _a[_i], k = _b[0], v = _b[1];
                res.setHeader(k, v);
            }
            next();
        });
    },
}); };
// A static host (GitHub Pages) cannot send headers, so the standalone build carries its
// policy as a <meta> tag instead (frame-ancestors is not allowed there; Pages adds nosniff).
// Build only: the dev server injects an inline script (React refresh) the policy would block.
var cspMeta = function () { return ({
    name: "stf-csp-meta",
    apply: "build",
    transformIndexHtml: function () { return [
        { tag: "meta", attrs: { "http-equiv": "Content-Security-Policy", content: csp(false).join("; ") }, injectTo: "head-prepend" },
        { tag: "meta", attrs: { name: "referrer", content: "no-referrer" }, injectTo: "head-prepend" },
    ]; },
}); };
// The theme pre-paint script (public/theme-init.js): a file, not inline, so the CSP needs no
// 'unsafe-inline' for scripts. Injected here because only the config knows the base path.
var themeInit = function () {
    var base = "/";
    return {
        name: "stf-theme-init",
        configResolved: function (c) { base = c.base; },
        transformIndexHtml: function () { return [{ tag: "script", attrs: { src: "".concat(base, "theme-init.js") }, injectTo: "head" }]; },
    };
};
export default defineConfig(function (_a) {
    var mode = _a.mode;
    var env = loadEnv(mode, process.cwd(), "");
    var standalone = env.VITE_LIVE_API === "0";
    return {
        // where the app is served: /stf/ locally, /<repo>/ on GitHub Pages (STF_BASE)
        base: env.STF_BASE || "/stf/",
        plugins: __spreadArray([react(), themeInit(), isolation()], (standalone ? [cspMeta()] : []), true),
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
            allowedHosts: true,
            headers: SECURITY_HEADERS,
            proxy: API_PROXY,
        },
        server: {
            port: 5173,
            host: "localhost",
            proxy: API_PROXY,
            // Vite's Host check stays on (a website the developer visits cannot reach this server through
            // DNS rebinding). Tunnelling the dev server is an explicit opt-in (STF_TUNNEL_DEV=1, the
            // web-tunnel launch config) and then admits ngrok's hostnames only, never any Host.
            allowedHosts: process.env.STF_TUNNEL_DEV === "1" ? [".ngrok-free.dev", ".ngrok.app", ".ngrok.io"] : [],
        },
    };
});
