# The speech pipeline

A spoken question goes through three steps, and each step has its own job:

```
question (speech) --POST /chat/stt--> text --POST /chat--> answer --POST /chat/tts--> speech
                    ElevenLabs Scribe         Groq / Gemini /          ElevenLabs voice 01
                    (Groq Whisper, Gemini)    Ollama (the copilot)     (Groq, Gemini, local)
```

**ElevenLabs only listens and speaks.** It turns the operator's recording into text and reads
an answer aloud. It never writes an answer: every answer comes from the copilot's language
models (Groq first), from the twin's tools and documents. Only `services/api/tts.py` calls
ElevenLabs, and `tests/test_voice.py` checks that no other module does and that ElevenLabs is
never one of the chat's models.

Measured on 2026-10-18 (`make voice-check`, then the three endpoints in turn):

| Step | Provider | Time | Result |
|---|---|---|---|
| speech to text | ElevenLabs `scribe_v1` | 0.7-0.9 s | 103-character sentence, every word right |
| speech to text (comparison) | Groq `whisper-large-v3-turbo` | 0.3-0.4 s | every word right |
| text to answer | Groq `openai/gpt-oss-120b` | 1.0 s | route: documents |
| answer to speech | ElevenLabs `eleven_multilingual_v2`, voice 01 | 1.5 s for 103 characters, 7 s for a long answer (first request after a pause: up to 14 s) | MP3 |

`eleven_flash_v2_5` was not faster here, and its audio was transcribed less exactly ("HPW" for
"HBW"), so the multilingual model stays the default.

## Speech to text

```
POST /chat/stt
Content-Type: audio/webm        (or audio/ogg, audio/wav, audio/mp4, audio/mpeg, audio/aac)

<the recording, at most 2 MB>
```

The answer is `{"text": ..., "model": "elevenlabs scribe_v1"}`. Providers are tried in the
order `STT_PROVIDERS` (default `elevenlabs,groq,gemini`); one without a key, at its limit or
failing is passed over. `GET /chat/stt/status` lists them in order, with which are ready. When
one is ready, the copilot's Voice tab records the question and the server transcribes it; only
without one does it use the browser's own speech recognition.

| Provider | Needs | Notes |
|---|---|---|
| ElevenLabs Scribe | `ELEVENLABS_API_KEY` (optional `ELEVENLABS_STT_MODEL`, default `scribe_v1`) | On HTTP 401 / 402 it is passed over for an hour, on 429 / 503 for a minute. |
| Groq Whisper | `GROQ_API_KEY` (optional `GROQ_STT_MODEL`) | The fastest. |
| Gemini | `GEMINI_API_KEY` (`GEMINI_STT_MODELS` in turn) | Free-tier daily quota. |

## Text to speech

One HTTP endpoint turns text into speech, trying providers in order until one speaks. The twin's
copilot uses it; any other site (a portfolio, a demo page) can use it the same way.

```
POST /chat/tts
Content-Type: application/json

{"text": "The oven is at 176 °C.", "voice": "Kore"}
```

The answer is the audio itself (`audio/mpeg` from ElevenLabs, `audio/wav` from Gemini and the local
voice), with two headers saying who spoke:

| Header | Example |
|---|---|
| `X-TTS-Provider` | `elevenlabs`, `gemini`, `local` |
| `X-TTS-Model` | `elevenlabs eleven_multilingual_v2`, `gemini-2.5-flash-preview-tts`, `macOS say` |

`GET /chat/tts/status` lists the providers and whether each is ready, and the Gemini voices' quota.

### Providers, in order

| Provider | Needs | Notes |
|---|---|---|
| ElevenLabs | `ELEVENLABS_API_KEY`, the voices `ELEVENLABS_VOICE_ID_01`, `ELEVENLABS_VOICE_ID_02`, ... (`ELEVENLABS_VOICE` picks one, default `01`), optional `ELEVENLABS_MODEL` | MP3. On HTTP 401 / 402 it is passed over for an hour, on 429 / 503 for a minute. `X-TTS-Model` names the voice, e.g. `elevenlabs eleven_multilingual_v2 voice 01`. |
| Groq | `GROQ_API_KEY` (optional `GROQ_TTS_MODEL`) | WAV. |
| Gemini | `GEMINI_API_KEY` | `GEMINI_TTS_MODELS` in turn: 2.5 Pro TTS (no free-tier quota), 2.5 Flash TTS, 3.8 Flash TTS. Each at its limit is passed over for Google's retry delay. |
| Local | macOS (`say`, `afconvert`) | Offline and free. On Linux, replace `LocalVoice` with Piper or espeak. |

Set the order with `TTS_PROVIDERS`, e.g. `TTS_PROVIDERS=elevenlabs,gemini` on a server without the
local voice. With none ready the endpoint answers 503 and a browser can fall back to its own
`speechSynthesis`, as the copilot does.

### The text

Markdown and `[citations]` are removed and units are spoken as words ("176 degrees Celsius",
"6.16 euros", "O E E"); LaTeX is verbalized (see below); at most 3 000 characters are
spoken, cut at a sentence.

### From another site

```js
const r = await fetch("https://<api-host>/chat/tts", {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ text: "Hello from the portfolio" }),
});
if (r.ok) new Audio(URL.createObjectURL(await r.blob())).play();
else speechSynthesis.speak(new SpeechSynthesisUtterance("Hello from the portfolio"));
```

The other site's origin must be in `STF_ALLOWED_ORIGINS` on the API (requests from other origins are
refused), and each client is rate-limited (3 at once, then one every 10 s) under a daily budget
(`GEMINI_TTS_DAILY_LIMIT`) - the keys stay on the server.

Mathematics is read the way a lecturer reads it, not symbol by symbol. The equation's
hierarchy is carried two ways:

- **Wording that names the structure** (`services/api/mathspeak.py`, rules, offline):
  "rho times the quantity ...", "a plus b, all over c", "one half m v squared", "the gradient
  of p", "the divergence of tau", "the curl of B", "the Laplacian of u", "u dot del u",
  "sine of the quantity k x minus omega t", "the integral from 0 to 1 of x squared, d x".
  Never "open bracket / close bracket".
- **Pauses at three strengths**: a short one where a bracketed group closes, a medium one
  between the terms of each side, a long one before the relation. mathspeak emits them as
  marks; `tts.prosody` renders them for the engine - timed `<break>` tags (0.25 s, 0.45 s)
  for ElevenLabs' v2 models, commas for Gemini, Groq, the local voice and `eleven_v3`.
  An expression of ten words or fewer is read in one breath.

A long answer is synthesized in pieces; a piece is cut at an equation's strongest pause
(before "equals" first), and ElevenLabs is given the sentences before and after each piece
(`previous_text` / `next_text`), so the intonation runs on across the pieces.

Example: `\rho(\partial_t \mathbf{u} + (\mathbf{u}\cdot\nabla)\mathbf{u}) = -\nabla p +
\mu\nabla^2\mathbf{u} + \rho\mathbf{f}` is read "rho times the quantity partial u by partial
t, plus u dot del u, [long pause] equals minus the gradient of p, [pause] plus mu times the
Laplacian of u, [pause] plus rho f".

**No separate LLM is needed for this.** The structure is in the LaTeX, and the rules read it
deterministically, offline, at no cost and with no added latency. A language model only
helps with notation the rules cannot say: `services/api/fluent_math.py` sends just those
expressions (mathspeak raises `Unsupported`) to the chat's model (Groq, then Gemini), with a
prompt in the same lecturer style, batched and cached per expression. `TTS_MATH_FLUENT`
sets this: unset or `fallback` (default) as described; `always` sends every expression to
the LLM first (about 1 s more per answer, quota, and readings that may vary); `0` turns it
off. What nothing can say (matrices, custom macros) is read as "(formula)", and code as
"(code)".

## Checking it

`make voice-check` uses the real providers and prints no key:

1. which speech-to-text and text-to-speech providers are ready, in order;
2. ElevenLabs reads a known sentence aloud with the configured voice (one short request);
3. ElevenLabs Scribe, and Groq Whisper for comparison, transcribe that audio back. Each
   transcript is scored against the sentence by word error rate; above 15 % the check fails.

The audio is kept at `.cache/voice-check.mp3`. Before deploying, run it with the same keys the
server will use.

Code: `services/api/tts.py` (providers `ElevenLabsVoice`, `GroqVoice`, `GeminiVoice`, `LocalVoice`;
`ElevenLabsStt`; classes `Tts` and `Stt`), `services/api/voice_check.py`.
Tests: `tests/test_tts.py`, `tests/test_voice.py`, `tests/test_mathspeak.py`, `tests/test_fluent_math.py`.
