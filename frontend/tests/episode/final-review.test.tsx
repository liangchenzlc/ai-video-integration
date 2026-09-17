import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import * as workflow from "../../src/features/projects/episode-workflow";
import {
  sampleShots,
  sampleAssets,
} from "../../src/features/projects/episode-demo";
import { shareAsset } from "../../src/pages/projects/episode/AssetsStage";
import * as storyboard from "../../src/pages/projects/episode/StoryboardStage";
import {
  VideoStage,
  canGenerateVideo,
} from "../../src/pages/projects/episode/VideoStage";
import { ImagePreview } from "../../src/pages/projects/episode/ImagePreview";
import { hasAvailableMedia } from "../../src/features/projects/episode-media";
import type { ListedMedia } from "../../src/features/projects/episode-media";

export function approvedState() {
  const value = workflow.emptyWorkflow({});
  value.scriptDraft = "雨夜相遇";
  value.approvedScript = {
    text: value.scriptDraft,
    aspect: value.aspect,
    style: value.style,
  };
  value.reviews = {
    source: "confirmed",
    script: "confirmed",
    assets: "confirmed",
    storyboard: "confirmed",
    video: "confirmed",
  };
  value.assets = sampleAssets()
    .slice(0, 1)
    .map((asset) => ({
      ...asset,
      review: "confirmed",
      selectedImageId: "asset-image",
      imageCandidates: [
        {
          id: "asset-image",
          source: "demo",
          value: { kind: "demo-image", id: "demo-image-asset" },
        },
      ],
    }));
  value.shots = sampleShots(value.scriptDraft).map((shot) => ({
    ...shot,
    review: "confirmed",
    assetIds: [value.assets[0]!.id],
    frameReview: "confirmed",
    selectedFirstId: "first",
    firstFrames: [
      {
        id: "first",
        source: "demo",
        value: { kind: "demo-image", id: `demo-image-${shot.id}` },
        usableForVideo: true,
      },
    ],
    selectedVideoId: "video",
    videos: [
      {
        id: "video",
        source: "demo",
        value: { kind: "demo-motion", id: `demo-motion-${shot.id}` },
      },
    ],
    videoReview: "confirmed",
  }));
  return value;
}
const projectId = "11111111-1111-4111-8111-111111111111";
const mediaId = "22222222-2222-4222-8222-222222222222";
const renderVideo = (
  value: workflow.EpisodeWorkflow,
  mediaItems: ListedMedia[] = [],
) =>
  renderToStaticMarkup(
    <VideoStage
      value={value}
      readOnly={false}
      onChange={() => {}}
      projectId={projectId}
      mediaItems={mediaItems}
    />,
  );

describe("final review boundaries", () => {
  it("does not share imported images without a current available image record", () => {
    const asset = approvedState().assets[0]!;
    asset.imageCandidates[0]!.value = { kind: "project-image", id: mediaId };
    expect(shareAsset(asset, []).ok).toBe(false);
  });
  it("does not report imported-media completion while the media service is unavailable", () => {
    const value = approvedState();
    value.shots[0]!.firstFrames[0]!.value = {
      kind: "project-image",
      id: mediaId,
    };
    expect(
      renderToStaticMarkup(
        <VideoStage
          value={value}
          readOnly={false}
          ready={false}
          onChange={() => {}}
          projectId={projectId}
          mediaItems={[
            { id: mediaId, mime: "image/png", availability: "available" },
          ]}
        />,
      ),
    ).not.toContain("演示流程完成，非成片");
  });
  it("reuses the linked resource for repeat and edited re-share", () => {
    const asset = approvedState().assets[0]!;
    const first = shareAsset(asset, []);
    expect(first.ok).toBe(true);
    if (!first.ok) return;
    const linked = { ...asset, linkedResourceId: first.linkedResourceId };
    const again = shareAsset(linked, first.resources);
    expect(again).toMatchObject({
      ok: true,
      linkedResourceId: first.linkedResourceId,
      resources: [first.resources[0]],
    });
    const edited = shareAsset(
      { ...linked, name: "新名字", description: "已重新核对的描述" },
      first.resources,
    );
    expect(edited).toMatchObject({
      ok: true,
      linkedResourceId: first.linkedResourceId,
      resources: [{ name: "新名字", description: "已重新核对的描述" }],
    });
  });

  it.each(["review", "stale"] as const)(
    "refuses %s asset sharing and blank confirmed metadata",
    (review) => {
      const asset = approvedState().assets[0]!;
      expect(shareAsset({ ...asset, review }, []).ok).toBe(false);
      expect(shareAsset({ ...asset, name: " " }, []).ok).toBe(false);
      expect(shareAsset({ ...asset, selectedImageId: null }, []).ok).toBe(
        false,
      );
    },
  );

  it("keeps stale first-frame review after adopting a new tail frame", () => {
    let value = workflow.editShot(
      approvedState(),
      approvedState().shots[0]!.id,
      { action: "新动作" },
    );
    const shot = value.shots[0]!;
    shot.endFrames = [
      {
        id: "tail",
        source: "demo",
        value: { kind: "demo-image", id: "demo-image-tail" },
        usableForVideo: true,
      },
    ];
    value = storyboard.confirmShotText(value, shot.id);
    value = workflow.adoptFrame(value, shot.id, "end", "tail");
    expect(canGenerateVideo(value.shots[0]!)).toMatchObject({ ok: false });
    expect(value.shots[0]).toMatchObject({
      firstFrameReview: "stale",
      endFrameReview: "confirmed",
    });
  });

  it("migrates old V2 frame reviews without losing old results", () => {
    const old = approvedState();
    const loaded = workflow.readWorkflow(
      "project",
      "episode",
      {},
      { getItem: () => JSON.stringify(old) },
    );
    expect(loaded.shots[0]).toMatchObject({
      firstFrameReview: "confirmed",
      endFrameReview: "not_started",
    });
    expect(loaded.shots[0]!.videos).toEqual(old.shots[0]!.videos);
  });

  it("blocks unreviewed shot text, stale script, and missing referenced asset image", () => {
    const value = approvedState();
    expect(renderVideo(value)).toContain("演示流程完成，非成片");
    value.shots[0]!.review = "review";
    expect(canGenerateVideo(value.shots[0]!)).toMatchObject({ ok: false });
    expect(renderVideo(value)).not.toContain("演示流程完成，非成片");
    value.shots[0]!.review = "confirmed";
    value.scriptDraft = "未确认的新剧本";
    expect(renderVideo(value)).not.toContain("演示流程完成，非成片");
    value.scriptDraft = value.approvedScript!.text;
    value.assets[0]!.selectedImageId = null;
    const markup = renderVideo(value);
    expect(markup).toContain("素材图片");
    expect(markup).not.toContain("演示流程完成，非成片");
  });

  it.each(["first", "video"] as const)(
    "rejects missing or wrong-MIME selected imported %s even after completion",
    (role) => {
      const value = approvedState();
      const candidate =
        role === "first"
          ? value.shots[0]!.firstFrames[0]!
          : value.shots[0]!.videos[0]!;
      candidate.value = {
        kind: role === "first" ? "project-image" : "project-video",
        id: mediaId,
      };
      expect(
        renderVideo(value, [
          {
            id: mediaId,
            mime: role === "first" ? "image/png" : "video/mp4",
            availability: "available",
          },
        ]),
      ).toContain("演示流程完成，非成片");
      expect(renderVideo(value)).not.toContain("演示流程完成，非成片");
      expect(
        renderVideo(value, [
          { id: mediaId, mime: "audio/wav", availability: "available" },
        ]),
      ).not.toContain("演示流程完成，非成片");
    },
  );

  it("keeps existing asset and frame previews in the combined production table", () => {
    const value = approvedState();
    const frames = renderToStaticMarkup(
      <storyboard.StoryboardStage
        value={value}
        readOnly={false}
        onChange={() => {}}
      />,
    );
    expect(frames).toContain("林小雨 · 演示参考");
    expect(frames).toContain("雨巷来客分镜图");
    expect(frames).toContain("门前迟疑分镜图");
    const grid = storyboard.createStoryboardGrids(value);
    grid.storyboardMode = "grid";
    const markup = renderToStaticMarkup(
      <storyboard.StoryboardStage
        value={grid}
        readOnly={false}
        onChange={() => {}}
      />,
    );
    expect(markup).not.toContain("整张九宫格演示参考");
    expect(markup).toContain("storyboard-production-table");
  });

  it("replaces shot and stage confirmation with prompt editing", () => {
    const value = approvedState();
    value.shots[0]!.review = "stale";
    const markup = renderToStaticMarkup(
      <storyboard.StoryboardStage
        value={value}
        readOnly={false}
        onChange={() => {}}
      />,
    );
    expect(markup).not.toContain("确认本镜文字");
    expect(markup).not.toContain("确认分镜阶段");
    expect(markup).toContain("图片提示词");
    expect(markup).not.toMatch(/<details[^>]*open/);
  });

  it("adds typed stable assets and removes only their own dependencies", () => {
    let value = approvedState();
    value.shots[1]!.assetIds = [];
    const unaffected = value.shots[1];
    value = workflow.addAsset(value, "prop");
    expect(value.assets[1]).toMatchObject({ kind: "prop", review: "review" });
    expect(value.assets[1]!.id).not.toBe(value.assets[0]!.id);
    const removed = workflow.removeAsset(value, value.assets[0]!.id);
    expect(removed.assets).toHaveLength(1);
    expect(removed.shots[0]).toMatchObject({
      assetIds: [],
      review: "review",
      frameReview: "stale",
      videoReview: "stale",
    });
    expect(removed.shots[0]!.videos).toEqual(value.shots[0]!.videos);
    expect(removed.shots[1]).toBe(unaffected);
  });

  it("reopens at the nearest unfinished stage and can confirm text through the happy path", () => {
    let value = approvedState();
    expect(workflow.nearestPendingStage(value)).toBe("video");
    value.assets[0]!.review = "review";
    expect(workflow.nearestPendingStage(value)).toBe("assets");
    value.assets[0]!.review = "confirmed";
    value.shots[0]!.review = "review";
    value = storyboard.confirmShotText(value, value.shots[0]!.id);
    expect(value.shots[0]!.review).toBe("confirmed");
    expect(storyboard.confirmStoryboard(value).reviews.storyboard).toBe(
      "confirmed",
    );
    value = workflow.editScript(value, "new script");
    expect(storyboard.confirmShotText(value, value.shots[0]!.id)).toBe(value);
  });

  it("requires exact MP4 MIME and validated project images for previews", () => {
    expect(
      hasAvailableMedia(
        [{ id: mediaId, mime: "video/mp4-fake", availability: "available" }],
        mediaId,
        "video/mp4",
      ),
    ).toBe(false);
    const preview = (mime: string) =>
      renderToStaticMarkup(
        <ImagePreview
          media={{ kind: "project-image", id: mediaId }}
          label="项目图"
          projectId={projectId}
          mediaItems={[{ id: mediaId, mime, availability: "available" }]}
        />,
      );
    expect(preview("image/png")).toContain(
      `avi-media://local/${projectId}/${mediaId}`,
    );
    expect(preview("video/mp4")).not.toContain("<img");
  });

  it("keeps previously confirmed asset and shot text across repeated edits", () => {
    const original = approvedState();
    let edited = workflow.editAsset(original, original.assets[0]!.id, {
      name: "新名称",
    });
    edited = workflow.editAsset(edited, original.assets[0]!.id, {
      description: "新描述",
    });
    edited = workflow.editShot(edited, original.shots[0]!.id, {
      action: "新动作",
    });
    edited = workflow.editShot(edited, original.shots[0]!.id, {
      description: "新构图",
    });
    expect(edited.assets[0]!.approvedText).toMatchObject({
      name: original.assets[0]!.name,
      description: original.assets[0]!.description,
    });
    expect(edited.shots[0]!.approvedText).toMatchObject({
      action: original.shots[0]!.action,
      description: original.shots[0]!.description,
    });
  });
});
