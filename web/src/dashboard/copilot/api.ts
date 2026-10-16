// The copilot's client: who the user is (an anonymous id kept in this browser), which session is
// open, and the calls to the server - ask, the history, speech out (TTS) and speech in (STT).
// The session id is shared by the Copilot page and the Ask panel on every dashboard page, so a
// conversation continues wherever it is picked up.
import { HAS_API } from "../../shared/mode";

export type Tab = "gemini" | "local" | "voice";
export type Style = "greeting" | "quick" | "compare" | "steps" | "status" | "list" | "explain" | "answer";
export type Switch = { from: string; to: string | null; why: string };
export type Turn = {
  role: "user" | "assistant"; text: string; t: number;
  model?: string; style?: Style; sources?: string[]; links?: { page: string; label: string }[];
  tools?: string[]; note?: string; unverified?: string[]; switched?: Switch[]; facts?: [string, string][];
  ms?: number; pending?: boolean;
};
export type Fact = [name: string, value: string, source: string];
export type Session = {
  id: string; title: string; created: number; updated: number; n_turns: number; last_model: string | null;
  turns: Turn[]; context: { facts: Fact[]; tools: string[]; models: string[]; page: string | null };
};
export type Summary = Pick<Session, "id" | "title" | "updated" | "n_turns" | "last_model">;
export type Status = {
  enabled: boolean; model: string | null; gemini?: boolean; ollama?: boolean;
  gemini_model?: string | null; ollama_model?: string | null;
  gemini_pool?: { model: string; free: boolean; back_in_s?: number }[] | null;
};

const store = {
  get: (k: string) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k: string, v: string | null) => { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch { /* private mode */ } },
};

/** An anonymous id for this browser: the owner of its sessions on the server. */
export function userId() {
  let u = store.get("stf.copilot.user");
  if (!u || !/^[a-zA-Z0-9_-]{8,64}$/.test(u)) {
    u = "u" + Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => b.toString(16).padStart(2, "0")).join("");
    store.set("stf.copilot.user", u);
  }
  return u;
}
export const currentSession = { get: () => store.get("stf.copilot.session"), set: (id: string | null) => store.set("stf.copilot.session", id) };
export const savedTab = { get: () => (store.get("stf.copilot.tab") as Tab | null) ?? "gemini", set: (t: Tab) => store.set("stf.copilot.tab", t) };

const H = () => ({ "Content-Type": "application/json", "X-STF-User": userId() });

export async function status(): Promise<Status> {
  if (!HAS_API) return { enabled: false, model: null };
  try { const r = await fetch("/chat/status"); if (r.ok) return await r.json(); } catch { /* offline */ }
  return { enabled: false, model: null };
}

export async function ask(body: { question: string; page: string; provider: string; session_id?: string | null; age?: number; pm?: boolean }) {
  const r = await fetch("/chat", { method: "POST", headers: H(), body: JSON.stringify({ ...body, session_id: body.session_id ?? undefined }) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail ?? `HTTP ${r.status}`);
  return j as {
    answer: string; model: string; style: Style; sources: string[]; links: { page: string; label: string }[];
    tools: string[]; facts: [string, string][]; note?: string; unverified?: string[]; switched?: Switch[];
    session?: { id: string; title: string; facts: number; models: string[] };
  };
}

export async function sessions(): Promise<Summary[]> {
  if (!HAS_API) return [];
  try { const r = await fetch("/copilot/sessions", { headers: H() }); return r.ok ? (await r.json()).sessions : []; } catch { return []; }
}
export async function session(id: string): Promise<Session | null> {
  try { const r = await fetch(`/copilot/sessions/${id}`, { headers: H() }); return r.ok ? await r.json() : null; } catch { return null; }
}
export async function forget(id: string) {
  await fetch(`/copilot/sessions/${id}`, { method: "DELETE", headers: H() }).catch(() => undefined);
}

/** The answer as speech: the server's voice pipeline, or null (then the browser speaks). */
export async function speech(text: string): Promise<{ url: string; by: string } | null> {
  if (!HAS_API) return null;
  try {
    const r = await fetch("/chat/tts", { method: "POST", headers: H(), body: JSON.stringify({ text }) });
    if (!r.ok) return null;
    const by = [r.headers.get("X-TTS-Provider"), r.headers.get("X-TTS-Model")].filter(Boolean).join(" · ");
    return { url: URL.createObjectURL(await r.blob()), by };
  } catch { return null; }
}

/** A recorded question as text, by the server (for browsers without speech recognition). */
export async function transcribe(blob: Blob): Promise<string> {
  const r = await fetch("/chat/stt", { method: "POST", headers: { "Content-Type": blob.type.split(";")[0], "X-STF-User": userId() }, body: blob });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail ?? `HTTP ${r.status}`);
  return j.text as string;
}

export const ago = (t: number) => {
  const s = Date.now() / 1000 - t;
  return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
};
