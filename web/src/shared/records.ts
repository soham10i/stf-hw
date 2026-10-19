// What the 3D twin does, kept in the database as this visitor's (the API's factory tables):
// every cookie its camera judged, and every order line it finished. Without the API (the public
// demo) nothing is sent; a failed request is dropped - the twin never waits on the database.
import { HAS_API } from "./mode";
import type { TwinRecord } from "../scene/store/useCellStore";

export function postRecord(r: TwinRecord) {
  if (!HAS_API) return;
  const { kind, ...body } = r;
  void fetch(kind === "inspection" ? "/twin/inspection" : "/twin/order", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), keepalive: true,
  }).catch(() => undefined);
}

// What this session did before, as the API stored it under the guest's id (GET /twin/records):
// the order lines the twin finished and the cookies its camera judged. Null without the API or on
// any failure - the panels treat history as a courtesy, never a dependency.
export type TwinOrderRow = {
  t: string; flavour: string; qty: number; baked: number; good: number;
  scrap: number; qc_fault: string;
};
export type TwinInspectionRow = {
  t: string; n: number; flavour: string; truth: string; condition: string;
  p: number; verdict: string; ae: number;
};
export type TwinRecords = {
  database: string;
  orders: TwinOrderRow[];
  inspections: TwinInspectionRow[];
};

export function fetchRecords(): Promise<TwinRecords | null> {
  if (!HAS_API) return Promise.resolve(null);
  return fetch("/twin/records")
    .then((r) => (r.ok ? (r.json() as Promise<TwinRecords>) : null))
    .catch(() => null);
}

/** A short relative time for a record's timestamptz: "just now", "4 min ago", "3 h ago". */
export function ago(t: string): string {
  const s = (Date.now() - new Date(t).getTime()) / 1000;
  if (Number.isNaN(s)) return "";
  if (s < 45) return "just now";
  if (s < 90 * 60) return `${Math.round(s / 60)} min ago`;
  if (s < 48 * 3600) return `${Math.round(s / 3600)} h ago`;
  return new Date(t).toLocaleDateString();
}
