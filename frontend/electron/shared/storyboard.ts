import { z } from "zod";
import { projectUuid, receiptSchema, type ProjectResult } from "./projects";

const integer = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
export const referenceRoleSchema = z.enum([
  "identity",
  "style",
  "location",
  "prop",
  "composition",
  "firstFrame",
  "keyMoment",
  "endFrame",
  "voiceDrive",
  "voiceReference",
]);
export const storyboardSchema = z.strictObject({
  drafts: z
    .array(
      z.strictObject({
        id: projectUuid,
        artifactId: projectUuid,
        kind: z.enum(["story", "asset", "shot"]),
        savedAt: z.string().min(1).max(40),
      }),
    )
    .max(5000),
  shotIds: z.array(projectUuid).max(5000),
});
export const coverageSchema = z.strictObject({
  unassignedRequirementIds: z.array(projectUuid).max(1000),
  unresolvedRequirementIds: z.array(projectUuid).max(1000),
  invalidReferenceIds: z.array(projectUuid).max(1000),
});
export const promptPreviewSchema = z.strictObject({
  templateId: z.string().min(1).max(100),
  templateVersion: z.string().min(1).max(100),
  prompt: z.string().max(100000),
  sourceRevisionIds: z.array(projectUuid).max(1000),
  blockers: z.array(z.string().max(2000)).max(100),
  reusableVideoMediaId: projectUuid.nullable(),
});
const projectInput = z.strictObject({ projectId: projectUuid });
const write = <T extends z.ZodType>(payload: T) =>
  projectInput.extend({
    command: z.strictObject({
      clientOperationId: projectUuid,
      expectedRevision: integer,
      payload,
    }),
  });
const base = (input: Record<string, unknown>) =>
  `/api/v1/projects/${input.projectId}`;
const route = <I extends z.ZodType, O extends z.ZodType>(options: {
  method: "GET" | "POST" | "PUT";
  input: I;
  output: O;
  mutating: boolean;
  path: (input: Record<string, unknown>) => string;
  body?: (input: z.infer<I>) => unknown;
}) => options;

export const storyboardRoutes = {
  list: route({
    method: "GET",
    input: projectInput,
    output: storyboardSchema,
    path: (input) => `${base(input)}/storyboard`,
    mutating: false,
  }),
  coverage: route({
    method: "GET",
    input: projectInput,
    output: coverageSchema,
    path: (input) => `${base(input)}/coverage`,
    mutating: false,
  }),
  reorder: route({
    method: "PUT",
    input: write(
      z.strictObject({
        shotIds: z
          .array(projectUuid)
          .min(1)
          .max(5000)
          .refine((ids) => new Set(ids).size === ids.length),
      }),
    ),
    output: receiptSchema,
    path: (input) => `${base(input)}/shot-order`,
    mutating: true,
    body: (input) => input.command,
  }),
  verify: route({
    method: "POST",
    input: write(
      z.strictObject({
        draftId: projectUuid,
        mediaId: projectUuid,
        role: referenceRoleSchema,
        matchesPurpose: z.boolean(),
        note: z.string().min(1).max(2000),
      }),
    ),
    output: receiptSchema,
    path: (input) => `${base(input)}/references/verification`,
    mutating: true,
    body: (input) => input.command,
  }),
  prompt: route({
    method: "GET",
    input: projectInput.extend({
      shotId: projectUuid,
      phase: z.enum(["image", "video"]),
    }),
    output: promptPreviewSchema,
    path: (input) =>
      `${base(input)}/storyboard/shots/${input.shotId}/prompt?phase=${input.phase}`,
    mutating: false,
  }),
};
export type Storyboard = z.infer<typeof storyboardSchema>;
export type Coverage = z.infer<typeof coverageSchema>;
export type PromptPreview = z.infer<typeof promptPreviewSchema>;
export type StoryboardBridge = {
  [K in keyof typeof storyboardRoutes]: (
    input: z.infer<(typeof storyboardRoutes)[K]["input"]>,
  ) => Promise<ProjectResult<z.infer<(typeof storyboardRoutes)[K]["output"]>>>;
};
