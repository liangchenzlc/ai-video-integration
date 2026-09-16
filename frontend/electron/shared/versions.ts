import { z } from "zod";
import revisionPayloadContract from "../../../backend/app/schemas/revision.schema.json";
import type { components } from "../../src/api/runtime-types";
import { projectUuid, receiptSchema, type ProjectResult } from "./projects";

const integer = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
const artifactKindSchema = z.enum([
  "story",
  "asset",
  "shot",
  "speech",
  "subtitle",
  "timeline",
  "observation",
]);
type CompletePayload = components["schemas"]["CompletePayload"];
const typedPayloadSchema = z.fromJSONSchema(
  revisionPayloadContract as Parameters<typeof z.fromJSONSchema>[0],
) as z.ZodType<CompletePayload>;

export const artifactStateSchema = z.strictObject({
  id: projectUuid,
  kind: artifactKindSchema,
  adoptedRevisionId: projectUuid.nullable(),
  confirmedRevisionId: projectUuid.nullable(),
  needsUpdate: z.boolean(),
  latestAdoptionId: projectUuid.nullable(),
});
export const revisionSchema = z.strictObject({
  id: projectUuid,
  artifactId: projectUuid,
  parentId: projectUuid.nullable(),
  payload: typedPayloadSchema,
  contentHash: z.string().regex(/^[0-9a-f]{64}$/),
  createdAt: z.string().min(1).max(40),
});
export const revisionPageSchema = z.strictObject({
  items: z.array(revisionSchema).max(200),
  nextCursor: projectUuid.nullable(),
});
export const impactSchema = z.strictObject({
  previewId: projectUuid,
  artifactId: projectUuid,
  fromRevisionId: projectUuid.nullable(),
  toRevisionId: projectUuid,
  affectedArtifactIds: z.array(projectUuid).max(10000),
  affectedScopes: z
    .array(
      z.enum([
        "identityVisual",
        "dialogueAudio",
        "subtitleTiming",
        "referenceInput",
        "requirementCoverage",
        "revealTiming",
        "timelinePlacement",
        "mix",
        "export",
      ]),
    )
    .max(9),
  estimatedExtraMicroCny: integer.nullable(),
  requiredChecks: z.array(z.string().min(1).max(100)).max(200),
  expiresAt: z.string().min(1).max(40),
});
export const checkReportSchema = z.strictObject({
  id: projectUuid,
  revisionIds: z.array(projectUuid).min(1).max(1000),
  ruleIds: z.array(z.string().min(1).max(100)).min(1).max(200),
  outcome: z.enum(["pass", "fail", "unknown", "not_applicable"]),
  issueIds: z.array(projectUuid).max(2000),
  method: z.enum(["local", "ai", "human"]),
  observedRanges: z
    .array(
      z
        .strictObject({
          startMs: integer,
          endMs: integer.min(1),
        })
        .refine((range) => range.endMs > range.startMs),
    )
    .max(1000),
  evidenceMediaIds: z.array(projectUuid).max(1000),
  ruleVersion: z.string().min(1).max(100),
  limitations: z.string().max(4000),
});

const projectInput = z.strictObject({ projectId: projectUuid });
const artifactInput = projectInput.extend({ artifactId: projectUuid });
const command = <T extends z.ZodType>(payload: T) =>
  z.strictObject({
    clientOperationId: projectUuid,
    expectedRevision: integer,
    payload,
  });
const writeArtifact = <T extends z.ZodType>(payload: T) =>
  artifactInput.extend({ command: command(payload) });
const base = (input: Record<string, unknown>) =>
  `/api/v1/projects/${input.projectId}`;
const artifactBase = (input: Record<string, unknown>) =>
  `${base(input)}/artifacts/${input.artifactId}`;
const route = <I extends z.ZodType, O extends z.ZodType>(options: {
  method: "GET" | "POST";
  input: I;
  output: O;
  path: (input: Record<string, unknown>) => string;
  mutating: boolean;
  body?: (input: z.infer<I>) => unknown;
}) => options;

export const versionRoutes = {
  artifact: route({
    method: "GET",
    input: artifactInput,
    output: artifactStateSchema,
    path: artifactBase,
    mutating: false,
  }),
  list: route({
    method: "GET",
    input: artifactInput.extend({
      cursor: projectUuid.optional(),
      limit: integer.min(1).max(200).optional(),
    }),
    output: revisionPageSchema,
    path: (input) =>
      `${artifactBase(input)}/revisions?limit=${input.limit ?? 50}${input.cursor ? `&cursor=${input.cursor}` : ""}`,
    mutating: false,
  }),
  create: route({
    method: "POST",
    input: writeArtifact(z.strictObject({ draftId: projectUuid })),
    output: receiptSchema,
    path: (input) => `${artifactBase(input)}/revisions`,
    mutating: true,
    body: (input) => input.command,
  }),
  preview: route({
    method: "POST",
    input: artifactInput.extend({
      toRevisionId: projectUuid,
      expectedRevision: integer,
    }),
    output: impactSchema,
    path: (input) => `${artifactBase(input)}/adoption-preview`,
    mutating: false,
    body: (input) => ({
      toRevisionId: input.toRevisionId,
      expectedRevision: input.expectedRevision,
    }),
  }),
  adopt: route({
    method: "POST",
    input: writeArtifact(
      z.strictObject({
        previewId: projectUuid,
        toRevisionId: projectUuid,
        confirm: z.boolean(),
      }),
    ),
    output: receiptSchema,
    path: (input) => `${artifactBase(input)}/adoptions`,
    mutating: true,
    body: (input) => input.command,
  }),
  confirm: route({
    method: "POST",
    input: writeArtifact(
      z.strictObject({
        revisionId: projectUuid,
        checkIds: z.array(projectUuid).min(1).max(1000),
      }),
    ),
    output: receiptSchema,
    path: (input) => `${artifactBase(input)}/confirmations`,
    mutating: true,
    body: (input) => input.command,
  }),
  undo: route({
    method: "POST",
    input: projectInput
      .extend({
        adoptionId: projectUuid,
        command: command(z.strictObject({ adoptionId: projectUuid })),
      })
      .refine((input) => input.adoptionId === input.command.payload.adoptionId),
    output: receiptSchema,
    path: (input) => `${base(input)}/adoptions/${input.adoptionId}/undo`,
    mutating: true,
    body: (input) => input.command,
  }),
  runChecks: route({
    method: "POST",
    input: projectInput.extend({
      command: command(
        z.strictObject({
          revisionIds: z.array(projectUuid).min(1).max(1000),
          ruleIds: z
            .array(z.enum(["structural", "references"]))
            .min(1)
            .max(200),
        }),
      ),
    }),
    output: receiptSchema,
    path: (input) => `${base(input)}/local-checks`,
    mutating: true,
    body: (input) => input.command,
  }),
  report: route({
    method: "GET",
    input: projectInput.extend({ checkId: projectUuid }),
    output: checkReportSchema,
    path: (input) => `${base(input)}/check-reports/${input.checkId}`,
    mutating: false,
  }),
};

export type VersionsBridge = {
  [K in keyof typeof versionRoutes]: (
    input: z.infer<(typeof versionRoutes)[K]["input"]>,
  ) => Promise<ProjectResult<z.infer<(typeof versionRoutes)[K]["output"]>>>;
};
export type ArtifactState = z.infer<typeof artifactStateSchema>;
export type Revision = z.infer<typeof revisionSchema>;
export type Impact = z.infer<typeof impactSchema>;
export type CheckReport = z.infer<typeof checkReportSchema>;
