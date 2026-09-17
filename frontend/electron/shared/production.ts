import { z } from "zod";
import { projectUuid, receiptSchema, type ProjectResult } from "./projects";

const integer = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
const text = z.string().max(4000);
const object = z.record(z.string(), z.json());
const kind = z.enum([
  "story",
  "asset",
  "shot",
  "speech",
  "subtitle",
  "timeline",
  "observation",
]);
const project = z.strictObject({ projectId: projectUuid });
const ids = z.array(projectUuid).max(1000);
const hash = z.string().regex(/^[0-9a-f]{64}$/);
export const timelineSchema = z.strictObject({
  width: z.union([
    z.literal(720),
    z.literal(1080),
    z.literal(1280),
    z.literal(1920),
  ]),
  height: z.union([
    z.literal(720),
    z.literal(1080),
    z.literal(1280),
    z.literal(1920),
  ]),
  fps: z.strictObject({
    numerator: z.union([z.literal(24), z.literal(25), z.literal(30)]),
    denominator: z.literal(1),
  }),
  durationMs: integer.min(1),
  burnSubtitles: z.boolean(),
  tracks: z
    .array(
      z.strictObject({
        id: projectUuid,
        kind: z.enum(["image", "video", "voice", "music", "sfx", "subtitle"]),
        order: integer.max(100),
        muted: z.boolean(),
      }),
    )
    .min(1)
    .max(100),
  clips: z
    .array(
      z.strictObject({
        id: projectUuid,
        trackId: projectUuid,
        shotId: projectUuid.nullable(),
        mediaId: projectUuid.nullable(),
        contentRevisionId: projectUuid.nullable(),
        startMs: integer,
        inMs: integer,
        outMs: integer.min(1),
        durationMs: integer.min(1),
        gainDb: z.number().min(-96).max(12),
        linkedClipIds: ids,
        keyframes: z
          .array(
            z.strictObject({
              timeMs: integer,
              property: z.enum(["x", "y", "scale", "opacity", "volume"]),
              value: z.number().min(-10000).max(10000),
              interpolation: z.enum(["linear", "hold"]),
            }),
          )
          .max(1000),
      }),
    )
    .max(5000),
  transitions: z
    .array(
      z.strictObject({
        id: projectUuid,
        fromClipId: projectUuid,
        toClipId: projectUuid,
        type: z.enum(["cut", "dissolve", "fade"]),
        durationMs: integer.max(10000),
      }),
    )
    .max(1000),
});
export const rightsSchema = z.strictObject({
  id: projectUuid,
  mediaId: projectUuid,
  source: text.min(1).max(2000),
  use: text.min(1).max(2000),
  evidenceMediaIds: ids,
  state: z.enum(["unverified", "verified", "recheck"]),
  explanation: text,
});
export const issueSchema = z.strictObject({
  id: projectUuid,
  ruleId: text,
  ruleVersion: text,
  artifactId: projectUuid,
  revisionId: projectUuid,
  baselineRevisionId: projectUuid.nullable(),
  severity: z.enum(["blocking", "unknown_required", "deviation", "advice"]),
  status: z.enum([
    "open",
    "fixing",
    "recheck",
    "resolved",
    "accepted_deviation",
  ]),
  message: text,
  evidence: text,
  time: z.strictObject({ startMs: integer, endMs: integer.min(1) }).nullable(),
  method: z.enum(["local", "ai", "human"]),
  limitations: text,
});
export const renderPlanSchema = z.strictObject({
  id: projectUuid,
  compilerVersion: text,
  timelineRevisionId: projectUuid,
  timeline: timelineSchema,
  mediaHashes: z
    .array(z.strictObject({ mediaId: projectUuid, sha256: hash }))
    .max(1000),
  inputHash: hash,
  videoCodec: z.literal("h264"),
  audioCodec: z.literal("aac").nullable(),
  purpose: z.enum(["preview", "animatic", "export"]),
});
const command = <T extends z.ZodType>(payload: T) =>
  z.strictObject({
    clientOperationId: projectUuid,
    expectedRevision: integer,
    payload,
  });
const input = <T extends z.ZodType>(payload: T) => project.extend({ payload });
const write = <T extends z.ZodType>(payload: T) =>
  project.extend({ command: command(payload) });
const base = (value: Record<string, unknown>) =>
  `/api/v1/projects/${value.projectId}`;
const route = <I extends z.ZodType, O extends z.ZodType>(options: {
  method: "GET" | "POST" | "PUT";
  input: I;
  output: O;
  mutating: boolean;
  global?: boolean;
  path: (value: Record<string, unknown>) => string;
  body?: (value: z.infer<I>) => unknown;
}) => options;
const timelineId = z.strictObject({ timelineRevisionId: projectUuid });
const diagnosticOptions = z.strictObject({
  projectId: projectUuid.nullable(),
  includeProject: z.boolean(),
  includeContent: z.boolean(),
});
export const productionRoutes = {
  index: route({
    method: "GET",
    input: project.extend({ offset: integer.max(999999999).optional() }),
    output: z.strictObject({
      nextOffset: integer.nullable(),
      drafts: z
        .array(
          z.strictObject({
            id: projectUuid,
            artifactId: projectUuid,
            kind,
            savedAt: text,
          }),
        )
        .max(5000),
      adopted: z
        .array(
          z.strictObject({
            artifactId: projectUuid,
            revisionId: projectUuid,
            kind,
            confirmed: z.boolean(),
            needsUpdate: z.boolean(),
            content: object,
          }),
        )
        .max(5000),
    }),
    mutating: false,
    path: (i) => `${base(i)}/production?offset=${i.offset ?? 0}`,
  }),
  timing: route({
    method: "POST",
    input: input(
      z.strictObject({
        shotRevisionId: projectUuid,
        speechRevisionIds: ids,
        beforeMs: integer,
        afterMs: integer,
      }),
    ),
    output: z.strictObject({
      requiredMs: integer,
      plannedMs: integer,
      shortageMs: integer,
      method: z.enum(["measured", "estimated"]),
      suitable: z.boolean(),
    }),
    mutating: false,
    path: (i) => `${base(i)}/timing-checks`,
    body: (i) => i.payload,
  }),
  readiness: route({
    method: "POST",
    input: input(
      z.strictObject({
        shotRevisionId: projectUuid,
        speechRevisionIds: ids,
        capabilityId: projectUuid,
        path: z.enum(["research", "production"]),
      }),
    ),
    output: z.strictObject({
      ready: z.boolean(),
      blockers: z.array(text).max(1000),
      warnings: z.array(text).max(1000),
    }),
    mutating: false,
    path: (i) => `${base(i)}/video-readiness`,
    body: (i) => i.payload,
  }),
  rights: route({
    method: "GET",
    input: project,
    output: z.strictObject({ items: z.array(rightsSchema).max(5000) }),
    mutating: false,
    path: (i) => `${base(i)}/rights`,
  }),
  saveRights: route({
    method: "PUT",
    input: write(z.strictObject({ evidence: rightsSchema })).extend({
      evidenceId: projectUuid,
    }),
    output: receiptSchema,
    mutating: true,
    path: (i) => `${base(i)}/rights/${i.evidenceId}`,
    body: (i) => i.command,
  }),
  ducking: route({
    method: "POST",
    input: input(
      z.strictObject({
        timelineRevisionId: projectUuid,
        musicClipIds: ids,
        reductionDb: z.number().min(0).max(96),
        attackMs: integer.max(10000),
        releaseMs: integer.max(10000),
      }),
    ),
    output: z.strictObject({
      timeline: timelineSchema,
      warnings: z.array(text).max(1000),
    }),
    mutating: false,
    path: (i) => `${base(i)}/mix/ducking`,
    body: (i) => i.payload,
  }),
  timelineEdit: route({
    method: "POST",
    input: input(
      z.strictObject({
        timeline: timelineSchema,
        action: z.enum(["move", "split", "trim"]),
        clipId: projectUuid,
        startMs: integer.optional(),
        splitMs: integer.optional(),
        inMs: integer.optional(),
        outMs: integer.optional(),
        durationMs: integer.optional(),
      }),
    ),
    output: z.strictObject({
      timeline: timelineSchema,
      affectedClipIds: ids,
      subtitleSplitPreview: z
        .array(z.strictObject({ clipId: projectUuid, splitMs: integer }))
        .max(1000),
    }),
    mutating: false,
    path: (i) => `${base(i)}/timeline/edit-preview`,
    body: (i) => i.payload,
  }),
  renderPlan: route({
    method: "POST",
    input: input(timelineId.extend({ burnSubtitles: z.boolean().optional() })),
    output: renderPlanSchema,
    mutating: false,
    path: (i) => `${base(i)}/render-plan-preview`,
    body: (i) => i.payload,
  }),
  animatic: route({
    method: "POST",
    input: write(timelineId),
    output: receiptSchema,
    mutating: true,
    path: (i) => `${base(i)}/animatics`,
    body: (i) => i.command,
  }),
  replacement: route({
    method: "POST",
    input: input(
      timelineId.extend({ clipId: projectUuid, newMediaId: projectUuid }),
    ),
    output: z.strictObject({
      shortageMs: integer,
      affectedClipIds: ids,
      requiredChecks: z.array(text).max(1000),
      canPreserveEdit: z.boolean(),
    }),
    mutating: false,
    path: (i) => `${base(i)}/timeline/replacement-preview`,
    body: (i) => i.payload,
  }),
  exportFilm: route({
    method: "POST",
    input: write(
      timelineId.extend({
        targetGrantId: projectUuid,
        burnSubtitles: z.boolean(),
        overwriteConfirmed: z.boolean(),
      }),
    ),
    output: receiptSchema,
    mutating: true,
    path: (i) => `${base(i)}/exports`,
    body: (i) => i.command,
  }),
  getExport: route({
    method: "GET",
    input: project.extend({ exportId: projectUuid }),
    output: z.strictObject({
      id: projectUuid,
      timelineRevisionId: projectUuid,
      jobId: projectUuid,
      state: z.enum(["pending", "complete", "failed", "cancelled"]),
      mediaId: projectUuid.nullable(),
      inputHash: hash,
    }),
    mutating: false,
    path: (i) => `${base(i)}/exports/${i.exportId}`,
  }),
  issues: route({
    method: "GET",
    input: project.extend({
      cursor: projectUuid.nullable().optional(),
      limit: integer.min(1).max(200).optional(),
    }),
    output: z.strictObject({
      items: z.array(issueSchema).max(200),
      nextCursor: projectUuid.nullable(),
    }),
    mutating: false,
    path: (i) =>
      `${base(i)}/issues?limit=${i.limit ?? 50}${i.cursor ? `&cursor=${i.cursor}` : ""}`,
  }),
  decideIssue: route({
    method: "POST",
    input: write(
      z.strictObject({
        action: z.enum([
          "accept_deviation",
          "request_recheck",
          "attach_evidence",
        ]),
        reason: text.min(1).max(2000),
        evidenceMediaIds: ids,
      }),
    ).extend({ issueId: projectUuid }),
    output: receiptSchema,
    mutating: true,
    path: (i) => `${base(i)}/issues/${i.issueId}/decisions`,
    body: (i) => i.command,
  }),
  diagnosticPreview: route({
    method: "POST",
    input: diagnosticOptions,
    output: diagnosticOptions.extend({
      files: z.array(z.strictObject({ name: text, description: text })).max(20),
    }),
    mutating: false,
    global: true,
    path: () => "/api/v1/diagnostics/preview",
    body: (i) => i,
  }),
  diagnostic: route({
    method: "POST",
    input: z.strictObject({
      command: command(
        diagnosticOptions.extend({ targetGrantId: projectUuid }),
      ),
    }),
    output: receiptSchema,
    mutating: true,
    global: true,
    path: () => "/api/v1/diagnostics",
    body: (i) => i.command,
  }),
};
export const chooseTargetSchema = z.strictObject({
  purpose: z.enum(["export", "diagnostic"]),
});
export const chosenTargetSchema = z
  .strictObject({ grantId: projectUuid, name: text, exists: z.boolean() })
  .nullable();
export type ProductionIndex = z.infer<typeof productionRoutes.index.output>;
export type Timeline = z.infer<typeof timelineSchema>;
export type RightEvidence = z.infer<typeof rightsSchema>;
export type ProductionBridge = {
  [K in keyof typeof productionRoutes]: (
    input: z.infer<(typeof productionRoutes)[K]["input"]>,
  ) => Promise<ProjectResult<z.infer<(typeof productionRoutes)[K]["output"]>>>;
} & {
  chooseTarget(
    input: z.infer<typeof chooseTargetSchema>,
  ): Promise<ProjectResult<z.infer<typeof chosenTargetSchema>>>;
};
