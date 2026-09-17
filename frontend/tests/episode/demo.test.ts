import { describe, expect, it } from "vitest";

import {
  DEMO_MODELS,
  sampleAssets,
  sampleImage,
  sampleMotion,
  sampleScript,
  sampleShots,
} from "../../src/features/projects/episode-demo";

describe("episode demo fixtures", () => {
  it("returns no script candidate for blank source text", () => {
    expect(sampleScript("  ")).toBeNull();
  });

  it("returns the same visibly labeled scaffold for repeated source text", () => {
    expect(sampleScript("雨夜有人借灯")).toEqual(sampleScript("雨夜有人借灯"));
    expect(sampleScript("雨夜有人借灯")?.value).toContain("演示剧本草稿");
  });

  it("uses generic asset names that require user correction", () => {
    expect(sampleAssets().map((asset) => asset.name)).toEqual([
      "角色 A",
      "场景 A",
      "道具 A",
    ]);
  });

  it("generates distinct stable shot IDs for the same script fixture", () => {
    const shots = sampleShots("演示剧本草稿：雨夜有人借灯");

    expect(shots.map((shot) => shot.id)).toEqual(
      sampleShots("演示剧本草稿：雨夜有人借灯").map((shot) => shot.id),
    );
    expect(new Set(shots.map((shot) => shot.id)).size).toBe(shots.length);
  });

  it("returns only demo media references for generated image and motion", () => {
    expect(sampleImage("s1").kind).toBe("demo-image");
    expect(sampleMotion("s1").kind).toBe("demo-motion");
  });

  it("offers two labeled demo choices for every workflow phase", () => {
    expect(
      Object.values(DEMO_MODELS).every((choices) => choices.length === 2),
    ).toBe(true);
    expect(DEMO_MODELS.video.map((choice) => choice.label)).toEqual([
      "演示·图生视频模型 A",
      "演示·图生视频模型 B",
    ]);
  });
});
