import { expect, test, vi } from "vitest";
import { parseYuan, formatYuan } from "../../src/app/task-money";
import { advanceTaskDraftRevision } from "../../src/app/TaskPanel";
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
