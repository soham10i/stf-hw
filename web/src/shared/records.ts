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
