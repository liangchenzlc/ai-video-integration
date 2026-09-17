import React, { type ReactNode } from "react";
import { Button } from "antd";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import {
  adoptFrame,
  editShot,
  editShotVideoPrompt,
  emptyWorkflow,
  readWorkflow,
  saveWorkflow,
} from "../../src/features/projects/episode-workflow";
import {
  sampleAssets,
  sampleShots,
} from "../../src/features/projects/episode-demo";
import {
  StoryboardStage,
  adoptGridCellAsFirstFrame,
  addStoryboardShot,
  removeStoryboardShot,
  createStoryboardGrids,
  reorderStoryboardShots,
} from "../../src/pages/projects/episode/StoryboardStage";

function workflowWithShots() {
  const value = emptyWorkflow({ aspect: "16:9", style: "写实" });
  value.shots = Array.from({ length: 9 }, (_, index) => ({
    id: `shot-${index + 1}`,
    title: `镜头 ${index + 1}`,
    description: "演示构图",
    action: "人物前进",
    dialogue: "",
    plannedMs: 3000,
    assetIds: [],
    review: "review" as const,
    firstFrames: [],
    selectedFirstId: null,
    endFrames: [],
    selectedEndId: null,
    videos: [],
    selectedVideoId: null,
    frameReview: "not_started" as const,
    videoReview: "not_started" as const,
  }));
  value.gridBatches = [
    {
      id: "grid-1",
      sheet: { kind: "demo-image", id: "demo-image-sheet-1" },
      cells: value.shots.map((shot, index) => ({
        index,
        shotId: shot.id,
        ref: {
          kind: "demo-image" as const,
          id: `demo-image-cell-${index + 1}`,
        },
        review: "confirmed" as const,
      })),
    },
  ];
  return value;
}

function button(
  node: ReactNode,
  label: string,
): { props: { disabled?: boolean; onClick: () => void } } {
  if (Array.isArray(node)) {
    for (const child of node) {
      try {
        return button(child, label);
      } catch {
        /* continue searching */
      }
    }
  } else if (React.isValidElement(node)) {
    const props = node.props as { children?: ReactNode };
    if (
      (node.type === "button" || node.type === Button) &&
      props.children === label
    )
      return node as ReturnType<typeof button>;
    if (props.children !== undefined) return button(props.children, label);
  }
  throw new Error(`Cannot find button ${label}`);
}

describe("storyboard stage", () => {
  it("adds unique stable-ID shots and deletes only the selected shot with grid bindings", () => {
    const value = workflowWithShots();
    const added = addStoryboardShot(value);
    expect(added.shots).toHaveLength(10);
    expect(added.shots[9]!.id).not.toBe(value.shots[0]!.id);
    expect(added.shots.slice(0, 9)).toEqual(value.shots);
    const removed = removeStoryboardShot(added, "shot-1");
    expect(removed.shots).toHaveLength(9);
    expect(
      removed.gridBatches[0]!.cells.some((cell) => cell.shotId === "shot-1"),
    ).toBe(false);
    expect(removed.shots[0]).toBe(value.shots[1]);
  });

  it("appends grid batches only for shots added after an existing batch", () => {
    const value = workflowWithShots();
    const existing = value.gridBatches[0]!;
    const appendedShots = Array.from({ length: 11 }, (_, index) => ({
      ...value.shots[0]!,
      id: `late-${index + 1}`,
      title: `新增 ${index + 1}`,
      firstFrames: [],
      selectedFirstId: null,
      videos: [],
      selectedVideoId: null,
      frameReview: "not_started" as const,
      videoReview: "not_started" as const,
    }));
    value.shots.push(...appendedShots);
    value.storyboardMode = "grid";
    const next = createStoryboardGrids(value);
    expect(next.gridBatches[0]).toBe(existing);
    expect(next.gridBatches).toHaveLength(3);
    expect(
      next.gridBatches.slice(1).map((batch) => batch.cells.length),
    ).toEqual([9, 2]);
    expect(
      next.gridBatches.flatMap((batch) =>
        batch.cells.map((cell) => cell.shotId),
      ),
    ).toEqual(value.shots.map((shot) => shot.id));
    expect(new Set(next.gridBatches.map((batch) => batch.id)).size).toBe(3);
    expect(createStoryboardGrids(next)).toBe(next);
    expect(
      renderToStaticMarkup(
        <StoryboardStage value={next} readOnly={false} onChange={() => {}} />,
      ),
    ).not.toContain("为新增镜头生成九宫格");
  });
  it("keeps all saved shots collapsed and replaces old frame/grid controls", () => {
    const value = workflowWithShots();
    value.storyboardMode = "grid";
    const markup = renderToStaticMarkup(
      <StoryboardStage value={value} readOnly={false} onChange={() => {}} />,
    );

    expect(markup.match(/<details class="storyboard-item"/g)).toHaveLength(9);
    expect(markup).not.toMatch(/<details[^>]*open/);
    expect(markup).not.toContain("首尾帧");
    expect(markup).not.toContain("九宫格分镜");
    expect(markup).toContain("生成分镜脚本");
  });

  it("does not adopt a whole grid sheet as a shot first frame", () => {
    const value = workflowWithShots();
    value.gridBatches[0]!.cells[0]!.ref = value.gridBatches[0]!.sheet;

    const next = adoptGridCellAsFirstFrame(value, "grid-1", 0, "shot-1");

    expect(next.shots[0]?.firstFrames).toEqual([]);
  });

  it("adopts a confirmed cell as a shot-owned usable first-frame candidate", () => {
    const value = workflowWithShots();

    const next = adoptGridCellAsFirstFrame(value, "grid-1", 0, "shot-1");

    expect(next.shots[0]).toMatchObject({
      selectedFirstId: "grid-grid-1-cell-0-demo-image-demo-image-cell-1",
      firstFrames: [
        {
          id: "grid-grid-1-cell-0-demo-image-demo-image-cell-1",
          value: { kind: "demo-image", id: "demo-image-cell-1" },
          usableForVideo: true,
        },
      ],
    });
  });

  it("adopts a same-ID demo crop without selecting a retained other-kind candidate", () => {
    const value = workflowWithShots();
    value.gridBatches[0]!.cells[0]!.ref = {
      kind: "demo-image",
      id: "shared-cell",
    };
    value.shots[0]!.firstFrames = [
      {
        id: "grid-grid-1-cell-0-shared-cell",
        source: "import",
        value: { kind: "project-image", id: "shared-cell" },
        usableForVideo: true,
      },
    ];

    const next = adoptGridCellAsFirstFrame(value, "grid-1", 0, "shot-1");

    expect(next.shots[0]).toMatchObject({
      selectedFirstId: "grid-grid-1-cell-0-demo-image-shared-cell",
      firstFrames: [
        { value: { kind: "project-image", id: "shared-cell" } },
        { value: { kind: "demo-image", id: "shared-cell" } },
      ],
    });
  });

  it("keeps a new confirmed cell crop instead of reselecting its older crop", () => {
    const value = workflowWithShots();
    const first = adoptGridCellAsFirstFrame(value, "grid-1", 0, "shot-1");
    first.gridBatches[0]!.cells[0]!.ref = {
      kind: "demo-image",
      id: "demo-image-cell-1-revised",
    };

    const next = adoptGridCellAsFirstFrame(first, "grid-1", 0, "shot-1");

    expect(next.shots[0]).toMatchObject({
      selectedFirstId:
        "grid-grid-1-cell-0-demo-image-demo-image-cell-1-revised",
      firstFrames: [
        { value: { id: "demo-image-cell-1" } },
        { value: { id: "demo-image-cell-1-revised" } },
      ],
    });
  });

  it("never adopts a project-image grid cell that is only for storyboard review", () => {
    const value = workflowWithShots();
    value.gridBatches[0]!.cells[0]!.ref = {
      kind: "project-image",
      id: "11111111-1111-4111-8111-111111111111",
    };

    const next = adoptGridCellAsFirstFrame(value, "grid-1", 0, "shot-1");

    expect(next.shots[0]?.firstFrames).toEqual([]);
  });

  it("blocks generation and prompt editing in read-only mode", () => {
    const onChange = vi.fn();
    const rendered = StoryboardStage({
      value: workflowWithShots(),
      readOnly: true,
      onChange,
    });
    const generate = button(rendered, "生成分镜脚本");

    expect(generate.props.disabled).toBe(true);
    generate.props.onClick();
    expect(onChange).not.toHaveBeenCalled();
    const markup = renderToStaticMarkup(rendered);
    expect(markup).toContain('readOnly=""');
    expect(markup).not.toContain("添加关联角色");
    expect(markup).not.toContain("取消关联");
  });

  it("keeps first- and end-frame adoption independent", () => {
    const value = workflowWithShots();
    value.shots[0]!.firstFrames = [
      {
        id: "first-1",
        source: "demo",
        value: { kind: "demo-image", id: "demo-image-first-1" },
      },
    ];
    value.shots[0]!.endFrames = [
      {
        id: "end-1",
        source: "demo",
        value: { kind: "demo-image", id: "demo-image-end-1" },
      },
    ];

    const next = adoptFrame(
      adoptFrame(value, "shot-1", "first", "first-1"),
      "shot-1",
      "end",
      "end-1",
    );

    expect(next.shots[0]).toMatchObject({
      selectedFirstId: "first-1",
      selectedEndId: "end-1",
    });
  });

  it("persists fixed grid bindings through a workflow reload", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, next: string) => values.set(key, next),
    };
    const value = workflowWithShots();

    const reordered = reorderStoryboardShots(
      value,
      [...value.shots].reverse().map((shot) => shot.id),
    );
    expect(saveWorkflow("project-1", "episode-1", reordered, storage)).toEqual({
      ok: true,
    });
    expect(
      readWorkflow("project-1", "episode-1", {}, storage).shots[0]!.id,
    ).toBe("shot-9");
    expect(
      readWorkflow(
        "project-1",
        "episode-1",
        { aspect: "16:9" },
        storage,
      ).gridBatches[0]?.cells.map((cell) => cell.shotId),
    ).toEqual([
      "shot-1",
      "shot-2",
      "shot-3",
      "shot-4",
      "shot-5",
      "shot-6",
      "shot-7",
      "shot-8",
      "shot-9",
    ]);
  });

  it("shows shared materials followed by a two-row image/video production table", () => {
    const value = workflowWithShots();
    value.shots = sampleShots("雨夜");
    const markup = renderToStaticMarkup(
      <StoryboardStage value={value} readOnly={false} onChange={() => {}} />,
    );
    expect(markup.indexOf('class="storyboard-materials"')).toBeLessThan(
      markup.indexOf('class="storyboard-prompt"'),
    );
    expect(markup.indexOf('class="storyboard-prompt"')).toBeLessThan(
      markup.indexOf('class="storyboard-output"'),
    );
    expect(markup.match(/aria-label="分镜图空白展示区"/g)).toHaveLength(2);
    expect(markup.match(/aria-label="分镜视频空白展示区"/g)).toHaveLength(2);
    expect(markup.match(/class="storyboard-materials-table"/g)).toHaveLength(2);
    expect(markup.match(/class="storyboard-production-table"/g)).toHaveLength(
      2,
    );
    expect(markup.match(/<tr>/g)).toHaveLength(6);
    expect(markup.indexOf("<h4>角色</h4>")).toBeLessThan(
      markup.indexOf("<h4>场景</h4>"),
    );
    expect(markup.indexOf("<h4>场景</h4>")).toBeLessThan(
      markup.indexOf("<h4>道具</h4>"),
    );
    expect(markup).toContain("ant-btn-primary");
    expect(markup).not.toContain("<h3>关联素材</h3>");
    expect(markup).toContain("生成分镜图");
    expect(markup).toContain("生成视频");
    expect(markup).toContain("视频提示词");
    expect(markup).toContain("雨巷来客");
    expect(markup).toContain("门前迟疑");
  });

  it("generates exactly two collapsed examples linked only to existing assets", () => {
    const value = emptyWorkflow({});
    value.scriptDraft = "雨夜";
    value.assets = sampleAssets();
    const onChange = vi.fn();
    const generate = button(
      StoryboardStage({ value, readOnly: false, onChange }),
      "生成分镜脚本",
    );
    generate.props.onClick();
    const next = onChange.mock.calls[0]![0];
    expect(next.shots).toHaveLength(2);
    expect(next.shots[0].assetIds).toEqual([
      "demo-asset-2",
      "demo-asset-1",
      "demo-asset-3",
    ]);
    expect(next.shots[0].imagePrompt).toContain("林小雨");
    expect(next.assets).toEqual(value.assets);
    expect(
      next.shots.every(
        (shot: { firstFrames: unknown[] }) => shot.firstFrames.length === 0,
      ),
    ).toBe(true);
  });

  it("persists prompt edits and associations without changing other shots", () => {
    const value = workflowWithShots();
    const next = editShot(value, "shot-1", {
      imagePrompt: "更新的图片提示词",
      assetIds: ["asset-1"],
    });
    const withVideoPrompt = editShotVideoPrompt(
      next,
      "shot-1",
      "镜头缓慢向前推进",
    );
    expect(next.shots[1]).toBe(value.shots[1]);
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, text: string) => {
        values.set(key, text);
      },
    };
    expect(saveWorkflow("p", "e", withVideoPrompt, storage)).toEqual({
      ok: true,
    });
    expect(readWorkflow("p", "e", {}, storage).shots[0]).toMatchObject({
      imagePrompt: "更新的图片提示词",
      videoPrompt: "镜头缓慢向前推进",
      assetIds: ["asset-1"],
    });
    expect(
      readWorkflow("p", "e", {}, storage).shots[1]?.imagePrompt,
    ).toBeUndefined();
  });

  it("video prompt edits invalidate only the matching video and preserve source images", () => {
    const value = workflowWithShots();
    const shot = value.shots[0]!;
    shot.review = "confirmed";
    shot.frameReview = "confirmed";
    shot.firstFrameReview = "confirmed";
    shot.firstFrames = [
      {
        id: "frame",
        source: "demo",
        value: { kind: "demo-image", id: "frame" },
      },
    ];
    shot.selectedFirstId = "frame";
    shot.videos = [
      {
        id: "video",
        source: "demo",
        value: { kind: "demo-motion", id: "video" },
      },
    ];
    shot.selectedVideoId = "video";
    shot.videoReview = "confirmed";
    value.reviews.storyboard = "confirmed";
    value.reviews.video = "confirmed";
    const next = editShotVideoPrompt(value, shot.id, "缓慢推近");
    expect(next.shots[0]).toMatchObject({
      videoPrompt: "缓慢推近",
      review: "confirmed",
      frameReview: "confirmed",
      firstFrameReview: "confirmed",
      selectedFirstId: "frame",
      selectedVideoId: "video",
      videoReview: "stale",
    });
    expect(next.shots[0]!.firstFrames).toBe(shot.firstFrames);
    expect(next.shots[0]!.videos).toBe(shot.videos);
    expect(next.shots[1]).toBe(value.shots[1]);
    expect(next.gridBatches).toBe(value.gridBatches);
    expect(next.reviews.storyboard).toBe("confirmed");
    expect(next.reviews.video).toBe("stale");
  });
});
