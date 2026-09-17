import React, { type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { emptyWorkflow } from "../../src/features/projects/episode-workflow";
import {
  StageNav,
  visibleEpisodeStage,
} from "../../src/pages/projects/episode/StageNav";
import { SourceStage } from "../../src/pages/projects/episode/SourceStage";
import { ScriptStage } from "../../src/pages/projects/episode/ScriptStage";

const state = emptyWorkflow({ aspect: "16:9", style: "写实" });

function control(
  node: ReactNode,
  tag: string,
  value: string,
): {
  props: { onChange: (event: { target: { value: string } }) => void };
} {
  if (Array.isArray(node)) {
    for (const child of node) {
      try {
        return control(child, tag, value);
      } catch {
        /* look at the next child */
      }
    }
  } else if (React.isValidElement(node)) {
    const props = node.props as { value?: string; children?: ReactNode };
    if (node.type === tag && props.value === value)
      return node as ReturnType<typeof control>;
    if (props.children !== undefined)
      return control(props.children, tag, value);
  }
  throw new Error(`Cannot find ${tag} with value ${value}`);
}

function reviewedState() {
  const workflow = emptyWorkflow({ aspect: "16:9", style: "写实" });
  workflow.novel = "旧原文";
  workflow.scriptDraft = "当前剧本";
  workflow.scriptCandidates = [
    { id: "draft-1", value: "候选", source: "demo" },
  ];
  workflow.approvedScript = {
    text: "已确认剧本",
    aspect: "16:9",
    style: "写实",
  };
  workflow.reviews = {
    source: "confirmed",
    script: "confirmed",
    assets: "confirmed",
    storyboard: "confirmed",
    video: "confirmed",
  };
  workflow.assets = [
    {
      id: "asset-1",
      kind: "character",
      name: "阿遥",
      description: "雨衣",
      linkedResourceId: null,
      imageCandidates: [
        {
          id: "image-1",
          source: "demo",
          value: { kind: "demo-image", id: "demo-image-asset" },
        },
      ],
      selectedImageId: "image-1",
      review: "confirmed",
    },
    {
      id: "asset-2",
      kind: "prop",
      name: "灯",
      description: "手提灯",
      linkedResourceId: null,
      imageCandidates: [],
      selectedImageId: null,
      review: "confirmed",
    },
  ];
  workflow.shots = [
    {
      id: "shot-1",
      title: "街口",
      description: "相遇",
      action: "停下",
      dialogue: "",
      plannedMs: 1000,
      assetIds: ["asset-1"],
      review: "confirmed",
      firstFrames: [
        {
          id: "frame-1",
          source: "demo",
          value: { kind: "demo-image", id: "demo-image-frame" },
        },
      ],
      selectedFirstId: "frame-1",
      endFrames: [],
      selectedEndId: null,
      videos: [
        {
          id: "video-1",
          source: "demo",
          value: { kind: "demo-motion", id: "demo-motion-shot" },
        },
      ],
      selectedVideoId: "video-1",
      frameReview: "confirmed",
      videoReview: "confirmed",
    },
    {
      id: "shot-2",
      title: "街尾",
      description: "独行",
      action: "行走",
      dialogue: "",
      plannedMs: 1000,
      assetIds: ["asset-2"],
      review: "confirmed",
      firstFrames: [
        {
          id: "frame-2",
          source: "demo",
          value: { kind: "demo-image", id: "demo-image-frame-2" },
        },
      ],
      selectedFirstId: "frame-2",
      endFrames: [],
      selectedEndId: null,
      videos: [],
      selectedVideoId: null,
      frameReview: "confirmed",
      videoReview: "not_started",
    },
  ];
  workflow.gridBatches = [
    {
      id: "grid-1",
      sheet: { kind: "demo-image", id: "demo-image-sheet" },
      cells: [
        {
          index: 0,
          shotId: "shot-1",
          ref: { kind: "demo-image", id: "demo-image-cell-1" },
          review: "confirmed",
        },
        {
          index: 1,
          shotId: "shot-2",
          ref: { kind: "demo-image", id: "demo-image-cell-2" },
          review: "confirmed",
        },
        { index: 2, shotId: "shot-3", ref: null, review: "not_started" },
      ],
    },
  ];
  return workflow;
}

describe("episode stages", () => {
  it("omits the saved-script viewer without changing the saved snapshot", () => {
    const value = reviewedState();
    const snapshot = value.approvedScript;
    const markup = renderToStaticMarkup(
      <ScriptStage value={value} readOnly={false} onChange={() => {}} />,
    );
    expect(markup).not.toContain("查看上次保存的剧本版本");
    expect(markup).not.toContain("episode-script-snapshot");
    expect(markup).toContain("本集剧本");
    expect(value.approvedScript).toBe(snapshot);
  });
  it("offers four stages with image and video production combined", () => {
    const markup = renderToStaticMarkup(
      <StageNav active="source" onSelect={() => {}} />,
    );
    expect(markup.match(/episode-stage-link/g)).toHaveLength(4);
    expect(markup).toContain("小说与剧本生成");
    expect(markup).toContain("分镜制作");
    expect(markup).not.toContain("分镜视频");
    expect(visibleEpisodeStage("video")).toBe("storyboard");
    expect(markup).not.toContain("未开始");
    expect(markup).not.toContain("<small>");
  });

  it("keeps source text and demo model choice visible", () => {
    const markup = renderToStaticMarkup(
      <SourceStage value={state} readOnly={false} onChange={() => {}} />,
    );
    expect(markup).toContain("本集小说");
    expect(markup).toContain("剧本生成模型");
    expect(markup).toContain("演示生成剧本");
  });

  it("allows aspect and style review without adding resolution", () => {
    const markup = renderToStaticMarkup(
      <ScriptStage value={state} readOnly={false} onChange={() => {}} />,
    );
    expect(markup).toContain("画幅比例");
    expect(markup).toContain("视觉风格");
    expect(markup).toContain("素材分析模型");
    expect(markup).not.toContain("清晰度");
  });

  it("does not offer mutation actions in read-only mode", () => {
    const source = renderToStaticMarkup(
      <SourceStage value={state} readOnly onChange={() => {}} />,
    );
    const script = renderToStaticMarkup(
      <ScriptStage value={state} readOnly onChange={() => {}} />,
    );
    expect(source).toMatch(/<button[^>]*disabled=""[^>]*><span>演示生成剧本/);
    expect(script).toMatch(
      /<button[^>]*disabled=""[^>]*><span>一键生成文本框架/,
    );
    expect(source).toContain("ant-btn-primary");
    expect(script).toContain("ant-btn-primary");
  });

  it("selects a candidate only on an explicit choice and keeps its history", () => {
    const onChange = vi.fn();
    const candidate = {
      id: "draft-1",
      value: "演示剧本候选",
      source: "demo" as const,
    };
    const withCandidate = {
      ...state,
      scriptDraft: "我写的剧本",
      scriptCandidates: [candidate],
    };
    const rendered = SourceStage({
      value: withCandidate,
      readOnly: false,
      onChange,
    });
    expect(onChange).not.toHaveBeenCalled();
    vi.stubGlobal("confirm", () => true);
    // The choice is a real button in the component, not an automatic effect of rendering.
    const candidateList = rendered.props.children[4];
    const choose = candidateList.props.children[1][0].props.children[1];
    choose.props.onClick();
    vi.unstubAllGlobals();
    expect(onChange).toHaveBeenCalledOnce();
    expect(onChange.mock.calls[0][0]).toMatchObject({
      scriptDraft: "演示剧本候选",
      scriptCandidates: [candidate],
    });
  });

  it("novel revision marks existing dependent results stale without discarding them", () => {
    const previous = reviewedState();
    const onChange = vi.fn();
    control(
      SourceStage({ value: previous, readOnly: false, onChange }),
      "textarea",
      "旧原文",
    ).props.onChange({ target: { value: "新原文" } });
    const next = onChange.mock.calls[0][0];
    expect(next.novel).toBe("新原文");
    expect(next.scriptCandidates).toEqual(previous.scriptCandidates);
    expect(next.approvedScript).toEqual(previous.approvedScript);
    expect(next.assets[0].imageCandidates).toEqual(
      previous.assets[0].imageCandidates,
    );
    expect(next.shots[0].videos).toEqual(previous.shots[0].videos);
    expect(next.reviews).toMatchObject({
      source: "review",
      script: "stale",
      assets: "stale",
      storyboard: "stale",
      video: "stale",
    });
    expect(
      next.gridBatches[0].cells.map((cell: { review: string }) => cell.review),
    ).toEqual(["stale", "stale", "not_started"]);
  });

  it("requires script re-confirmation when source changes but approved text still equals draft", () => {
    const previous = reviewedState();
    previous.approvedScript = {
      text: previous.scriptDraft,
      aspect: previous.aspect,
      style: previous.style,
    };
    const onChange = vi.fn();
    control(
      SourceStage({ value: previous, readOnly: false, onChange }),
      "textarea",
      "旧原文",
    ).props.onChange({ target: { value: "新原文" } });
    const next = onChange.mock.calls[0][0];
    expect(next.approvedScript).toEqual(previous.approvedScript);
    expect(next.scriptCandidates).toEqual(previous.scriptCandidates);
    expect(next.reviews.script).toBe("stale");

    const markup = renderToStaticMarkup(
      <ScriptStage value={next} readOnly={false} onChange={() => {}} />,
    );
    expect(markup).toContain("剧本变更待更新");
    expect(markup).not.toContain("当前剧本版本已保存");
    expect(markup).toContain("一键生成文本框架");
    expect(markup).not.toContain("确认剧本</button>");
  });

  it.each(["aspect", "style"] as const)(
    "%s revision stales existing grid cells but keeps mappings and candidates",
    (field) => {
      const previous = reviewedState();
      const onChange = vi.fn();
      const element = ScriptStage({
        value: previous,
        readOnly: false,
        onChange,
      });
      control(
        element,
        field === "aspect" ? "select" : "input",
        field === "aspect" ? "16:9" : "写实",
      ).props.onChange({
        target: { value: field === "aspect" ? "9:16" : "水墨" },
      });
      const next = onChange.mock.calls[0][0];
      expect(next.gridBatches[0].sheet).toEqual(previous.gridBatches[0].sheet);
      expect(
        next.gridBatches[0].cells.map(
          (cell: { shotId: string; ref: unknown; review: string }) => [
            cell.shotId,
            cell.ref,
            cell.review,
          ],
        ),
      ).toEqual([
        ["shot-1", previous.gridBatches[0].cells[0].ref, "stale"],
        ["shot-2", previous.gridBatches[0].cells[1].ref, "stale"],
        ["shot-3", null, "not_started"],
      ]);
      expect(next.shots[0].videos).toEqual(previous.shots[0].videos);
      expect(next.reviews.storyboard).toBe("stale");
    },
  );

  it.each(["name", "description"] as const)(
    "asset %s edit only stales its referencing shots",
    (field) => {
      const previous = reviewedState();
      const onChange = vi.fn();
      const element = ScriptStage({
        value: previous,
        readOnly: false,
        onChange,
      });
      control(
        element,
        field === "name" ? "input" : "textarea",
        field === "name" ? "阿遥" : "雨衣",
      ).props.onChange({ target: { value: "更新后" } });
      const next = onChange.mock.calls[0][0];
      expect(next.assets[0][field]).toBe("更新后");
      expect(next.assets[0].imageCandidates).toEqual(
        previous.assets[0].imageCandidates,
      );
      expect(next.assets[1]).toEqual(previous.assets[1]);
      expect(next.shots[0]).toMatchObject({
        frameReview: "stale",
        videoReview: "stale",
      });
      expect(next.shots[0].videos).toEqual(previous.shots[0].videos);
      expect(next.shots[1]).toEqual(previous.shots[1]);
      expect(
        next.gridBatches[0].cells.map(
          (cell: { review: string }) => cell.review,
        ),
      ).toEqual(["stale", "confirmed", "not_started"]);
    },
  );
});
