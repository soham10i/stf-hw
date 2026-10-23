// Where the API lives, from the browser's point of view. Default is same-origin (the API serves
// the built site, or the vite dev server proxies /api paths) - zero configuration. When the frontend
// is hosted elsewhere (the portfolio site, a CDN), build with VITE_STF_API=https://api.example.com
// and every fetch/WebSocket below switches to that origin. Build-time, not runtime: vite replaces
// import.meta.env.VITE_* at build, so a rebuild is needed after changing it.
//
// Known limitation (documented in docs/DISTRIBUTED.md): a cross-origin API cannot carry the
// signed guest cookie (SameSite=Lax), so guest-bound features (orders, photos, tracking) need the
// site and API under one origin - put a reverse proxy in front, or accept the copilot's X-STF-User
// header as the only identity.

const env = import.meta.env as unknown as Record<string, string | undefined>;

/** The configured API origin, or "" for same-origin. Never ends with "/". */
export const API_BASE: string = (env.VITE_STF_API ?? "").replace(/\/+$/, "");

/** A same-origin path turned into an absolute URL only when the API is hosted separately. */
export function api(path: string): string {
  return API_BASE + path;
}

/** A WebSocket URL for an API path: wss:// on https pages, ws:// otherwise. A base with a
 *  scheme is an absolute origin; a bare path prefix (a same-origin reverse proxy) keeps this
 *  page's host and prefixes the path instead. */
export function apiWs(path: string): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  if (/^https?:\/\//.test(API_BASE)) {
    return `${proto}://${API_BASE.replace(/^https?:\/\//, "")}${path}`;
  }
  return `${proto}://${location.host}${API_BASE}${path}`;
}
