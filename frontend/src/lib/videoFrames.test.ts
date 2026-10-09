import {
  collectFrames,
  frameTimestamps,
  LAST_FRAME_OFFSET_SEC,
  scaledSize,
  withTimeout,
} from "./videoFrames";

describe("frameTimestamps", () => {
  it("samples one frame per second plus the last frame", () => {
    expect(frameTimestamps(5.5)).toEqual([0, 1, 2, 3, 4, 5, 5.5 - LAST_FRAME_OFFSET_SEC]);
  });

  it("does not add a whole-second frame right before the last frame", () => {
    // last = 4.9: 0..4 then 4.9 (no 5, which is past the end)
    expect(frameTimestamps(5)).toEqual([0, 1, 2, 3, 4, 4.9]);
    // last = 5.0 coincides with the 5 s sample, so it is only listed once
    expect(frameTimestamps(5.1)).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it("always includes the first and last frame and never exceeds max", () => {
    const times = frameTimestamps(60);
    expect(times).toHaveLength(20);
    expect(times[0]).toBe(0);
    expect(times[times.length - 1]).toBeCloseTo(60 - LAST_FRAME_OFFSET_SEC, 3);
    for (let i = 1; i < times.length; i++) {
      expect(times[i]).toBeGreaterThan(times[i - 1]);
    }
  });

  it("caps exactly at max when the 1 fps samples just exceed it", () => {
    const times = frameTimestamps(20.5);
    expect(times).toHaveLength(20);
    expect(times[0]).toBe(0);
    expect(times[19]).toBeCloseTo(20.4, 3);
  });

  it("honours custom fps / max", () => {
    expect(frameTimestamps(2.1, { fps: 2, max: 20 })).toEqual([0, 0.5, 1, 1.5, 2]);
    expect(frameTimestamps(100, { fps: 1, max: 3 })).toEqual([0, 49.95, 99.9]);
  });

  it("handles very short, zero and invalid durations", () => {
    expect(frameTimestamps(0.3)).toEqual([0, 0.2]);
    expect(frameTimestamps(0.05)).toEqual([0]);
    expect(frameTimestamps(0)).toEqual([0]);
    expect(frameTimestamps(Number.NaN)).toEqual([0]);
    expect(frameTimestamps(Number.POSITIVE_INFINITY)).toEqual([0]);
    expect(frameTimestamps(-3)).toEqual([0]);
  });

  it("returns a single frame when max is 1", () => {
    expect(frameTimestamps(10, { fps: 1, max: 1 })).toEqual([0]);
  });
});

describe("scaledSize", () => {
  it("scales the longest side down to 1280 keeping the aspect ratio", () => {
    expect(scaledSize(1920, 1080)).toEqual({ width: 1280, height: 720 });
    expect(scaledSize(1080, 1920)).toEqual({ width: 720, height: 1280 });
    expect(scaledSize(2560, 1600)).toEqual({ width: 1280, height: 800 });
  });

  it("never upscales", () => {
    expect(scaledSize(800, 600)).toEqual({ width: 800, height: 600 });
    expect(scaledSize(1280, 400)).toEqual({ width: 1280, height: 400 });
  });

  it("supports a custom max side and keeps at least 1 px", () => {
    expect(scaledSize(1000, 500, 100)).toEqual({ width: 100, height: 50 });
    expect(scaledSize(10000, 1, 100)).toEqual({ width: 100, height: 1 });
  });

  it("returns zero size for unknown dimensions", () => {
    expect(scaledSize(0, 0)).toEqual({ width: 0, height: 0 });
    expect(scaledSize(Number.NaN, 10)).toEqual({ width: 0, height: 0 });
  });
});

describe("collectFrames", () => {
  it("grabs every timestamp in order", async () => {
    const seen: number[] = [];
    const frames = await collectFrames([0, 1, 2], async (t) => {
      seen.push(t);
      return `frame-${t}`;
    });
    expect(seen).toEqual([0, 1, 2]);
    expect(frames).toEqual(["frame-0", "frame-1", "frame-2"]);
  });

  it("propagates a grab failure", async () => {
    await expect(
      collectFrames([0, 1], async (t) => {
        if (t === 1) throw new Error("decode failed");
        return "ok";
      })
    ).rejects.toThrow("decode failed");
  });
});

describe("withTimeout", () => {
  it("resolves with the promise's value when it is fast enough", async () => {
    await expect(withTimeout(Promise.resolve(3), 1000, "slow")).resolves.toBe(3);
  });

  it("rejects when the promise takes too long", async () => {
    await expect(
      withTimeout(new Promise(() => undefined), 5, "too slow")
    ).rejects.toThrow("too slow");
  });
});
