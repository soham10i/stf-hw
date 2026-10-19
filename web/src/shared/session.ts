// This visitor's session on the API (guests.py): the server issued the browser a signed
// session id; the record says only when it was made and how often it was seen - no personal
// data. Two visitors never share it, so none of one's orders, photos or chats reach the other.
// Without the API (the public demo) there is no session at all.
import { HAS_API } from "./mode";

export type GuestStatus = {
  guest: string;            // the session id, first 8 hex chars
  since: number | null;     // epoch seconds, when the session was made
  visits: number | null;
  kept_days: number;        // unseen this long, the record and its data are removed
  database: string;         // 'supabase' or 'sqlite'
  note: string;             // why the database is what it is (empty when healthy)
};

export function fetchGuest(): Promise<GuestStatus | null> {
  if (!HAS_API) return Promise.resolve(null);
  return fetch("/guest")
    .then((r) => (r.ok ? (r.json() as Promise<GuestStatus>) : null))
    .catch(() => null);
}
