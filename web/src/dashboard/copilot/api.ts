// The copilot's client: who the user is (an anonymous id kept in this browser), which session is
// open, and the calls to the server - ask, the history, speech out (TTS) and speech in (STT).
// The session id is shared by the Copilot page and the Ask panel on every dashboard page, so a
// conversation continues wherever it is picked up.
import { HAS_API } from "../../shared/mode";

export type Tab = "chat" | "voice";
/** One merged model control: "auto" walks the chain below in order; the rest pin one provider. */
export type Model = "auto" | "gemini" | "groq" | "upb" | "local";
export type Style = "greeting" | "quick" | "compare" | "steps" | "status" | "list" | "explain" | "derive" | "research" | "answer";
/** Where the server sent a question, and why (services/api/orchestrate.py). */
export type Mode = "chat" | "twin" | "docs" | "web" | "deep";
export type Route = { mode: Mode; why: string[]; signals?: Record<string, unknown> };
/** The operator's choice in the composer: auto lets the server decide. */
export type Choice = "auto" | "docs" | "web" | "deep";
export type Switch = { from: string; to: string | null; why: string };
/** How much an answer may spend (services/api/depth.py); "auto" lets the server pick. */
export type Depth = "auto" | "brief" | "standard" | "thorough";
/** Who the answer is written for (depth.py AUDIENCE). */
export type Audience = "operator" | "engineer" | "researcher";
/** Which web pages an answer may use (services/api/source_policy.py): forums and social media
    are never used; "strict" keeps only standards, agencies, papers, makers and references. */
export type SourceLevel = "vetted" | "strict";
export type Grade = "authoritative" | "reference" | "community";
/** What one answer cost: every model call's tokens, by provider (token_budget.meter). */
export type Usage = { tokens: number; calls: number; by: Record<string, number>; depth: Exclude<Depth, "auto">;
  audience?: Audience | null; sources: SourceLevel; removed: number };
/** Where a source is, exactly (services/api/chat.py _cites): a document passage (its file, line,
    heading anchor, match score and text), a tool that computed facts, or a web page. */
export type Cite = { kind: "doc" | "tool" | "web"; tool: string; label: string; file?: string; line?: number;
  anchor?: string; score?: number; quote?: string; title?: string; trusted?: boolean; cited?: boolean; grade?: Grade };
export type Turn = {
  role: "user" | "assistant"; text: string; t: number;
  model?: string; style?: Style; sources?: string[]; links?: { page: string; label: string }[];
  tools?: string[]; note?: string; unverified?: string[]; switched?: Switch[]; facts?: [string, string][];
  cites?: Cite[]; ms?: number; pending?: boolean;
  route?: Route; steps?: string[]; thinking?: string; usage?: Usage;
};
export type Fact = [name: string, value: string, source: string];
export type Session = {
  id: string; title: string; created: number; updated: number; n_turns: number; last_model: string | null;
  turns: Turn[]; context: { facts: Fact[]; tools: string[]; models: string[]; page: string | null };
  /** what the next model is given from this session, as it is given (Markdown; sessions.py) */
  memory?: string;
};
export type Summary = Pick<Session, "id" | "title" | "updated" | "n_turns" | "last_model">;
export type Status = {
  enabled: boolean; model: string | null; gemini?: boolean; groq?: boolean; upb?: boolean; ollama?: boolean;
  gemini_model?: string | null; groq_model?: string | null; upb_model?: string | null; ollama_model?: string | null;
  gemini_pool?: { model: string; free: boolean; back_in_s?: number }[] | null;
  /** the providers in try-order, with readiness (services/api/chat.py ORDER) */
  order?: { name: string; ready: boolean }[];
  /** the web search's order and Gemini's token budget (services/api/token_budget.py) */
  search?: { order: string[]; gemini: boolean; gemini_rest_s: number;
    /** each Gemini key in the order it is asked (Google Cloud before AI Studio) */
    lanes?: { name: "cloud" | "studio"; label: string; models_free: number; rest_s: number; refused: boolean }[];
    budget: { tier: "full" | "lean" | "minimal" | "spent"; tokens_day: { used: number; limit: number };
      searches_day: { used: number; limit: number } } | null };
  /** who pays for each provider, as the operator labelled it (chat.py status) */
  billing?: { provider: string; plan: string }[];
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
export const savedChoice = { get: () => (store.get("stf.copilot.choice") as Choice | null) ?? "auto", set: (c: Choice) => store.set("stf.copilot.choice", c) };
// tabs used to name a provider (gemini/groq/…); those all fold into the chat tab now
export const savedTab = { get: (): Tab => (store.get("stf.copilot.tab") === "voice" ? "voice" : "chat"), set: (t: Tab) => store.set("stf.copilot.tab", t) };
// the UI offers only Auto and Local: a saved pin to a cloud provider (an earlier version)
// falls back to Auto; the chain itself stays a server detail
export const savedModel = { get: (): Model => { const m = store.get("stf.copilot.model") as Model | null; return m === "local" ? "local" : "auto"; }, set: (m: Model) => store.set("stf.copilot.model", m) };
/** What the server calls each model choice; "auto" sends none, so the server walks its chain. */
/** The answer settings, kept in this browser: who is asking, how deep, which sources. */
export type Prefs = { audience: Audience; depth: Depth; sources: SourceLevel };
export const PROFILE_DEFAULTS: Record<Audience, Prefs> = {
  operator: { audience: "operator", depth: "brief", sources: "vetted" },
  engineer: { audience: "engineer", depth: "auto", sources: "vetted" },
  researcher: { audience: "researcher", depth: "thorough", sources: "strict" },
};
export const savedPrefs = {
  get: (): Prefs => {
    try {
      const p = JSON.parse(store.get("stf.copilot.prefs") ?? "null") as Partial<Prefs> | null;
      const a: Audience = p?.audience && p.audience in PROFILE_DEFAULTS ? p.audience : "engineer";
      const d = PROFILE_DEFAULTS[a];
      return {
        audience: a,
        depth: (["auto", "brief", "standard", "thorough"] as Depth[]).includes(p?.depth as Depth) ? p!.depth as Depth : d.depth,
        sources: p?.sources === "strict" || p?.sources === "vetted" ? p.sources : d.sources,
      };
    } catch { return PROFILE_DEFAULTS.engineer; }
  },
  set: (p: Prefs) => store.set("stf.copilot.prefs", JSON.stringify(p)),
};
export const providerOf = (m: Model): string | undefined => ({ auto: undefined, gemini: "gemini", groq: "groq", upb: "upb", local: "ollama" })[m];

const H = () => ({ "Content-Type": "application/json", "X-STF-User": userId() });

export async function status(): Promise<Status> {
  if (!HAS_API) return { enabled: false, model: null };
  try { const r = await fetch("/chat/status"); if (r.ok) return await r.json(); } catch { /* offline */ }
  return { enabled: false, model: null };
}

type AskBody = { question: string; page: string; provider?: string; session_id?: string | null; age?: number; pm?: boolean; mode?: Choice;
  depth?: Depth; audience?: Audience; sources?: SourceLevel };
export type Reply = {
  answer: string; model: string; style: Style; sources: string[]; links: { page: string; label: string }[];
  tools: string[]; facts: [string, string][]; note?: string; unverified?: string[]; switched?: Switch[];
  cites?: Cite[]; session?: { id: string; title: string; facts: number; models: string[] };
  route?: Route; steps?: string[]; thinking?: string; usage?: Usage;
};
const payload = (body: AskBody) => JSON.stringify({ ...body, session_id: body.session_id ?? undefined,
  mode: body.mode === "auto" ? undefined : body.mode, depth: body.depth === "auto" ? undefined : body.depth });

export async function ask(body: AskBody) {
  const r = await fetch("/chat", { method: "POST", headers: H(), body: payload(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail ?? `HTTP ${r.status}`);
  return j as Reply;
}

/** What the server reports while it answers (POST /chat/stream). */
export type Progress = { route?: Route; step?: string; thinking?: string };

/** Ask, and hear the route, each step and the model's thinking as they happen; resolves with
    the reply. Falls back to the plain request where the stream is not served. */
export async function askStream(body: AskBody, on: (p: Progress) => void): Promise<Reply> {
  const r = await fetch("/chat/stream", { method: "POST", headers: H(), body: payload(body) });
  if (r.status === 404 || r.status === 405) return ask(body);
  if (!r.ok || !r.body) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.detail ?? `HTTP ${r.status}`);
  }
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    let k: number;
    while ((k = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, k);
      buf = buf.slice(k + 2);
      const ev = /^event: (.+)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (!ev || data === undefined) continue;
      const j = JSON.parse(data);
      if (ev === "answer") return j as Reply;
      if (ev === "error") throw new Error(j.detail ?? "the copilot failed");
      if (ev === "route") on({ route: j as Route });
      else if (ev === "step") on({ step: j.text });
      else if (ev === "thinking") on({ thinking: j.text });
    }
  }
  throw new Error("the answer was cut off");
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

/** What the stream starts with: raw PCM at this sample rate, or one container file (wav/mp3). */
export type SpeakMeta = { kind: "pcm"; rate: number; by: string } | { kind: "file"; mime: string; by: string };
export type SpeakEvent =
  | { type: "meta"; meta: SpeakMeta }
  | { type: "chunk"; b64: string }
  | { type: "end" };

/** The answer read aloud as it is synthesised: POST /chat/tts/stream's SSE events (services/api/
    tts.py). Returns false where the endpoint is not served, so the caller falls back to the
    whole-file speech() below. Throws on a served failure. */
export async function speechStream(text: string, on: (e: SpeakEvent) => void): Promise<boolean> {
  if (!HAS_API) return false;
  const r = await fetch("/chat/tts/stream", { method: "POST", headers: H(), body: JSON.stringify({ text }) });
  if (r.status === 404 || r.status === 405) return false;
  if (!r.ok || !r.body) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.detail ?? `HTTP ${r.status}`);
  }
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    let k: number;
    while ((k = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, k);
      buf = buf.slice(k + 2);
      const ev = /^event: (.+)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (!ev || data === undefined) continue;
      const j = JSON.parse(data);
      if (ev === "meta") on({ type: "meta", meta: j as SpeakMeta });
      else if (ev === "chunk") on({ type: "chunk", b64: j.b64 as string });
      else if (ev === "end") { on({ type: "end" }); return true; }
      else if (ev === "error") throw new Error(j.detail ?? "the voice failed");
    }
  }
  on({ type: "end" });   // the stream closed without an end event: play what arrived
  return true;
}

/** A recorded question as text, by the server (for browsers without speech recognition). */
export async function transcribe(blob: Blob): Promise<{ text: string; model: string }> {
  const r = await fetch("/chat/stt", { method: "POST", headers: { "Content-Type": blob.type.split(";")[0], "X-STF-User": userId() }, body: blob });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail ?? `HTTP ${r.status}`);
  return { text: j.text as string, model: j.model as string };
}

/** The server's transcription: its providers in order (ElevenLabs Scribe first) and which are
    ready. When one is, the Voice tab records and the server transcribes. */
export type SttStatus = { enabled: boolean; providers: { name: string; ready: boolean; model: string | null }[] };
export async function sttStatus(): Promise<SttStatus> {
  if (!HAS_API) return { enabled: false, providers: [] };
  try { const r = await fetch("/chat/stt/status"); if (r.ok) return await r.json(); } catch { /* offline */ }
  return { enabled: false, providers: [] };
}

/** 6234 -> "6.2k" */
export const kTokens = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : `${n}`);

export const ago = (t: number) => {
  const s = Date.now() / 1000 - t;
  return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
};
