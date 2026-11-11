// The microphone as the streaming transcriber wants it (services/api/voice/stt_stream.py):
// 16 kHz, mono, 16-bit little-endian PCM, posted to the page in 100 ms pieces.
//
// The AudioContext runs at the device's rate (44.1 or 48 kHz). Asking the context for 16 kHz
// instead is not portable (Firefox refuses to connect a microphone at another rate), so the
// samples are brought down here: each output sample is the mean of the input samples it
// covers, which also filters what 16 kHz cannot carry. A plain file, not a blob, so the
// built app's Content-Security-Policy (script-src 'self') lets it load.
const OUT_RATE = 16000;
const PIECE = 1600; // samples: 100 ms

class Pcm16k extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = sampleRate / OUT_RATE; // input samples per output sample
    this.acc = 0;
    this.n = 0;
    this.pos = 0;
    this.out = new Int16Array(PIECE);
    this.k = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.acc += ch[i];
      this.n++;
      this.pos++;
      if (this.pos >= this.step) {
        this.pos -= this.step;
        const v = Math.max(-1, Math.min(1, this.acc / this.n));
        this.out[this.k++] = v < 0 ? v * 0x8000 : v * 0x7fff;
        this.acc = 0;
        this.n = 0;
        if (this.k === PIECE) {
          this.port.postMessage(this.out.buffer, [this.out.buffer]);
          this.out = new Int16Array(PIECE);
          this.k = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("pcm-16k", Pcm16k);
