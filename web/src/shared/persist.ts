// State that survives a reload, per browser (localStorage). Storage can be
// missing or throw (private mode, blocked site data): the app then just forgets.
import { useState } from "react";

export function usePersistent<T>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  const set = (x: T) => {
    setV(x);
    try { localStorage.setItem(key, JSON.stringify(x)); } catch { /* not persisted */ }
  };
  return [v, set];
}
