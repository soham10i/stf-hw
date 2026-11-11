// Where the API lives, from the browser's point of view. Default is same-origin (the API serves
// the built site, or the vite dev server proxies /api paths) - zero configuration. When the frontend
// is hosted elsewhere (the portfolio site, a CDN), build with VITE_STF_API=https://api.example.com
// and every fetch/WebSocket below switches to that origin. Build-time, not runtime: vite replaces
// import.meta.env.VITE_* at build, so a rebuild is needed after changing it.
//
// Known limitation (documented in docs/reference/operations/distributed.md): a cross-origin API cannot carry the
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

/** The API's error body (services/api/core/errors.py, docs/reference/architecture/error-codes.md). */
export type ErrorBody = {
  code?: string; reason?: string; status?: number; message?: string; request_id?: string;
  /** older servers send the message as `error` or `detail` */
  error?: string; detail?: string;
};

/** A failed API call: the message is safe to show; `code` (universal) and `reason` (custom)
 *  are for code that reacts to a particular failure; `requestId` finds the server's log lines. */
export class ApiError extends Error {
  readonly code?: string;
  readonly reason?: string;
  readonly status?: number;
  readonly requestId?: string;

  constructor(body: ErrorBody, status?: number, fallback?: string) {
    const text = [body.message, body.detail, body.error].find((v) => typeof v === "string");
    super(text ?? fallback ?? `HTTP ${status ?? "error"}`);
    this.name = "ApiError";
    this.code = body.code;
    this.reason = body.reason;
    this.status = body.status ?? status;
    this.requestId = body.request_id;
  }
}

/** The error of a failed response, from its JSON body when it has one. */
export async function errorOf(r: Response, fallback?: string): Promise<ApiError> {
  const body = (await r.json().catch(() => ({}))) as ErrorBody;
  return new ApiError(body, r.status, fallback);
}
