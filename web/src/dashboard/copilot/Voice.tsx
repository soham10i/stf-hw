// The Voice tab: press, speak, hear the answer. Speech becomes text on the server when it has a
// transcriber (the recording goes to POST /chat/stt: ElevenLabs Scribe first), else in the
// browser (the Web Speech API: Chrome, Edge, Safari). The text is then asked like any other
// question - a language model (Groq, Gemini, ...) writes the answer - and the answer is read
// aloud (POST /chat/tts: ElevenLabs first). The voice services only listen and speak.
import { useEffect, useRef, useState } from "react";
import { sttStatus, transcribe } from "./api";

type Rec = { start(): void; stop(): void; abort(): void; onresult: ((e: any) => void) | null; onend: (() => void) | null; onerror: ((e: any) => void) | null; interimResults: boolean; lang: string; continuous: boolean };
const Recognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

export function Voice({ busy, onAsk }: { busy: boolean; onAsk: (text: string) => void }) {
  const [state, setState] = useState<"idle" | "listening" | "transcribing">("idle");
  const [heard, setHeard] = useState("");
  const [err, setErr] = useState("");
  const [server, setServer] = useState<string | null>(null);     // the server's first ready transcriber
  const [by, setBy] = useState("");
  const rec = useRef<Rec | null>(null);
  const media = useRef<MediaRecorder | null>(null);
  useEffect(() => () => { rec.current?.abort(); media.current?.stop(); }, []);
  useEffect(() => {
    sttStatus().then((s) => { const p = s.providers.find((x) => x.ready); setServer(p ? `${p.name} ${p.model ?? ""}`.trim() : null); });
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
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const type = ["audio/webm", "audio/ogg", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
    const m = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks: Blob[] = [];
    m.ondataavailable = (e) => chunks.push(e.data);
    m.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      setState("transcribing");
      try { const t = await transcribe(new Blob(chunks, { type: m.mimeType })); setHeard(t.text); setBy(t.model); finish(t.text); }
      catch (e) { setErr((e as Error).message); setState("idle"); }
    };
    media.current = m;
    m.start();
    window.setTimeout(() => { if (m.state === "recording") m.stop(); }, 20000);   // at most 20 s
  };

  const toggle = async () => {
    setErr("");
    if (state === "listening") { rec.current?.stop(); if (media.current?.state === "recording") media.current.stop(); return; }
    if (state !== "idle" || busy) return;
    setHeard("");
    setState("listening");
    try { if (server || !Recognition) await listenRecord(); else listenBrowser(); }
    catch { setErr("No microphone is available."); setState("idle"); }
  };

  const say = state === "listening" ? "Listening… tap to stop" : state === "transcribing" ? "Turning speech into text…"
    : busy ? "Thinking…" : "Tap and ask about the cell";
  return (
    <div className="cx-voice">
      <button className={`cx-mic ${state} ${busy ? "busy" : ""}`} onClick={toggle} aria-label={state === "listening" ? "Stop listening" : "Ask by voice"}>
        <svg viewBox="0 0 24 24" width="34" height="34" aria-hidden="true"><path fill="currentColor" d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12z" /></svg>
        {state === "listening" && <><i className="ring r1" /><i className="ring r2" /></>}
      </button>
      <b>{say}</b>
      {heard && <p className="cx-heard">“{heard}”</p>}
      {err && <p className="cx-note bad">{err}</p>}
      <span className="cx-hint">
        {server ? `heard by ${by || server} on the server` : Recognition ? "speech recognition in your browser" : "recorded, transcribed on the server"}
        {" · answers written by the language model, read aloud"}
      </span>
    </div>
  );
}
