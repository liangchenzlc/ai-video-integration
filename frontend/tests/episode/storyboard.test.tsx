import React, { type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import {
  adoptFrame,
  emptyWorkflow,
  readWorkflow,
  saveWorkflow,
} from "../../src/features/projects/episode-workflow";
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
    if (node.type === "button" && props.children === label)
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
    expect(
      renderToStaticMarkup(
        <StoryboardStage value={value} readOnly={false} onChange={() => {}} />,
      ),
    ).toContain("为新增镜头生成九宫格");
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
  it("renders both frame modes and all nine fixed grid cells", () => {
    const value = workflowWithShots();
    value.storyboardMode = "grid";
    const markup = renderToStaticMarkup(
      <StoryboardStage value={value} readOnly={false} onChange={() => {}} />,
    );

    expect(markup).toContain("首尾帧");
    expect(markup).toContain("九宫格分镜");
    expect(markup.match(/episode-grid-cell/g)).toHaveLength(9);
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

  it("does not emit a state change from read-only mode switches", () => {
    const onChange = vi.fn();
    const rendered = StoryboardStage({
      value: workflowWithShots(),
      readOnly: true,
      onChange,
    });
    const gridMode = button(rendered, "九宫格分镜");

    expect(gridMode.props.disabled).toBe(true);
    gridMode.props.onClick();
    expect(onChange).not.toHaveBeenCalled();
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

  it("labels the preview as static and calls unsupported tail frames review-only", () => {
    const frameMarkup = renderToStaticMarkup(
      <StoryboardStage
        value={workflowWithShots()}
        readOnly={false}
        onChange={() => {}}
      />,
    );
    const gridValue = workflowWithShots();
    gridValue.storyboardMode = "grid";
    const gridMarkup = renderToStaticMarkup(
      <StoryboardStage
        value={gridValue}
        readOnly={false}
        onChange={() => {}}
      />,
    );

    expect(frameMarkup).toContain("静态预览");
    expect(gridMarkup).toContain("仅供分镜参考");
    expect(frameMarkup).toContain("不支持尾帧的视频模型会将其视为仅供审核参考");
  });
});
