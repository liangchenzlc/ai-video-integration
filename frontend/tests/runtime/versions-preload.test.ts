import { randomUUID } from "node:crypto";
import { afterEach, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("electron", () => ({ ipcRenderer: { invoke: mocks.invoke } }));

import { versionsBridge } from "../../electron/preload/versions";
import {
  checkReportSchema,
  revisionSchema,
} from "../../electron/shared/versions";

afterEach(() => mocks.invoke.mockReset());

test("version preload rejects malformed local input before IPC", async () => {
  const result = await versionsBridge.list({
    projectId: randomUUID(),
    artifactId: "not-an-artifact-id",
  });
  expect(result).toMatchObject({
    ok: false,
    error: { code: "REQUEST_INVALID" },
  });
  expect(mocks.invoke).not.toHaveBeenCalled();
});

test("version preload rejects extra backend content and remaps unsafe errors", async () => {
  mocks.invoke.mockResolvedValueOnce({
    ok: true,
    data: {
      id: randomUUID(),
      kind: "story",
      adoptedRevisionId: null,
      confirmedRevisionId: null,
      needsUpdate: false,
      latestAdoptionId: null,
      privatePath: "private-sentinel",
    },
  });
  const result = await versionsBridge.artifact({
    projectId: randomUUID(),
    artifactId: randomUUID(),
  });
  expect(result.ok).toBe(false);
  expect(JSON.stringify(result)).not.toContain("private-sentinel");

  mocks.invoke.mockResolvedValueOnce({
    ok: false,
    error: { code: "PREVIEW_STALE", message: "private-sentinel" },
  });
  const failure = await versionsBridge.preview({
    projectId: randomUUID(),
    artifactId: randomUUID(),
    toRevisionId: randomUUID(),
    expectedRevision: 3,
  });
  expect(failure).toMatchObject({
    ok: false,
    error: { code: "PREVIEW_STALE" },
  });
  expect(JSON.stringify(failure)).not.toContain("private-sentinel");
});

test("artifact reads retain the persisted latest adoption handle", async () => {
  const adoptionId = randomUUID();
  mocks.invoke.mockResolvedValue({
    ok: true,
    data: {
      id: randomUUID(),
      kind: "story",
      adoptedRevisionId: randomUUID(),
      confirmedRevisionId: null,
      needsUpdate: true,
      latestAdoptionId: adoptionId,
    },
  });
  const result = await versionsBridge.artifact({
    projectId: randomUUID(),
    artifactId: randomUUID(),
  });
  expect(result).toMatchObject({
    ok: true,
    data: { latestAdoptionId: adoptionId },
  });
});

test("check reports enforce the reviewed issue and observed-range limits", () => {
  const id = randomUUID();
  const base = {
    id,
    revisionIds: [id],
    ruleIds: ["structural"],
    outcome: "pass" as const,
    issueIds: Array(2000).fill(id),
    method: "local" as const,
    observedRanges: Array(1000).fill({ startMs: 0, endMs: 1 }),
    evidenceMediaIds: [],
    ruleVersion: "local-structure-v1",
    limitations: "deterministic only",
  };
  expect(checkReportSchema.safeParse(base).success).toBe(true);
  expect(
    checkReportSchema.safeParse({
      ...base,
      issueIds: [...base.issueIds, id],
    }).success,
  ).toBe(false);
  expect(
    checkReportSchema.safeParse({
      ...base,
      observedRanges: [...base.observedRanges, { startMs: 1, endMs: 2 }],
    }).success,
  ).toBe(false);
});

test("formal revisions reject partial draft payloads at the shared bridge boundary", () => {
  const id = randomUUID();
  expect(
    revisionSchema.safeParse({
      id,
      artifactId: randomUUID(),
      parentId: null,
      payload: { kind: "story", content: {} },
      contentHash: "a".repeat(64),
      createdAt: "2026-09-16T08:00:00Z",
    }).success,
  ).toBe(false);
});

test("the bundled formal contract accepts every complete kind and rejects unknown nested fields", () => {
  const id = randomUUID();
  const hash = "a".repeat(64);
  const story = {
    kind: "story" as const,
    content: {
      sourceText: "灯亮了。",
      sourceHash: hash,
      inputType: "idea" as const,
      approvalLevel: "proposal" as const,
      brief: "保持温暖。",
      outline: [],
      requirements: [],
      scenes: [],
      dialogues: [],
      adaptationNotes: [],
    },
  };
  const payloads = [
    story,
    {
      kind: "asset",
      content: {
        assetType: "character",
        name: "旅人",
        identityAnchors: ["蓝色外套"],
        allowedChanges: [],
        states: [],
        references: [],
      },
    },
    {
      kind: "shot",
      content: {
        shotId: id,
        purpose: "建立场景",
        sceneId: id,
        assetRevisionIds: [],
        requirementIds: [],
        startState: "门灯熄灭",
        events: [],
        endState: "门灯亮起",
        camera: "固定中景",
        subjectHand: "none",
        plannedMs: 1000,
        dialogueIds: [],
        references: [],
        videoMediaId: null,
        pickupOfShotId: null,
        use: "original",
      },
    },
    {
      kind: "speech",
      content: {
        dialogueId: id,
        text: "谢谢。",
        speakerAssetId: id,
        mediaId: id,
        measuredMs: 800,
        voicedRanges: [],
        timingMethod: "manual",
        voicePreset: "neutral",
        pronunciationNotes: "",
      },
    },
    {
      kind: "subtitle",
      content: {
        audioRevisionId: null,
        timingMethod: "manual",
        cues: [],
      },
    },
    {
      kind: "timeline",
      content: {
        width: 1920,
        height: 1080,
        fps: { numerator: 24, denominator: 1 },
        durationMs: 1000,
        tracks: [{ id, kind: "video", order: 0, muted: false }],
        clips: [],
        transitions: [],
        burnSubtitles: false,
      },
    },
    {
      kind: "observation",
      content: {
        mediaId: id,
        mediaHash: hash,
        method: "technical",
        observed: [],
        usable: [],
        problems: [],
        limitations: "",
      },
    },
  ];
  for (const payload of payloads)
    expect(
      revisionSchema.safeParse({
        id,
        artifactId: id,
        parentId: null,
        payload,
        contentHash: hash,
        createdAt: "2026-09-16T08:00:00Z",
      }).success,
    ).toBe(true);
  expect(
    revisionSchema.safeParse({
      id,
      artifactId: id,
      parentId: null,
      payload: {
        ...story,
        content: { ...story.content, privatePath: "not allowed" },
      },
      contentHash: hash,
      createdAt: "2026-09-16T08:00:00Z",
    }).success,
  ).toBe(false);
});
