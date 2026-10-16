# The speech pipeline

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

## Providers, in order

| Provider | Needs | Notes |
|---|---|---|
| ElevenLabs | `ELEVENLABS_API_KEY` (optional `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL`) | MP3. On HTTP 401 / 429 / 503 it is passed over (an hour for a bad key, a minute for a limit). |
| Gemini | `GEMINI_API_KEY` | `GEMINI_TTS_MODELS` in turn: 2.5 Pro TTS (no free-tier quota), 2.5 Flash TTS, 3.8 Flash TTS. Each at its limit is passed over for Google's retry delay. |
| Local | macOS (`say`, `afconvert`) | Offline and free. On Linux, replace `LocalVoice` with Piper or espeak. |

Set the order with `TTS_PROVIDERS`, e.g. `TTS_PROVIDERS=elevenlabs,gemini` on a server without the
local voice. With none ready the endpoint answers 503 and a browser can fall back to its own
`speechSynthesis`, as the copilot does.

## The text

Markdown and `[citations]` are removed and units are spoken as words ("176 degrees Celsius",
"6.16 euros", "O E E"); at most 1 200 characters are spoken, cut at a sentence.

## From another site

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

Code: `services/api/tts.py` (providers `ElevenLabsVoice`, `GeminiVoice`, `LocalVoice`; class `Tts`).
Tests: `tests/test_tts.py`.
