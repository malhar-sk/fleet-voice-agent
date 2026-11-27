/**
 * Prepares the WAV files Chromium plays as the fake microphone (--use-file-for-fake-audio-capture).
 *
 * The committed clips (evals/audio/*.wav, e2e/audio/*.wav) are 16-bit PCM mono, which Chromium accepts,
 * but they start speaking at t=0. Chromium starts playing the file as soon as the page calls
 * getUserMedia, about 1 s BEFORE the WebRTC connection is up, so the first words are lost
 * (observed: "Which devices are offline right now?" was transcribed as "Questions are offline right now.").
 * So each clip gets LEAD_S of silence before the speech and TAIL_S after it, which also gives the
 * VAD a clear end of speech. Chromium loops the file, so the tail also separates repetitions.
 *
 * Also writes silence.wav (no speech at all) for the silence edge case.
 * Output goes to e2e/.cache/audio/ (git-ignored) and is rebuilt by globalSetup on every run.
 */
import fs from "node:fs";
import path from "node:path";

export const LEAD_S = 3.0;
export const TAIL_S = 6.0;

interface Pcm { sampleRate: number; channels: number; bitsPerSample: number; data: Buffer }

export function readWav(file: string): Pcm {
  const b = fs.readFileSync(file);
  if (b.toString("ascii", 0, 4) !== "RIFF" || b.toString("ascii", 8, 12) !== "WAVE") throw new Error(`${file}: not a WAV file`);
  let off = 12, fmt: Omit<Pcm, "data"> | undefined, data: Buffer | undefined;
  while (off + 8 <= b.length) {
    const id = b.toString("ascii", off, off + 4), size = b.readUInt32LE(off + 4), body = off + 8;
    if (id === "fmt ") {
      if (b.readUInt16LE(body) !== 1) throw new Error(`${file}: only PCM WAV is supported`);
      fmt = { channels: b.readUInt16LE(body + 2), sampleRate: b.readUInt32LE(body + 4), bitsPerSample: b.readUInt16LE(body + 14) };
    } else if (id === "data") data = b.subarray(body, body + size);
    off = body + size + (size % 2);
  }
  if (!fmt || !data) throw new Error(`${file}: missing fmt or data chunk`);
  if (fmt.bitsPerSample !== 16) throw new Error(`${file}: expected 16-bit PCM, got ${fmt.bitsPerSample}`);
  return { ...fmt, data };
}

export function writeWav(file: string, p: Pcm): void {
  const h = Buffer.alloc(44), byteRate = p.sampleRate * p.channels * (p.bitsPerSample / 8);
  h.write("RIFF", 0); h.writeUInt32LE(36 + p.data.length, 4); h.write("WAVE", 8);
  h.write("fmt ", 12); h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(p.channels, 22);
  h.writeUInt32LE(p.sampleRate, 24); h.writeUInt32LE(byteRate, 28);
  h.writeUInt16LE(p.channels * (p.bitsPerSample / 8), 32); h.writeUInt16LE(p.bitsPerSample, 34);
  h.write("data", 36); h.writeUInt32LE(p.data.length, 40);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, Buffer.concat([h, p.data]));
}

const silence = (p: Omit<Pcm, "data">, s: number) =>
  Buffer.alloc(Math.round(s * p.sampleRate) * p.channels * (p.bitsPerSample / 8));

export const REPO = path.resolve(__dirname, "..", "..");
export const CACHE = path.resolve(__dirname, "..", ".cache", "audio");

/** Padded copy of a repo-relative clip; returns the absolute path Chromium should play. */
export function padded(repoRelative: string): string {
  const src = readWav(path.join(REPO, repoRelative));
  const out = path.join(CACHE, path.basename(repoRelative));
  writeWav(out, { ...src, data: Buffer.concat([silence(src, LEAD_S), src.data, silence(src, TAIL_S)]) });
  return out;
}

/** Duration in seconds of the padded file (what push-to-talk has to hold for). */
export function durationS(file: string): number {
  const p = readWav(file);
  return p.data.length / (p.sampleRate * p.channels * (p.bitsPerSample / 8));
}

export function makeSilence(seconds = 20): string {
  const out = path.join(CACHE, "silence.wav");
  const fmt = { sampleRate: 22050, channels: 1, bitsPerSample: 16 };
  writeWav(out, { ...fmt, data: silence(fmt, seconds) });
  return out;
}
