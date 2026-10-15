// The live backend (services/api): the scene descriptor and the frame stream.
// The 3D machine needs neither - it is built from the export - so the twin works
// without it; the backend adds the physics kernel's stream and its order queue.
// A standalone build (HAS_API false) never contacts it at all.
import { useEffect, useState, useSyncExternalStore } from "react";
import { HAS_API } from "../shared/mode";
import { connect } from "../socket";
import { store } from "../store";
import type { SceneDescriptor } from "../types";

const RETRY_MS = 3000;

// A down API answers the dev proxy with an empty or HTML body: fail with a
// readable error instead of a raw JSON SyntaxError.
async function fetchLayout(): Promise<SceneDescriptor> {
  const r = await fetch("/layout");
  const text = await r.text();
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return JSON.parse(text) as SceneDescriptor;
}

export function useBackend() {
  const [scene, setScene] = useState<SceneDescriptor | null>(null);
  const [error, setError] = useState<string | null>(null);
  const conn = useSyncExternalStore(store.subscribe, store.get);

  useEffect(() => {
    if (!HAS_API) return;
    let cancelled = false;
    let timer: number | undefined;
    const load = () => {
      fetchLayout()
        .then((d) => {
          if (cancelled) return;
          setError(null);
          setScene(d);
          connect();                    // the socket opens once the scene graph can be built
        })
        .catch(() => {
          if (cancelled) return;
          setError("API not reachable on :8000 - run `make api`. Retrying every 3 s.");
          timer = window.setTimeout(load, RETRY_MS);
        });
    };
    load();
    return () => { cancelled = true; if (timer !== undefined) window.clearTimeout(timer); };
  }, []);

  // the socket's hello carries the backend's layout fingerprint: a restarted backend
  // with a different layout means refetching, not animating stale geometry
  useEffect(() => {
    if (scene && conn.layoutFingerprint && conn.layoutFingerprint !== scene.fingerprint) {
      fetchLayout().then(setScene).catch(() => {});
    }
  }, [conn.layoutFingerprint, scene]);

  return { scene, error, conn: HAS_API ? conn : { ...conn, conn: "standalone" as const } };
}
