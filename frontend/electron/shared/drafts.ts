import { z } from "zod";
import {
  projectUuid,
  receiptSchema,
  operationSchema,
  projectSchema,
  type ProjectResult,
} from "./projects";

const revision = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
const kind = z.enum([
  "story",
  "asset",
  "shot",
  "speech",
  "subtitle",
  "timeline",
  "observation",
]);
export const draftContentSchema = z.strictObject({
  kind,
  content: z.record(z.string(), z.json()),
});
export const draftSchema = z.strictObject({
  id: projectUuid,
  artifactId: projectUuid,
  baseRevisionId: projectUuid.nullable(),
  content: draftContentSchema,
});
export const draftListSchema = z
  .array(
    z.strictObject({
      id: projectUuid,
      artifactId: projectUuid,
      kind,
      savedAt: z.string(),
    }),
  )
  .max(50);
export const projectInputSchema = z.strictObject({ projectId: projectUuid });
export const draftInputSchema = z.strictObject({
  projectId: projectUuid,
  draftId: projectUuid,
});
export const projectOperationInputSchema = z.strictObject({
  projectId: projectUuid,
  operationId: projectUuid,
});
export const saveDraftSchema = z.strictObject({
  projectId: projectUuid,
  command: z.strictObject({
    clientOperationId: projectUuid,
    expectedRevision: revision,
    payload: z.strictObject({
      draftId: projectUuid,
      artifactId: projectUuid,
      baseRevisionId: projectUuid.nullable(),
      content: draftContentSchema,
    }),
  }),
});
export type Draft = z.infer<typeof draftSchema>;
export type SaveDraft = z.infer<typeof saveDraftSchema>;
export interface DraftsBridge {
  save(input: SaveDraft): Promise<ProjectResult<z.infer<typeof receiptSchema>>>;
  get(input: z.infer<typeof draftInputSchema>): Promise<ProjectResult<Draft>>;
  list(
    input: z.infer<typeof projectInputSchema>,
  ): Promise<ProjectResult<z.infer<typeof draftListSchema>>>;
  project(
    input: z.infer<typeof projectInputSchema>,
  ): Promise<ProjectResult<z.infer<typeof projectSchema>>>;
  operation(
    input: z.infer<typeof projectOperationInputSchema>,
  ): Promise<ProjectResult<z.infer<typeof operationSchema>>>;
}
