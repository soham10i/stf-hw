// The Voice tab: press, speak, hear the answer. Speech becomes text on the server when it has a
// transcriber (the recording goes to POST /chat/stt: ElevenLabs Scribe first), else in the
// browser (the Web Speech API: Chrome, Edge, Safari). The text is then asked like any other
// question - a language model (Groq, Gemini, ...) writes the answer - and the answer is read
// aloud (POST /chat/tts: ElevenLabs first). The voice services only listen and speak.
//
// Recording for the server: one mono track with the browser's echo cancellation, noise
// suppression and gain control, so the answer being read aloud and the line's own noise are
// not sent as speech. The recording ends by itself when the operator stops talking - the
// level stays under the threshold for SILENCE_MS after speech began - or after MAX_MS, or on
// a second tap. The threshold is set from the room: the first CALIBRATE_MS measure its noise.
// Starting to speak stops an answer that is still being read aloud.
//
// Streamed when the server can (GET /chat/stt/status "stream"): the microphone goes to
// WS /chat/stt/stream as 16 kHz PCM (pcm-worklet.js) while the operator speaks, the words
// appear as they are recognised, and the final text arrives a moment after the end. The
// recording is kept all the same: a stream that fails or never opens costs nothing but the
// wait, because the recording is then uploaded to POST /chat/stt as before.
import { useEffect, useRef, useState } from "react";
import { apiWs } from "../../shared/api";
import { sttStatus, transcribe } from "./api";
import { stopSpeaking } from "./Message";
// no-inline: a small file would otherwise become a data: URL, which script-src 'self' refuses
import workletUrl from "./pcm-worklet.js?url&no-inline";
import { quiet } from "../../shared/log";

type Rec = { start(): void; stop(): void; abort(): void; onresult: ((e: any) => void) | null; onend: (() => void) | null; onerror: ((e: any) => void) | null; interimResults: boolean; lang: string; continuous: boolean };
const Recognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

const MAX_MS = 20000;        // the longest question
const TICK_MS = 30;          // how often the level is measured
const CALIBRATE_MS = 300;    // the room's noise is measured first
const SPEECH_MS = 150;       // this long over the threshold is speech, not a click
const SILENCE_MS = 1200;     // this long under it after speech is the end of the question
const NOTHING_MS = 6000;     // no speech this long after the tap: stop, nothing was said
const MIN_LEVEL = 0.015;     // the threshold never goes below this (RMS of the signal, 0..1)
const MIC: MediaTrackConstraints = { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true };
const OPEN_MS = 3000;        // the stream to open, at most, before the recording is uploaded instead
const FINAL_MS = 7000;       // the final text after the end, at most (the server waits 5 s for it)

type Heard = { text: string; heard?: string; model?: string };

/** The microphone streamed to the server's transcriber: `partial` gets the words so far, and
    `end()` sends the end and resolves with the final text - or with null when the stream failed,
    never opened or did not answer in time, so the caller uploads its recording instead. */
export async function openStream(mic: MediaStream, partial: (text: string) => void) {
  const ctx = new AudioContext();
  await ctx.audioWorklet.addModule(workletUrl);
  const src = ctx.createMediaStreamSource(mic);
  const node = new AudioWorkletNode(ctx, "pcm-16k");
  src.connect(node);
  node.connect(ctx.destination);                 // pulls the node; it writes silence, nothing is heard
  const ws = new WebSocket(apiWs("/chat/stt/stream"));
  ws.binaryType = "arraybuffer";
  const early: ArrayBuffer[] = [];               // the first words, spoken while the socket opens
  let settle: (v: Heard | null) => void = () => {};
  const final = new Promise<Heard | null>((r) => { settle = r; });
  const opened = new Promise<boolean>((r) => {
    ws.onopen = () => { early.splice(0).forEach((b) => ws.send(b)); r(true); };
    ws.onclose = () => { r(false); settle(null); };
    ws.onerror = () => { r(false); settle(null); };
  });
  node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(e.data);
    else if (ws.readyState === WebSocket.CONNECTING) early.push(e.data);
  };
  ws.onmessage = (e) => {
    let m: { type?: string; text?: string; heard?: string; model?: string };
    try { m = JSON.parse(e.data as string); } catch { return; }
    if (m.type === "partial" && m.text) partial(m.text);
    else if (m.type === "final") settle({ text: m.text ?? "", heard: m.heard, model: m.model });
    else if (m.type === "error") settle(null);
  };
  const close = () => {
    src.disconnect(); node.disconnect(); node.port.onmessage = null;
    ctx.close().catch(quiet("audio"));
    if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close();
  };
  const within = <T,>(p: Promise<T>, ms: number, otherwise: T) =>
    Promise.race([p, new Promise<T>((r) => window.setTimeout(() => r(otherwise), ms))]);
  return {
    close,
    end: async (): Promise<Heard | null> => {
      src.disconnect();                          // no more audio after the end
      if (!(await within(opened, OPEN_MS, false))) { close(); return null; }
      ws.send(JSON.stringify({ type: "end" }));
      const got = await within(final, FINAL_MS, null);
      close();
      return got;
    },
  };
}

/** Watches a stream's level every TICK_MS and calls `end` once the speaker has finished (or never
    started); `level` gets the current level, scaled 0..1 for the meter. Returns a stop.
    A timer, not animation frames: a browser stops frames in a tab that is not in front, and the
    operator may look at another window while speaking. Times are measured, not counted in
    ticks, so a slowed timer (about one tick a second in a background tab) still ends the
    question - later, never wrongly. */
export function endOfSpeech(stream: MediaStream, end: (why: "done" | "nothing") => void, level: (v: number) => void) {
  const ctx = new AudioContext();
  const src = ctx.createMediaStreamSource(stream);
  const an = ctx.createAnalyser();
  an.fftSize = 1024;
  src.connect(an);
  const buf = new Float32Array(an.fftSize);
  const t0 = performance.now();
  let floor = 0, n = 0, threshold = MIN_LEVEL;
  let last = t0, loud = 0, silentMs = 0, spoke = false, over = false;
  const tick = () => {
    an.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    const rms = Math.sqrt(sum / buf.length);
    const now = performance.now();
    const dt = now - last;
    last = now;
    level(Math.min(1, rms / (threshold * 4)));
    if (now - t0 < CALIBRATE_MS) {
      floor += rms; n++;
      return;
    }
    if (n) { threshold = Math.max(MIN_LEVEL, (floor / n) * 3); n = 0; }
    if (rms > threshold) {
      // a late tick's one loud sample counts as a short stretch, never as the whole gap
      silentMs = 0; loud += Math.min(dt, 4 * TICK_MS);
      if (loud >= SPEECH_MS) spoke = true;
    } else {
      silentMs += dt;
      if (silentMs > 300) loud = 0;                     // a pause between words keeps what was loud
      if (spoke && silentMs >= SILENCE_MS) return finish("done");
    }
    if (!spoke && now - t0 >= NOTHING_MS) finish("nothing");
  };
  const finish = (why: "done" | "nothing") => { if (over) return; stop(); end(why); };
  const stop = () => { over = true; window.clearInterval(timer); src.disconnect(); ctx.close().catch(quiet("audio")); level(0); };
  const timer = window.setInterval(tick, TICK_MS);
  return { stop, spoke: () => spoke };
}

export function Voice({ busy, onAsk }: { busy: boolean; onAsk: (text: string) => void }) {
  const [state, setState] = useState<"idle" | "listening" | "transcribing">("idle");
  const [heard, setHeard] = useState("");
  const [asked, setAsked] = useState("");                        // the transcript as asked, when the server rewrote it
  const [err, setErr] = useState("");
  const [level, setLevel] = useState(0);
  const [server, setServer] = useState<string | null>(null);     // a ready transcriber on the server
  const [streams, setStreams] = useState(false);                 // the server transcribes as it hears
  const rec = useRef<Rec | null>(null);
  const media = useRef<MediaRecorder | null>(null);
  const vad = useRef<ReturnType<typeof endOfSpeech> | null>(null);
  useEffect(() => () => { rec.current?.abort(); vad.current?.stop(); if (media.current?.state === "recording") media.current.stop(); }, []);
  useEffect(() => {
    sttStatus().then((s) => {
      setServer(s.providers.some((x) => x.ready) ? "server" : null);
      setStreams(!!s.stream && typeof AudioWorkletNode !== "undefined");
    });
  }, []);

  const finish = (text: string) => {
    setState("idle");
    const t = text.trim();
    if (t) onAsk(t);
  };

  const listenBrowser = () => {
    const r: Rec = new Recognition();
    r.lang = navigator.language || "en-US";
    r.interimResults = true;
    r.continuous = false;
    let final = "";
    r.onresult = (e: any) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const s = e.results[i][0].transcript;
        if (e.results[i].isFinal) final += s; else interim += s;
      }
      setHeard(final + interim);
    };
    r.onerror = (e: any) => { setErr(e.error === "not-allowed" ? "Microphone access was refused." : `Could not listen (${e.error}).`); setState("idle"); };
    r.onend = () => finish(final);
    rec.current = r;
    r.start();
  };

  const listenRecord = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: MIC });
    const type = ["audio/webm", "audio/ogg", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
    const m = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks: Blob[] = [];
    let silent = false;
    // the words as they are heard, when the server streams; a stream that cannot open is
    // simply not used (the recording below is uploaded instead)
    const live = streams ? await openStream(stream, setHeard).catch(quiet("voice", null)) : null;
    m.ondataavailable = (e) => chunks.push(e.data);
    m.onstop = async () => {
      vad.current?.stop();
      stream.getTracks().forEach((t) => t.stop());
      if (silent) { live?.close(); setErr("I heard nothing. Tap and speak a little closer to the microphone."); setState("idle"); return; }
      setState("transcribing");
      try {
        // the stream's text, else the recording uploaded (a stream that failed, or heard no words)
        const streamed = live ? await live.end() : null;
        const t = streamed?.text ? streamed : await transcribe(new Blob(chunks, { type: m.mimeType }));
        if (!t.text.trim()) { setErr("I could not make out any words. Tap and try again."); setState("idle"); return; }
        setHeard(t.heard ?? t.text); setAsked(t.heard ? t.text : "");
        finish(t.text);
      } catch (e) { setErr((e as Error).message); setState("idle"); }
    };
    media.current = m;
    m.start();
    vad.current = endOfSpeech(stream, (why) => {
      silent = why === "nothing";
      if (m.state === "recording") m.stop();
    }, setLevel);
    window.setTimeout(() => { if (m.state === "recording") m.stop(); }, MAX_MS);
  };

  const toggle = async () => {
    setErr("");
    if (state === "listening") { rec.current?.stop(); if (media.current?.state === "recording") media.current.stop(); return; }
    if (state !== "idle" || busy) return;
    stopSpeaking();                                  // the operator talks over the answer: it stops
    setHeard(""); setAsked("");
    setState("listening");
    try { if (server || !Recognition) await listenRecord(); else listenBrowser(); }
    catch { setErr("No microphone is available."); setState("idle"); }
  };

  const say = state === "listening" ? "Listening… stops when you do" : state === "transcribing" ? "Turning speech into text…"
    : busy ? "Thinking…" : "Tap and ask, or say “take me to the oven”";
  return (
    <div className="cx-voice">
      <button className={`cx-mic ${state} ${busy ? "busy" : ""}`} onClick={toggle} aria-label={state === "listening" ? "Stop listening" : "Ask by voice"}
        style={{ "--lvl": level } as React.CSSProperties}>
        <svg viewBox="0 0 24 24" width="34" height="34" aria-hidden="true"><path fill="currentColor" d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12z" /></svg>
        {state === "listening" && <><i className="ring r1" /><i className="ring r2" /></>}
      </button>
      <b aria-live="polite">{say}</b>
      {heard && <p className="cx-heard">“{heard}”{asked && <span className="cx-asked"> asked as “{asked}”</span>}</p>}
      {err && <p className="cx-note bad" role="alert">{err}</p>}
      <span className="cx-hint">
        {streams ? "transcribed as you speak" : server ? "transcribed on the server" : Recognition ? "speech recognition in your browser" : "recorded, transcribed on the server"}
        {" · answers written by the language model, read aloud"}
      </span>
    </div>
  );
}
