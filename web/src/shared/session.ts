// This visitor's session on the API (guests.py): the server issued the browser a signed
// session id; the record says only when it was made and how often it was seen - no personal
// data. Two visitors never share it, so none of one's orders, photos or chats reach the other.
// Without the API (the public demo) there is no session at all.
import { HAS_API } from "./mode";
import { api } from "./api";

export type GuestStatus = {
  guest: string;            // the session id, first 8 hex chars
  session_id?: string;      // full session id
  since: number | null;     // epoch seconds, when the session was made
  visits: number | null;
  kept_days: number;        // unseen this long, the record and its data are removed
  database: string;         // 'supabase' or 'sqlite'
  note: string;             // why the database is what it is (empty when healthy)
};

let _cachedGuest: Promise<GuestStatus | null> | null = null;

export function fetchGuest(page = "site"): Promise<GuestStatus | null> {
  if (!HAS_API) return Promise.resolve(null);
  const q = page ? `?page=${encodeURIComponent(page)}` : "";
  // a failure is not kept: the next caller (the live link reconnecting) asks again, so the
  // session cookie is issued once the API is reachable
  const forget = () => { _cachedGuest = null; return null; };
  _cachedGuest ??= fetch(api(`/guest${q}`))
    .then((r) => (r.ok ? (r.json() as Promise<GuestStatus>) : forget()))
    .catch(forget);
  return _cachedGuest;
}
