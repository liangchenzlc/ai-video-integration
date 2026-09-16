import { describe, expect, it } from "vitest";
import { duplicateMusicClip } from "../../src/app/production-fields";

describe("explicit music loop", () => {
  it("duplicates the selected music clip beside itself without extending its source range", () => {
    const original = {
      id: crypto.randomUUID(),
      trackId: crypto.randomUUID(),
      mediaId: crypto.randomUUID(),
      startMs: 4000,
      inMs: 300,
      outMs: 2300,
      durationMs: 2000,
      linkedClipIds: [crypto.randomUUID()],
      keyframes: [],
    };
    const duplicated = duplicateMusicClip(original);
    expect(duplicated).toMatchObject({
      trackId: original.trackId,
      mediaId: original.mediaId,
      startMs: 6000,
      inMs: 300,
      outMs: 2300,
      durationMs: 2000,
      linkedClipIds: [],
    });
    expect(duplicated.id).not.toBe(original.id);
    expect(original.startMs).toBe(4000);
  });
});
