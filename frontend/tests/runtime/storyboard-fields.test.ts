import { describe, expect, it } from "vitest";
import { sourceSpan, textHash } from "../../src/app/storyboard-fields";

describe("storyboard source provenance", () => {
  it("uses Unicode code points and binds a selection to its exact text hash", async () => {
    const source = "雨😀\n灯亮";
    const hash = await textHash(source);
    expect(hash).toMatch(/^[0-9a-f]{64}$/);
    expect(sourceSpan(source, 3, 5, hash)).toEqual({
      sourceHash: hash,
      startCodePoint: 2,
      endCodePoint: 4,
    });
    expect(await textHash("雨😀\n灯灭")).not.toBe(hash);
    expect(sourceSpan(source, 3, 3, hash)).toBeNull();
  });
});
