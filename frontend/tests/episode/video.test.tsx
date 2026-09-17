import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  emptyWorkflow,
  type ShotItem,
} from "../../src/features/projects/episode-workflow";
import {
  VideoStage,
  canGenerateVideo,
  failVideo,
  generateDemoVideo,
  confirmVideo,
} from "../../src/pages/projects/episode/VideoStage";

function stateWithShots() {
  const value = emptyWorkflow({ aspect: "16:9" });
  value.scriptDraft = "确认的剧本";
  value.approvedScript = {
    text: value.scriptDraft,
    aspect: value.aspect,
    style: value.style,
  };
  value.reviews.script = "confirmed";
  value.reviews.storyboard = "confirmed";
  value.shots = ["one", "two"].map((id) => ({
    id,
    title: `镜头 ${id}`,
    description: "雨夜街口",
    action: "人物走入画面",
    dialogue: "",
    plannedMs: 3000,
    assetIds: [],
    review: "confirmed" as const,
    firstFrames: [
      {
        id: `first-${id}`,
        source: "demo" as const,
        value: { kind: "demo-image" as const, id: `demo-image-${id}` },
        usableForVideo: true,
      },
    ],
    selectedFirstId: `first-${id}`,
    endFrames: [],
    selectedEndId: null,
    videos: [],
    selectedVideoId: null,
    frameReview: "confirmed" as const,
    videoReview: "not_started" as const,
  }));
  return value;
}

describe("per-shot video demo", () => {
  it("requires an adopted, confirmed, usable individual first frame", () => {
    const shot = stateWithShots().shots[0]!;
    expect(canGenerateVideo({ ...shot, selectedFirstId: null })).toEqual({
      ok: false,
      reason: "请先选定本镜可用的单幅分镜图",
    });
    expect(canGenerateVideo({ ...shot, frameReview: "review" })).toMatchObject({
      ok: false,
    });
    expect(
      canGenerateVideo({
        ...shot,
        firstFrames: shot.firstFrames.map((frame) => ({
          ...frame,
          usableForVideo: false,
        })),
      }),
    ).toMatchObject({ ok: false });
    expect(
      canGenerateVideo(
        {
          ...shot,
          firstFrames: [
            {
              ...shot.firstFrames[0]!,
              value: { kind: "demo-image", id: "demo-image-sheet" },
            },
          ],
        },
        [],
        ["demo-image-sheet"],
      ),
    ).toMatchObject({ ok: false });
    expect(canGenerateVideo(shot, [], ["demo-image-one"])).toMatchObject({
      ok: false,
    });
    expect(canGenerateVideo(shot)).toEqual({ ok: true });
  });

  it("requires a currently available image MIME for imported first frames", () => {
    const shot: ShotItem = stateWithShots().shots[0]!;
    shot.firstFrames[0] = {
      ...shot.firstFrames[0]!,
      value: {
        kind: "project-image",
        id: "22222222-2222-4222-8222-222222222222",
      },
      source: "import",
    };
    expect(canGenerateVideo(shot)).toMatchObject({ ok: false });
    expect(
      canGenerateVideo(shot, [
        {
          id: shot.firstFrames[0]!.value.id,
          mime: "video/mp4",
          availability: "available",
        },
      ]),
    ).toMatchObject({ ok: false });
    expect(
      canGenerateVideo(shot, [
        {
          id: shot.firstFrames[0]!.value.id,
          mime: "image/png",
          availability: "missing",
        },
      ]),
    ).toMatchObject({ ok: false });
    expect(
      canGenerateVideo(shot, [
        {
          id: shot.firstFrames[0]!.value.id,
          mime: "image/png",
          availability: "available",
        },
      ]),
    ).toEqual({ ok: true });
  });

  it("changes just one shot and retains outputs across a failed retry", () => {
    const start = stateWithShots();
    const first = generateDemoVideo(start, "one");
    expect(first.shots[1]).toBe(start.shots[1]);
    expect(first.shots[0]!.videos).toHaveLength(1);
    const failed = failVideo(first, "one");
    expect(failed.shots[0]!.videos).toEqual(first.shots[0]!.videos);
    const retry = generateDemoVideo(failed, "one");
    expect(retry.shots[0]!.videos).toHaveLength(2);
    expect(retry.shots[0]!.videos[0]).toEqual(first.shots[0]!.videos[0]);
    const confirmed = confirmVideo(
      retry,
      "one",
      retry.shots[0]!.selectedVideoId!,
    );
    expect(confirmed.shots[0]!.videoReview).toBe("confirmed");
    expect(confirmed.shots[1]).toBe(start.shots[1]);
  });

  it("labels demo motion as non-video and renders imported MP4 with controls", () => {
    const value = stateWithShots();
    value.shots[0] = generateDemoVideo(value, "one").shots[0]!;
    value.shots[1]!.videos = [
      {
        id: "imported",
        source: "import",
        value: {
          kind: "project-video",
          id: "33333333-3333-4333-8333-333333333333",
        },
      },
    ];
    value.shots[1]!.selectedVideoId = "imported";
    const markup = renderToStaticMarkup(
      <VideoStage
        value={value}
        readOnly={false}
        onChange={() => {}}
        projectId="11111111-1111-4111-8111-111111111111"
        mediaItems={[
          {
            id: "33333333-3333-4333-8333-333333333333",
            mime: "video/mp4",
            availability: "available",
          },
        ]}
      />,
    );
    expect(markup).toContain("交互演示");
    expect(markup).toContain("非视频文件");
    expect(markup).toContain("<video");
    expect(markup).toContain("controls");
  });

  it("explains empty and read-only states without showing export or an invented movie", () => {
    const value = emptyWorkflow({ aspect: "9:16" });
    const empty = renderToStaticMarkup(
      <VideoStage value={value} readOnly={true} onChange={() => {}} />,
    );
    expect(empty).toContain("先在分镜阶段建立镜头");
    expect(empty).toContain("只读模式");
    expect(empty).not.toContain("<video");
    expect(empty).not.toContain("导出");
  });

  it("does not claim five-stage completion if a shot frame is still unconfirmed", () => {
    const value = stateWithShots();
    value.reviews.script = "confirmed";
    value.shots.forEach((shot) => {
      shot.videoReview = "confirmed";
      shot.videos = [
        {
          id: `motion-${shot.id}`,
          source: "demo",
          value: { kind: "demo-motion", id: `demo-motion-${shot.id}` },
        },
      ];
      shot.selectedVideoId = `motion-${shot.id}`;
    });
    value.shots[0]!.frameReview = "review";
    const markup = renderToStaticMarkup(
      <VideoStage value={value} readOnly={false} onChange={() => {}} />,
    );
    expect(markup).not.toContain("演示流程完成，非成片");
  });

  it("requires a nonempty confirmed asset stage with adopted image candidates for completion", () => {
    const value = stateWithShots();
    value.reviews.script = "confirmed";
    value.reviews.assets = "confirmed";
    value.shots.forEach((shot) => {
      shot.videoReview = "confirmed";
      shot.videos = [
        {
          id: `video-${shot.id}`,
          source: "demo",
          value: { kind: "demo-motion", id: `demo-motion-${shot.id}` },
        },
      ];
      shot.selectedVideoId = `video-${shot.id}`;
    });
    const render = () =>
      renderToStaticMarkup(
        <VideoStage value={value} readOnly={false} onChange={() => {}} />,
      );
    expect(render()).not.toContain("演示流程完成，非成片");
    value.assets = [
      {
        id: "asset-one",
        kind: "prop",
        name: "道具",
        description: "手持道具",
        linkedResourceId: null,
        imageCandidates: [],
        selectedImageId: null,
        review: "confirmed",
      },
    ];
    expect(render()).not.toContain("演示流程完成，非成片");
    value.assets[0]!.imageCandidates = [
      {
        id: "asset-image",
        source: "demo",
        value: { kind: "demo-image", id: "demo-image-asset" },
      },
    ];
    value.assets[0]!.selectedImageId = "asset-image";
    expect(render()).toContain("演示流程完成，非成片");
  });
});
