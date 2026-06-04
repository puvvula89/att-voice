// audio.js — mic capture and PCM playback for Gemini Live native audio
//
// INPUT:  16 kHz, mono, 16-bit signed PCM (little-endian), base64-encoded
// OUTPUT: 24 kHz, mono, 16-bit signed PCM decoded to Float32 and played

// ---------------------------------------------------------------------------
// Playback
// ---------------------------------------------------------------------------

let _playCtx = null;
let _nextPlayTime = 0;
const OUTPUT_SAMPLE_RATE = 24000;

/**
 * True while the agent's audio is still playing (plus a short tail). Used for
 * half-duplex: the client stops sending mic audio while the agent speaks, so the
 * model never "hears itself" through the speakers and advances on its own.
 */
export function isAgentSpeaking() {
  if (!_playCtx) return false;
  return _playCtx.currentTime < _nextPlayTime + 0.2;
}

function getPlayContext() {
  if (!_playCtx) {
    _playCtx = new AudioContext({ sampleRate: OUTPUT_SAMPLE_RATE });
    _nextPlayTime = _playCtx.currentTime;
  }
  return _playCtx;
}

/**
 * Resume the playback AudioContext. MUST be called from a user-gesture handler
 * (click/keypress) — browsers keep an AudioContext "suspended" until then, so
 * scheduled audio is silent. Without this, model audio never plays.
 */
export async function unlockAudio() {
  const ctx = getPlayContext();
  if (ctx.state === "suspended") await ctx.resume();
}

/**
 * Decode a base64-encoded 24 kHz / mono / 16-bit PCM frame and enqueue it
 * for gapless playback.
 *
 * @param {string} base64Pcm
 */
export function playFrame(base64Pcm) {
  const ctx = getPlayContext();
  if (ctx.state === "suspended") ctx.resume(); // defensive; real unlock happens on the Start gesture

  // genai serializes audio bytes as base64url (uses - and _); browser atob() needs standard base64.
  const standardB64 = base64Pcm.replace(/-/g, "+").replace(/_/g, "/");
  const binaryStr = atob(standardB64);
  const bytes = new Uint8Array(binaryStr.length);
  for (let i = 0; i < binaryStr.length; i++) {
    bytes[i] = binaryStr.charCodeAt(i);
  }

  // Int16 little-endian → Float32
  const numSamples = bytes.length >> 1; // 2 bytes per sample
  const float32 = new Float32Array(numSamples);
  const view = new DataView(bytes.buffer);
  for (let i = 0; i < numSamples; i++) {
    float32[i] = view.getInt16(i * 2, /*littleEndian=*/true) / 32768.0;
  }

  // Build AudioBuffer and schedule for gapless playback
  const buffer = ctx.createBuffer(1, numSamples, OUTPUT_SAMPLE_RATE);
  buffer.copyToChannel(float32, 0);

  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(ctx.destination);

  const startAt = Math.max(ctx.currentTime, _nextPlayTime);
  source.start(startAt);
  _nextPlayTime = startAt + buffer.duration;
}

// ---------------------------------------------------------------------------
// Capture
// ---------------------------------------------------------------------------

const INPUT_SAMPLE_RATE = 16000;
const CAPTURE_CHUNK_FRAMES = 1600; // 100 ms of 16 kHz audio

/**
 * Start microphone capture.  Calls onFrame(base64) with 16 kHz / mono /
 * 16-bit signed PCM (little-endian) chunks, base64-encoded.
 *
 * Uses ScriptProcessorNode (widely supported, no extra worker file needed).
 *
 * @param {(base64: string) => void} onFrame
 */
export async function startMic(onFrame) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    video: false,
  });
  const captureCtx = new AudioContext();
  if (captureCtx.state === "suspended") await captureCtx.resume();
  const source = captureCtx.createMediaStreamSource(stream);

  // ScriptProcessorNode buffer size — process in 4096-sample chunks at the
  // native AudioContext rate, then accumulate and downsample.
  const PROC_BUFFER = 4096;
  const processor = captureCtx.createScriptProcessor(PROC_BUFFER, 1, 1);

  // Accumulator for resampled output
  let accumulator = new Float32Array(0);

  processor.onaudioprocess = (event) => {
    const input = event.inputBuffer.getChannelData(0); // Float32, native rate
    const nativeRate = captureCtx.sampleRate;

    // Downsample to 16 kHz via simple linear interpolation
    const ratio = nativeRate / INPUT_SAMPLE_RATE;
    const outLength = Math.floor(input.length / ratio);
    const resampled = new Float32Array(outLength);
    for (let i = 0; i < outLength; i++) {
      const pos = i * ratio;
      const lo = Math.floor(pos);
      const hi = Math.min(lo + 1, input.length - 1);
      const frac = pos - lo;
      resampled[i] = input[lo] * (1 - frac) + input[hi] * frac;
    }

    // Append to accumulator
    const merged = new Float32Array(accumulator.length + resampled.length);
    merged.set(accumulator, 0);
    merged.set(resampled, accumulator.length);
    accumulator = merged;

    // Emit complete chunks
    while (accumulator.length >= CAPTURE_CHUNK_FRAMES) {
      const chunk = accumulator.slice(0, CAPTURE_CHUNK_FRAMES);
      accumulator = accumulator.slice(CAPTURE_CHUNK_FRAMES);

      // Float32 → Int16 little-endian
      const pcm = new Int16Array(chunk.length);
      for (let i = 0; i < chunk.length; i++) {
        const clamped = Math.max(-1, Math.min(1, chunk[i]));
        pcm[i] = clamped < 0 ? clamped * 32768 : clamped * 32767;
      }

      // Int16Array → base64
      const bytes = new Uint8Array(pcm.buffer);
      let binary = "";
      for (let i = 0; i < bytes.length; i++) {
        binary += String.fromCharCode(bytes[i]);
      }
      onFrame(btoa(binary));
    }
  };

  source.connect(processor);
  // ScriptProcessorNode must be connected to destination to keep running
  processor.connect(captureCtx.destination);
}
