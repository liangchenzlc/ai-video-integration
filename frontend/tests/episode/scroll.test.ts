import { describe, expect, it } from "vitest";
import { activeStepIndex } from "../../src/pages/projects/episode-scroll";

describe("episode scroll navigation", () => {
  it("accepts fractional section positions after scrollIntoView rounding", () => {
    expect(activeStepIndex([-1390, -608, 100.28125, 800], 100, false)).toBe(2);
  });

  it("does not select a section that is still below the alignment tolerance", () => {
    expect(activeStepIndex([-1390, -608, 102, 800], 100, false)).toBe(1);
  });

  it("selects the last stage at the bottom during manual scrolling", () => {
    expect(activeStepIndex([-1390, -608, 150, 800], 100, true)).toBe(3);
  });
});
