import { expect, test, vi } from "vitest";
import { parseYuan, formatYuan } from "../../src/app/task-money";
import {
  advanceTaskDraftRevision,
  describeCandidate,
  loadAllTaskCandidates,
} from "../../src/app/TaskPanel";
import { taskRoutes, callSchema } from "../../electron/shared/tasks";

test("yuan conversion preserves every micro yuan and rejects rounding or unsafe amounts", () => {
  expect(parseYuan("1.234567")).toBe(1234567);
  expect(parseYuan("9007199254.740991")).toBe(Number.MAX_SAFE_INTEGER);
  expect(formatYuan(1234567)).toBe("1.234567");
  for (const value of [
    "1.0000001",
    "-1",
    "1e3",
    "",
    "9007199254.740992",
    "NaN",
  ])
    expect(() => parseYuan(value)).toThrow();
});
test("task bridge exposes only fixed routes and rejects arbitrary transport and amounts", () => {
  const id = "00000000-0000-4000-8000-000000000001";
  expect(
    taskRoutes.budget.input.safeParse({ projectId: id, path: "/private" })
      .success,
  ).toBe(false);
  expect(
    taskRoutes.setBudget.input.safeParse({
      projectId: id,
      command: {
        clientOperationId: id,
        expectedRevision: 0,
        payload: { totalMicroCny: 1.1, allocations: [], warningPercent: 80 },
      },
    }).success,
  ).toBe(false);
  expect(taskRoutes.start.path({ projectId: id })).toBe(
    `/api/v1/projects/${id}/tasks`,
  );
  expect(taskRoutes.activity.path({})).toBe("/api/v1/task-activity");
  expect(
    taskRoutes.candidates.path({ projectId: id, taskId: id, limit: 25 }),
  ).toBe(`/api/v1/projects/${id}/tasks/${id}/candidates?limit=25`);
  expect(
    taskRoutes.candidates.input.safeParse({
      projectId: id,
      taskId: id,
      url: "https://example.invalid/private",
    }).success,
  ).toBe(false);
});

test("candidate presentation exposes story content and local image media without adopting it", () => {
  const id = "00000000-0000-4000-8000-000000000001";
  const story = describeCandidate(id, {
    kind: "story",
    content: {
      sourceText: "雨夜里的门灯。",
      sourceHash: "a".repeat(64),
      inputType: "idea",
      approvalLevel: "outline",
      brief: "保留陌生人之间的善意。",
      outline: ["旅人点亮门灯", "清晨收到一把伞"],
      requirements: [],
      scenes: [],
      dialogues: [],
      adaptationNotes: ["本地固定练习结果"],
    },
  });
  expect(story).toMatchObject({
    kind: "text",
    title: "故事候选",
    summary: "旅人点亮门灯\n清晨收到一把伞",
    mediaUrl: null,
  });

  const image = describeCandidate(id, {
    kind: "asset",
    content: {
      assetType: "character",
      name: "门灯旅人",
      identityAnchors: ["深色雨衣", "旧帆布包"],
      allowedChanges: [],
      states: [],
      references: [
        {
          mediaId: id,
          mediaHash: "b".repeat(64),
          role: "identity",
          order: 0,
          state: "pending",
          keep: [],
          ignore: [],
          crop: null,
        },
      ],
    },
  });
  expect(image).toMatchObject({
    kind: "image",
    title: "角色图像候选：门灯旅人",
    summary: "身份锚点：深色雨衣、旧帆布包",
    mediaUrl: `avi-media://local/${id}/${id}`,
  });
});

test("candidate loading retains every page when the response size splits a task", async () => {
  const first = "00000000-0000-4000-8000-000000000001";
  const second = "00000000-0000-4000-8000-000000000002";
  const revision = (id: string) => ({
    id,
    artifactId: first,
    parentId: null,
    payload: {
      kind: "story" as const,
      content: {
        sourceText: "雨夜",
        sourceHash: "a".repeat(64),
        inputType: "idea" as const,
        approvalLevel: "proposal" as const,
        brief: "门灯",
        outline: [],
        requirements: [],
        scenes: [],
        dialogues: [],
        adaptationNotes: [],
      },
    },
    contentHash: "b".repeat(64),
    createdAt: "2026-09-16T10:00:00Z",
  });
  const cursors: Array<string | undefined> = [];
  const result = await loadAllTaskCandidates(async (cursor) => {
    cursors.push(cursor);
    return cursor
      ? {
          ok: true as const,
          data: { items: [revision(second)], nextCursor: null },
        }
      : {
          ok: true as const,
          data: { items: [revision(first)], nextCursor: first },
        };
  });
  expect(cursors).toEqual([undefined, first]);
  expect(result.error).toBeNull();
  expect(result.items.map((item) => item.id)).toEqual([first, second]);
});

test("candidate loading returns earlier pages when a later page cannot be read", async () => {
  const id = "00000000-0000-4000-8000-000000000001";
  const item = {
    id,
    artifactId: id,
    parentId: null,
    payload: {
      kind: "story" as const,
      content: {
        sourceText: "雨夜",
        sourceHash: "a".repeat(64),
        inputType: "idea" as const,
        approvalLevel: "proposal" as const,
        brief: "门灯",
        outline: [],
        requirements: [],
        scenes: [],
        dialogues: [],
        adaptationNotes: [],
      },
    },
    contentHash: "b".repeat(64),
    createdAt: "2026-09-16T10:00:00Z",
  };
  const result = await loadAllTaskCandidates(async (cursor) =>
    cursor
      ? {
          ok: false as const,
          error: { code: "BACKEND_UNAVAILABLE", message: "读取下一页失败" },
        }
      : { ok: true as const, data: { items: [item], nextCursor: id } },
  );
  expect(result.items).toEqual([item]);
  expect(result.error).toBe("读取下一页失败");
});

test("settled calls require an explicit amount; unknown calls retain a nullable settlement", () => {
  const id = "00000000-0000-4000-8000-000000000001";
  const call = {
    id,
    taskId: id,
    stepId: id,
    submissionToken: id,
    remoteTaskId: null,
    state: "result_unknown",
    resultMediaIds: [],
    billingState: "pending",
    reservedMicroCny: 1200000,
    settledMicroCny: null,
    expiresAt: null,
    providerId: "synthetic",
    modelId: "fixture",
    region: "local",
    requestedAt: "2026-09-16T10:00:00Z",
    errorCode: "CALL_RESULT_UNKNOWN",
  };
  expect(callSchema.safeParse(call).success).toBe(true);
  expect(
    callSchema.safeParse({ ...call, billingState: "settled" }).success,
  ).toBe(false);
  expect(
    callSchema.safeParse({
      ...call,
      billingState: "settled",
      settledMicroCny: 0,
    }).success,
  ).toBe(true);
  expect(
    taskRoutes.entries.output.safeParse({
      items: [
        {
          callId: id,
          state: "settled",
          reservedMicroCny: 0,
          settledMicroCny: null,
          basis: "",
        },
      ],
      nextCursor: null,
    }).success,
  ).toBe(false);
});

test("a matching task receipt advances the clean draft from its observed project head", () => {
  const id = "00000000-0000-4000-8000-000000000001";
  const advance = vi.fn(() => true);
  expect(
    advanceTaskDraftRevision(
      { id, expectedRevision: 7 },
      {
        operationId: id,
        committedRevision: 8,
        resourceId: "00000000-0000-4000-8000-000000000002",
        state: "committed",
      },
      advance,
    ),
  ).toBe(true);
  expect(advance).toHaveBeenCalledWith(7, 8);

  expect(
    advanceTaskDraftRevision(
      { id, expectedRevision: undefined },
      {
        operationId: id,
        committedRevision: 8,
        resourceId: "00000000-0000-4000-8000-000000000002",
        state: "committed",
      },
      advance,
    ),
  ).toBe(false);
  expect(advance).toHaveBeenCalledTimes(1);
});
