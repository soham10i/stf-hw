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
    "/twin": API,
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
};
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
        plugins: __spreadArray([react(), themeInit()], (standalone ? [cspMeta()] : []), true),
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
            // Allow any ngrok or remote tunnel host
            allowedHosts: true,
        },
    };
});
