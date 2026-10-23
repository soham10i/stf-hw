// Usage traction, consent-gated (the server's visits.py). The choice lives in localStorage
// (the banner's state) and in a plain cookie (so anything server-side can see it too); only
// "accepted" sends the beacon, and the server stores nothing at all otherwise. The beacon
// carries the page name and the consent flag - no name, no email, no exact location: the server
// attaches the guest session and a coarse place from the IP.
import { HAS_API } from "./mode";
import { fetchGuest } from "./session";
import { api } from "./api";

const LS_KEY = "stf.consent";
const COOKIE = "stf_consent";
export type Consent = "accepted" | "declined";

export function consent(): Consent | null {
  try {
    const v = localStorage.getItem(LS_KEY);
    return v === "accepted" || v === "declined" ? v : null;
  } catch {
    return null;
  }
}

export function setConsent(c: Consent, days = 180) {
  try {
    localStorage.setItem(LS_KEY, c);
  } catch { /* private mode: the cookie still carries the choice */ }
  const secure = location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${COOKIE}=${c}; Path=/; Max-Age=${days * 86400}; SameSite=Lax${secure}`;
}

/** The server issues the guest session on its first /guest call; a beacon sent before that has
    nobody to attribute to. Once per page load is plenty - the middleware keeps it fresh. */
let guestReady: Promise<unknown> | null = null;
export function ensureGuest(page?: string) {
  guestReady ??= fetchGuest(page).catch(() => undefined);
  return guestReady;
}

/** A page visit, notified to owner immediately and stored if consent given. Fire-and-forget. */
export function track(page: string, ua = true) {
  if (!HAS_API) return;
  const p = page.trim().slice(0, 200);
  if (!p) return;
  void ensureGuest(p)
    .then(() =>
      fetch(api("/guest/track"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page: p, consent: consent() === "accepted", ua }),
      }),
    )
    .catch(() => undefined); // traction must never disturb the visit
}
