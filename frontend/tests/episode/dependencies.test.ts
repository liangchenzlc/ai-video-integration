import { describe, expect, it } from "vitest";

import {
  adoptFrame,
  editAsset,
  editScript,
  editShot,
  emptyWorkflow,
  stageStatus,
  type EpisodeWorkflow,
} from "../../src/features/projects/episode-workflow";

function workflow(): EpisodeWorkflow {
  const state = emptyWorkflow({ aspect: "16:9", style: "写实" });
  state.scriptDraft = "原剧本";
  state.scriptCandidates = [
    { id: "script-1", value: "原候选剧本", source: "demo" },
  ];
  state.assets = [
    {
      id: "asset-a",
      kind: "character",
      name: "阿遥",
      description: "红外套",
      linkedResourceId: null,
      imageCandidates: [],
      selectedImageId: null,
      review: "confirmed",
    },
  ];
  state.shots = [
    {
      id: "shot-a",
      title: "阿遥",
      description: "街口",
      action: "走近",
      dialogue: "你好",
      plannedMs: 3000,
      assetIds: ["asset-a"],
      review: "confirmed",
      firstFrames: [
        {
          id: "first-old",
          value: { kind: "demo-image", id: "demo-image-first-old" },
          source: "demo",
        },
      ],
      selectedFirstId: "first-old",
      endFrames: [],
      selectedEndId: null,
      videos: [
        {
          id: "video-a",
          value: { kind: "demo-motion", id: "demo-motion-a" },
          source: "demo",
        },
      ],
      selectedVideoId: "video-a",
      frameReview: "confirmed",
      videoReview: "confirmed",
    },
    {
      id: "shot-b",
      title: "路灯",
      description: "远景",
      action: "闪烁",
      dialogue: "",
      plannedMs: 2000,
      assetIds: [],
      review: "confirmed",
      firstFrames: [],
      selectedFirstId: null,
      endFrames: [],
      selectedEndId: null,
      videos: [
        {
          id: "video-b",
          value: { kind: "demo-motion", id: "demo-motion-b" },
          source: "demo",
        },
      ],
      selectedVideoId: "video-b",
      frameReview: "confirmed",
      videoReview: "confirmed",
    },
  ];
  state.gridBatches = [
    {
      id: "grid-a",
      sheet: { kind: "demo-image", id: "demo-image-sheet-a" },
      cells: [{ index: 0, shotId: "shot-a", ref: null, review: "confirmed" }],
    },
  ];
  state.reviews = {
    source: "confirmed",
    script: "confirmed",
    assets: "confirmed",
    storyboard: "confirmed",
    video: "confirmed",
  };
  return state;
}

describe("episode dependency invalidation", () => {
  it("preserves script candidates while a script edit makes existing downstream work stale", () => {
    const original = workflow();
    original.gridBatches[0]!.cells[0]!.ref = {
      kind: "demo-image",
      id: "demo-image-cell-script",
    };
    const edited = editScript(original, "改后的剧本");

    expect(edited.scriptDraft).toBe("改后的剧本");
    expect(edited.scriptCandidates).toEqual([
      { id: "script-1", value: "原候选剧本", source: "demo" },
    ]);
    expect(edited.assets[0]?.review).toBe("stale");
    expect(edited.shots[0]?.frameReview).toBe("stale");
    expect(edited.shots[0]?.videoReview).toBe("stale");
    expect(edited.gridBatches[0]?.cells[0]).toMatchObject({
      shotId: "shot-a",
      ref: { kind: "demo-image", id: "demo-image-cell-script" },
      review: "stale",
    });
    expect(stageStatus(edited, "assets")).toBe("stale");
    expect(stageStatus(edited, "storyboard")).toBe("stale");
    expect(stageStatus(edited, "video")).toBe("stale");
  });

  it("marks only shots linked to an edited asset stale", () => {
    const edited = editAsset(workflow(), "asset-a", { description: "蓝外套" });

    expect(edited.assets[0]).toMatchObject({
      name: "阿遥",
      description: "蓝外套",
      review: "review",
    });
    expect(edited.shots.find((shot) => shot.id === "shot-a")).toMatchObject({
      frameReview: "stale",
      videoReview: "stale",
    });
    expect(edited.shots.find((shot) => shot.id === "shot-b")?.videoReview).toBe(
      "confirmed",
    );
  });

  it("leaves an unrelated shot unchanged when another shot is edited", () => {
    const edited = editShot(workflow(), "shot-a", { action: "停下" });

    expect(edited.shots.find((shot) => shot.id === "shot-a")).toMatchObject({
      action: "停下",
      frameReview: "stale",
      videoReview: "stale",
    });
    expect(edited.shots.find((shot) => shot.id === "shot-b")).toEqual(
      workflow().shots[1],
    );
  });

  it("makes only the selected shot video stale when adopting a new first frame", () => {
    const original = workflow();
    original.shots[0]?.firstFrames.push({
      id: "first-new",
      value: { kind: "demo-image", id: "demo-image-first-new" },
      source: "demo",
    });
    const edited = adoptFrame(original, "shot-a", "first", "first-new");

    expect(edited.shots.find((shot) => shot.id === "shot-a")).toMatchObject({
      selectedFirstId: "first-new",
      frameReview: "confirmed",
      videoReview: "stale",
    });
    expect(edited.shots.find((shot) => shot.id === "shot-b")?.videoReview).toBe(
      "confirmed",
    );
  });

  it("does not turn an explicit unstarted review into confirmation from populated data", () => {
    const state = workflow();
    state.reviews.assets = "not_started";

    expect(stageStatus(state, "assets")).toBe("not_started");
  });

  it("preserves confirmed stage badges when an edited shot has no downstream result", () => {
    const state = workflow();
    const target = state.shots.find((shot) => shot.id === "shot-a")!;
    target.firstFrames = [];
    target.selectedFirstId = null;
    target.videos = [];
    target.selectedVideoId = null;
    const unrelated = state.shots.find((shot) => shot.id === "shot-b")!;
    unrelated.firstFrames = [
      {
        id: "first-b",
        value: { kind: "demo-image", id: "demo-image-first-b" },
        source: "demo",
      },
    ];

    const edited = editShot(state, "shot-a", { action: "回头" });

    expect(edited.reviews.storyboard).toBe("confirmed");
    expect(edited.reviews.video).toBe("confirmed");
    expect(edited.shots.find((shot) => shot.id === "shot-b")).toMatchObject({
      frameReview: "confirmed",
      videoReview: "confirmed",
    });
  });

  it("stales only grid cells bound to shots affected by an asset edit", () => {
    const state = workflow();
    state.gridBatches = [
      {
        id: "grid-a",
        sheet: { kind: "demo-image", id: "demo-image-sheet-a" },
        cells: [
          {
            index: 0,
            shotId: "shot-a",
            ref: { kind: "demo-image", id: "demo-image-cell-a" },
            review: "confirmed",
          },
          {
            index: 1,
            shotId: "shot-b",
            ref: { kind: "demo-image", id: "demo-image-cell-b" },
            review: "confirmed",
          },
        ],
      },
    ];

    const edited = editAsset(state, "asset-a", { description: "蓝外套" });

    expect(edited.gridBatches[0]?.cells.map((cell) => cell.review)).toEqual([
      "stale",
      "confirmed",
    ]);
    expect(edited.gridBatches[0]?.cells.map((cell) => cell.ref?.id)).toEqual([
      "demo-image-cell-a",
      "demo-image-cell-b",
    ]);
  });

  it("preserves unrelated confirmed stages when an asset has no downstream result", () => {
    const state = workflow();
    const target = state.shots.find((shot) => shot.id === "shot-a")!;
    target.firstFrames = [];
    target.videos = [];
    const unrelated = state.shots.find((shot) => shot.id === "shot-b")!;
    unrelated.firstFrames = [
      {
        id: "first-b",
        value: { kind: "demo-image", id: "demo-image-first-b" },
        source: "demo",
      },
    ];

    const edited = editAsset(state, "asset-a", { name: "阿遥" });

    expect(edited.reviews.storyboard).toBe("confirmed");
    expect(edited.reviews.video).toBe("confirmed");
  });

  it("preserves an unrelated confirmed video stage when adopting a frame", () => {
    const state = workflow();
    const target = state.shots.find((shot) => shot.id === "shot-a")!;
    target.videos = [];
    target.selectedVideoId = null;
    target.firstFrames.push({
      id: "first-new",
      value: { kind: "demo-image", id: "demo-image-first-new" },
      source: "demo",
    });

    const edited = adoptFrame(state, "shot-a", "first", "first-new");

    expect(edited.reviews.video).toBe("confirmed");
    expect(edited.shots.find((shot) => shot.id === "shot-b")?.videoReview).toBe(
      "confirmed",
    );
  });
});
