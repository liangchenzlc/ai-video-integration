import { z } from "zod";
import { projectUuid, receiptSchema, type ProjectResult } from "./projects";
import { projectInputSchema } from "./drafts";
import { phaseSchema, providerIdSchema } from "./settings";
const integer = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
const text = z.string().min(1).max(2000);
export const stages = [
  "story",
  "image",
  "video",
  "speech",
  "lipsync",
  "music",
  "sfx",
  "check",
] as const;
const stage = z.enum(stages);
const mode = z.enum(["synthetic", "real"]);
const allocations = z
  .array(z.strictObject({ stage, limitMicroCny: integer }))
  .max(8);
export const budgetSchema = z.strictObject({
  totalMicroCny: integer,
  allocations,
  warningPercent: integer.min(1).max(100),
  executionMode: mode.nullable(),
});
const taskState = z.enum([
  "pending",
  "running",
  "complete",
  "partial",
  "result_unknown",
  "pending_download",
  "failed",
]);
export const taskPlanSchema = z.strictObject({
  id: projectUuid,
  objectId: projectUuid,
  stage,
  phase: phaseSchema,
  goal: text,
  inputRevisionIds: z.array(projectUuid),
  inputMediaHashes: z.array(z.string().regex(/^[0-9a-f]{64}$/)),
  steps: z
    .array(
      z.strictObject({
        id: projectUuid,
        purpose: z.enum(["create", "revise", "precheck"]),
        capabilityId: projectUuid,
        maxCalls: integer.min(1).max(16),
        requestedMs: integer.min(1).nullable(),
        maxMicroCny: integer,
        disclosure: z.array(
          z.enum(["text", "image", "audio", "video", "upload"]),
        ),
      }),
    )
    .min(1)
    .max(32),
  candidates: integer.min(1).max(8),
  maximumMicroCny: integer,
  priceVersion: text.max(100),
  templateVersion: text.max(100),
  expiresAt: text.max(40),
  executionMode: mode,
  inputPreview: z.strictObject({
    kind: z.enum([
      "story",
      "asset",
      "shot",
      "speech",
      "subtitle",
      "timeline",
      "observation",
    ]),
    payload: z.record(z.string(), z.json()),
  }),
  models: z.array(
    z.strictObject({
      stepId: projectUuid,
      providerId: providerIdSchema,
      modelId: text.max(200),
      region: text.max(100),
      capabilityVersion: text.max(100),
    }),
  ),
});
export const taskSchema = z.strictObject({
  id: projectUuid,
  planId: projectUuid,
  state: taskState,
  eventSequence: integer,
  callIds: z.array(projectUuid),
  candidateRevisionIds: z.array(projectUuid),
  observationStopped: z.boolean(),
});
export const callSchema = z
  .strictObject({
    id: projectUuid,
    taskId: projectUuid,
    stepId: projectUuid,
    submissionToken: projectUuid,
    remoteTaskId: text.max(300).nullable(),
    state: z.enum([
      "prepared",
      "submitting",
      "running",
      "result_unknown",
      "pending_download",
      "succeeded",
      "failed",
      "cancelled",
    ]),
    resultMediaIds: z.array(projectUuid),
    billingState: z.enum(["pending", "settled"]),
    reservedMicroCny: integer,
    settledMicroCny: integer.nullable(),
    expiresAt: text.max(40).nullable(),
    providerId: providerIdSchema,
    modelId: text.max(200),
    region: text.max(100),
    requestedAt: text.max(40),
    errorCode: text.max(100).nullable(),
  })
  .refine(
    (call) => call.billingState !== "settled" || call.settledMicroCny !== null,
  );
export const costSummarySchema = z.strictObject({
  settledMicroCny: integer,
  reservedMicroCny: integer,
  remainingWorkMicroCny: integer,
  reworkScenarioMicroCny: integer,
  forecastMicroCny: integer,
  budgetMicroCny: integer,
  containsUnknown: z.boolean(),
  estimateVersion: text,
});
const costEntrySchema = z
  .strictObject({
    callId: projectUuid,
    state: z.enum(["pending", "settled"]),
    reservedMicroCny: integer,
    settledMicroCny: integer.nullable(),
    basis: z.string().max(2000),
  })
  .refine(
    (entry) => entry.state !== "settled" || entry.settledMicroCny !== null,
  );
export const activitySchema = z.array(
  z.strictObject({
    projectId: projectUuid,
    projectName: text,
    taskId: projectUuid,
    state: taskState,
  }),
);
export const taskListSchema = z.strictObject({
  items: z.array(
    z.strictObject({
      id: projectUuid,
      planId: projectUuid,
      objectId: projectUuid,
      stage,
      phase: phaseSchema,
      state: taskState,
      eventSequence: integer,
      observationStopped: z.boolean(),
      active: z.boolean(),
    }),
  ),
  nextCursor: projectUuid.nullable(),
});
const pageInput = projectInputSchema.extend({
  cursor: projectUuid.optional(),
  limit: integer.min(1).max(100).optional(),
});
const command = <T extends z.ZodType>(payload: T) =>
  z.strictObject({
    clientOperationId: projectUuid,
    expectedRevision: integer,
    payload,
  });
const write = <T extends z.ZodType>(payload: T) =>
  projectInputSchema.extend({ command: command(payload) });
type PathInput = Record<string, unknown>;
const base = (input: PathInput) => `/api/v1/projects/${input.projectId}`;
const page = (input: PathInput) =>
  `?limit=${input.limit ?? 50}${input.cursor ? `&cursor=${input.cursor}` : ""}`;
function route<I extends z.ZodType, O extends z.ZodType>(
  method: "GET" | "POST" | "PUT",
  input: I,
  output: O,
  path: (input: PathInput) => string,
) {
  return { method, input, output, path };
}
export const taskRoutes = {
  budget: route(
    "GET",
    projectInputSchema,
    budgetSchema,
    (i) => `${base(i)}/budget`,
  ),
  setBudget: route(
    "PUT",
    write(
      z.strictObject({
        totalMicroCny: integer,
        allocations,
        warningPercent: integer.min(1).max(100),
      }),
    ),
    receiptSchema,
    (i) => `${base(i)}/budget`,
  ),
  plan: route(
    "POST",
    write(
      z.strictObject({
        objectId: projectUuid,
        stage,
        phase: phaseSchema,
        goal: text,
        inputRevisionIds: z.array(projectUuid),
        candidates: integer.min(1).max(8),
        includePrecheck: z.boolean(),
        executionMode: mode,
      }),
    ),
    receiptSchema,
    (i) => `${base(i)}/task-plans`,
  ),
  getPlan: route(
    "GET",
    projectInputSchema.extend({ planId: projectUuid }),
    taskPlanSchema,
    (i) => `${base(i)}/task-plans/${i.planId}`,
  ),
  start: route(
    "POST",
    write(
      z.strictObject({
        planId: projectUuid,
        authorizedMaximumMicroCny: integer,
        disclosureAccepted: z.boolean(),
      }),
    ),
    receiptSchema,
    (i) => `${base(i)}/tasks`,
  ),
  get: route(
    "GET",
    projectInputSchema.extend({ taskId: projectUuid }),
    taskSchema,
    (i) => `${base(i)}/tasks/${i.taskId}`,
  ),
  list: route(
    "GET",
    pageInput,
    taskListSchema,
    (i) => `${base(i)}/tasks${page(i)}`,
  ),
  call: route(
    "GET",
    projectInputSchema.extend({ callId: projectUuid }),
    callSchema,
    (i) => `${base(i)}/calls/${i.callId}`,
  ),
  recover: route(
    "POST",
    write(
      z.strictObject({
        action: z.enum(["query", "download", "stop_waiting", "cancel_remote"]),
      }),
    ).extend({ callId: projectUuid }),
    receiptSchema,
    (i) => `${base(i)}/calls/${i.callId}/recovery`,
  ),
  continue: route(
    "POST",
    write(z.strictObject({ confirmedUnsubmittedOnly: z.boolean() })).extend({
      taskId: projectUuid,
    }),
    receiptSchema,
    (i) => `${base(i)}/tasks/${i.taskId}/continue`,
  ),
  settle: route(
    "POST",
    write(
      z.strictObject({
        settledMicroCny: integer,
        basis: text,
        evidenceMediaIds: z.array(projectUuid),
        reason: text,
      }),
    ).extend({ callId: projectUuid }),
    receiptSchema,
    (i) => `${base(i)}/calls/${i.callId}/settlements`,
  ),
  setExpense: route(
    "PUT",
    write(
      z.strictObject({
        expenseId: projectUuid,
        category: z.enum(["storage", "transfer", "procurement"]),
        state: z.enum(["estimated", "pending", "settled"]),
        amountMicroCny: integer,
        basis: text,
      }),
    ).extend({ expenseId: projectUuid }),
    receiptSchema,
    (i) => `${base(i)}/external-expenses/${i.expenseId}`,
  ),
  costs: route(
    "GET",
    projectInputSchema,
    costSummarySchema,
    (i) => `${base(i)}/cost-summary`,
  ),
  entries: route(
    "GET",
    pageInput,
    z.strictObject({
      items: z.array(costEntrySchema),
      nextCursor: projectUuid.nullable(),
    }),
    (i) => `${base(i)}/cost-entries${page(i)}`,
  ),
  activity: route(
    "GET",
    z.strictObject({}),
    activitySchema,
    () => "/api/v1/task-activity",
  ),
};
export type TasksBridge = {
  [K in keyof typeof taskRoutes]: (
    input: z.infer<(typeof taskRoutes)[K]["input"]>,
  ) => Promise<ProjectResult<z.infer<(typeof taskRoutes)[K]["output"]>>>;
};
export type TaskPlan = z.infer<typeof taskPlanSchema>;
export type Task = z.infer<typeof taskSchema>;
export type Call = z.infer<typeof callSchema>;
export type Budget = z.infer<typeof budgetSchema>;
export type CostSummary = z.infer<typeof costSummarySchema>;
