import { describe, expect, it } from "vitest";
import type { GlobalAsset } from "../../src/features/assets/asset-model";
import { emptyWorkflow } from "../../src/features/projects/episode-workflow";
import {
  readProjectResources,
  validAsset,
} from "../../src/features/projects/project-detail-model";
import {
  adoptAssetImage,
  canBindImportedImage,
  shareAsset,
} from "../../src/pages/projects/episode/AssetsStage";

const projectMediaId = "11111111-1111-4111-8111-111111111111";

const resource: GlobalAsset = {
  id: "resource-kept",
  kind: "character",
  name: "阿遥",
  description: "雨衣",
  category: "主角",
  tags: ["雨夜"],
  createdAt: "2026-09-17T00:00:00.000Z",
};

describe("episode asset sharing", () => {
  it("keeps a selected demo image as a demo reference", () => {
    const workflow = emptyWorkflow({ aspect: "16:9" });
    workflow.assets = [
      {
        id: "asset-1",
        kind: "character",
        name: "阿遥",
        description: "雨衣",
        linkedResourceId: null,
        imageCandidates: [
          {
            id: "candidate-1",
            source: "demo",
            value: { kind: "demo-image", id: "demo-image-asset" },
          },
        ],
        selectedImageId: null,
        review: "review",
      },
    ];

    expect(
      adoptAssetImage(workflow, "asset-1", "candidate-1").assets[0],
    ).toMatchObject({
      selectedImageId: "candidate-1",
      imageCandidates: [
        { value: { kind: "demo-image", id: "demo-image-asset" } },
      ],
    });
  });

  it("stales only downstream work for the asset whose image changes", () => {
    const workflow = emptyWorkflow({ aspect: "16:9" });
    workflow.assets = [
      {
        id: "asset-1",
        kind: "character",
        name: "阿遥",
        description: "雨衣",
        linkedResourceId: null,
        imageCandidates: [
          {
            id: "candidate-1",
            source: "demo",
            value: { kind: "demo-image", id: "demo-image-asset" },
          },
        ],
        selectedImageId: null,
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
        action: "走",
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
        ],
      },
    ];

    const next = adoptAssetImage(workflow, "asset-1", "candidate-1");
    expect(next.assets[0].imageCandidates).toEqual(
      workflow.assets[0].imageCandidates,
    );
    expect(next.shots[0]).toMatchObject({
      frameReview: "stale",
      videoReview: "stale",
    });
    expect(next.shots[1]).toMatchObject({
      frameReview: "confirmed",
      videoReview: "not_started",
    });
    expect(next.gridBatches[0].cells.map((cell) => cell.review)).toEqual([
      "stale",
      "confirmed",
    ]);
  });

  it("only permits an available image media record to be bound after import", () => {
    expect(canBindImportedImage([], projectMediaId)).toBe(false);
    expect(
      canBindImportedImage(
        [{ id: projectMediaId, mime: "video/mp4", availability: "available" }],
        projectMediaId,
      ),
    ).toBe(false);
    expect(
      canBindImportedImage(
        [{ id: projectMediaId, mime: "image/png", availability: "missing" }],
        projectMediaId,
      ),
    ).toBe(false);
    expect(
      canBindImportedImage(
        [{ id: projectMediaId, mime: "image/png", availability: "available" }],
        projectMediaId,
      ),
    ).toBe(true);
  });

  it("keeps the existing project resource id when an asset is shared", () => {
    const result = shareAsset(
      {
        id: "asset-1",
        kind: "character",
        name: "阿遥",
        description: "黄色雨衣",
        linkedResourceId: "resource-kept",
        review: "confirmed",
        selectedImageId: "image",
        imageCandidates: [
          {
            id: "image",
            source: "demo",
            value: { kind: "demo-image", id: "demo-image-safe" },
          },
        ],
      },
      [resource],
      "link",
    );

    expect(result).toEqual({
      ok: true,
      linkedResourceId: "resource-kept",
      resources: [
        {
          ...resource,
          description: "黄色雨衣",
          visualRef: { kind: "demo-image", id: "demo-image-safe" },
        },
      ],
    });
  });

  it("requires an explicit link or create choice for duplicate names", () => {
    expect(
      shareAsset(
        {
          id: "asset-2",
          kind: "character",
          name: "阿遥",
          description: "雨衣",
          linkedResourceId: null,
          review: "confirmed",
          selectedImageId: "image",
          imageCandidates: [
            {
              id: "image",
              source: "demo",
              value: { kind: "demo-image", id: "demo-image-safe" },
            },
          ],
        },
        [resource],
      ),
    ).toEqual({ ok: false, reason: "choice_required", matches: [resource] });
  });

  it("accepts a project image visual reference and rejects malformed refs", () => {
    expect(validAsset(resource)).toBe(true);
    expect(
      validAsset({
        ...resource,
        visualRef: { kind: "project-image", id: projectMediaId },
      }),
    ).toBe(true);
    expect(
      validAsset({
        ...resource,
        visualRef: { kind: "project-video", id: projectMediaId },
      }),
    ).toBe(false);
    expect(
      validAsset({
        ...resource,
        visualRef: { kind: "project-image", id: "not-a-media-id" },
      }),
    ).toBe(false);
  });

  it("loads legacy project resource cards without a visual reference", () => {
    const storage = {
      getItem: () => JSON.stringify([resource]),
    };
    expect(readProjectResources("project-1", storage)).toEqual([resource]);
  });
});
