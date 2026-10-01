// One data-access layer for every generated file the app reads (web/public/...).
// Each file is fetched once per page load and shared by every component that asks
// for it (a small repository with a promise cache), instead of each panel and page
// keeping its own fetch + state + error copy.
import { useEffect, useState } from "react";

const BASE = import.meta.env.BASE_URL;
const cache = new Map<string, Promise<unknown>>();

/** Fetch a file under the app's base path, once. Rejects on HTTP errors and non-JSON. */
export function loadJson<T>(path: string): Promise<T> {
  if (!cache.has(path)) {
    const p = fetch(`${BASE}${path}`, { cache: "no-store" }).then((r) => {
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.json();
    });
    p.catch(() => cache.delete(path));           // a failed fetch may be retried later
    cache.set(path, p);
  }
  return cache.get(path) as Promise<T>;
}

export type Loaded<T> = { data: T | null; error: string | null; loading: boolean };

/** React hook over loadJson. `hint` is what the error says to run when the file is missing. */
export function useJson<T>(path: string, hint?: string): Loaded<T> {
  const [state, setState] = useState<Loaded<T>>({ data: null, error: null, loading: true });
  useEffect(() => {
    let live = true;
    setState({ data: null, error: null, loading: true });
    loadJson<T>(path)
      .then((data) => live && setState({ data, error: null, loading: false }))
      .catch((e: Error) => live && setState({ data: null, error: hint ?? e.message, loading: false }));
    return () => { live = false; };
  }, [path, hint]);
  return state;
}
