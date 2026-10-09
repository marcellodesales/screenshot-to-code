// Video → frames, extracted in the browser so non-Gemini models can see a
// screen recording: 1 frame/s, at most 20 (always the first and the last),
// longest side 1280 px, JPEG q=0.85. Sent as `prompt.videoFrames`.

export const FRAME_FPS = 1;
export const MAX_FRAMES = 20;
export const FRAME_MAX_SIDE = 1280;
export const FRAME_JPEG_QUALITY = 0.85;
// Seeking exactly to `duration` often yields no frame; stay just before it.
export const LAST_FRAME_OFFSET_SEC = 0.1;
const SEEK_TIMEOUT_MS = 5_000;
const EXTRACTION_TIMEOUT_MS = 30_000;

function round3(value: number) {
  return Math.round(value * 1000) / 1000;
}

// Timestamps (seconds) to sample: every 1/fps from 0, plus the last frame;
// evenly spread over the whole video when that would exceed `max`.
export function frameTimestamps(
  durationSec: number,
  { fps = FRAME_FPS, max = MAX_FRAMES }: { fps?: number; max?: number } = {}
): number[] {
  if (!Number.isFinite(durationSec) || durationSec <= 0 || max <= 1) return [0];
  const last = round3(Math.max(0, durationSec - LAST_FRAME_OFFSET_SEC));
  if (last <= 0) return [0];

  const step = 1 / fps;
  // Skip a regular sample that would land right on top of the last frame.
  const minGap = step / 4;
  const times = [0];
  for (let k = 1; k * step < last - minGap; k++) {
    times.push(round3(k * step));
  }
  times.push(last);

  if (times.length <= max) return times;
  return Array.from({ length: max }, (_, i) => round3((last * i) / (max - 1)));
}

export function scaledSize(
  width: number,
  height: number,
  maxSide = FRAME_MAX_SIDE
): { width: number; height: number } {
  if (!(width > 0) || !(height > 0)) return { width: 0, height: 0 };
  const scale = Math.min(1, maxSide / Math.max(width, height));
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

// Grab frames one at a time (a <video> can only seek to one place at once).
export async function collectFrames(
  timestamps: number[],
  grab: (timeSec: number) => Promise<string>
): Promise<string[]> {
  const frames: string[] = [];
  for (const time of timestamps) {
    frames.push(await grab(time));
  }
  return frames;
}

export function withTimeout<T>(
  promise: Promise<T>,
  ms: number,
  message: string
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      }
    );
  });
}

// ---- DOM extraction (browser only) ----

function waitFor(video: HTMLVideoElement, event: string): Promise<void> {
  return withTimeout(
    new Promise<void>((resolve, reject) => {
      const onEvent = () => {
        cleanup();
        resolve();
      };
      const onError = () => {
        cleanup();
        reject(new Error("The video could not be decoded"));
      };
      const cleanup = () => {
        video.removeEventListener(event, onEvent);
        video.removeEventListener("error", onError);
      };
      video.addEventListener(event, onEvent);
      video.addEventListener("error", onError);
    }),
    SEEK_TIMEOUT_MS,
    `Timed out waiting for the video (${event})`
  );
}

async function seek(video: HTMLVideoElement, timeSec: number) {
  const seeked = waitFor(video, "seeked");
  video.currentTime = timeSec;
  await seeked;
}

// MediaRecorder WebM files report `duration = Infinity` until the browser has
// scanned to the end; seeking far past the end forces it to compute it.
async function resolveDuration(video: HTMLVideoElement): Promise<number> {
  if (Number.isFinite(video.duration)) return video.duration;
  await seek(video, Number.MAX_SAFE_INTEGER);
  const duration = video.duration;
  await seek(video, 0);
  return duration;
}

async function extract(src: string): Promise<string[]> {
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.preload = "auto";
  try {
    const loaded = waitFor(video, "loadeddata");
    video.src = src;
    await loaded;

    const duration = await resolveDuration(video);
    const { width, height } = scaledSize(video.videoWidth, video.videoHeight);
    if (width === 0 || height === 0) throw new Error("The video has no frames");

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Canvas 2D is not available");

    return await collectFrames(frameTimestamps(duration), async (time) => {
      await seek(video, time);
      context.drawImage(video, 0, 0, width, height);
      return canvas.toDataURL("image/jpeg", FRAME_JPEG_QUALITY);
    });
  } finally {
    video.removeAttribute("src");
    video.load();
  }
}

// Frames of a video (object or data URL) as JPEG data URLs. Rejects on any
// failure; callers treat that as "no frames" so the upload still goes through.
export function extractVideoFrames(src: string): Promise<string[]> {
  return withTimeout(
    extract(src),
    EXTRACTION_TIMEOUT_MS,
    "Timed out extracting video frames"
  );
}
