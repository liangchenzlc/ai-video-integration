import { settingsSchema } from "./settings";
import { z } from "zod";
import { projectUuid, receiptSchema, type ProjectResult } from "./projects";

const integer = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
export const toolSettingsSchema = settingsSchema;
export const mediaSchema = z.strictObject({
  id: projectUuid,
  sha256: z.string().regex(/^[0-9a-f]{64}$/),
  byteLength: integer.min(1).max(2 * 1024 ** 3),
  mime: z.enum([
    "image/png",
    "image/jpeg",
    "video/mp4",
    "audio/wav",
    "audio/mpeg",
    "audio/mp4",
  ]),
  durationMs: integer.min(1).nullable(),
  width: integer.min(1).nullable(),
  height: integer.min(1).nullable(),
  availability: z.enum(["staging", "available", "missing", "quarantined"]),
  provenance: z.enum(["imported", "generated", "derived", "synthetic"]),
});
export const mediaPageSchema = z.strictObject({
  items: z.array(mediaSchema).max(200),
  nextCursor: projectUuid.nullable(),
});
export const jobSchema = z.strictObject({
  id: projectUuid,
  kind: z.enum([
    "import",
    "probe",
    "animatic",
    "export",
    "diagnostic",
    "local_check",
    "connection_check",
  ]),
  state: z.enum(["queued", "running", "succeeded", "failed", "cancelled"]),
  progress: z.number().min(0).max(1),
  resultId: projectUuid.nullable(),
  errorCode: z.string().max(100).nullable(),
});
export const chooseFileSchema = z.strictObject({
  purpose: z.enum(["importMedia", "ffmpeg"]),
});
export const mediaListInputSchema = z.strictObject({
  projectId: projectUuid,
  cursor: projectUuid.nullable().optional(),
  limit: z.number().int().min(1).max(200).optional(),
});
export const mediaIdSchema = z.strictObject({
  projectId: projectUuid,
  mediaId: projectUuid,
});
export const jobIdSchema = z.strictObject({
  projectId: projectUuid,
  jobId: projectUuid,
});
const command = <T extends z.ZodType>(payload: T) =>
  z.strictObject({
    clientOperationId: projectUuid,
    expectedRevision: integer,
    payload,
  });
export const toolsCommandSchema = command(
  z.strictObject({ ffmpegGrantId: projectUuid }),
);
export const importMediaSchema = z.strictObject({
  projectId: projectUuid,
  command: command(
    z.strictObject({
      fileGrantId: projectUuid,
      purpose: z.enum([
        "reference",
        "speech",
        "video",
        "music",
        "sfx",
        "evidence",
      ]),
    }),
  ),
});
export const relocateMediaSchema = z.strictObject({
  projectId: projectUuid,
  mediaId: projectUuid,
  command: command(
    z.strictObject({
      fileGrantId: projectUuid,
      expectedHash: z.string().regex(/^[0-9a-f]{64}$/),
    }),
  ),
});
export const cancelJobSchema = z.strictObject({
  projectId: projectUuid,
  jobId: projectUuid,
  command: command(z.strictObject({ reason: z.string().min(1).max(500) })),
});
export type Media = z.infer<typeof mediaSchema>;
export type MediaJob = z.infer<typeof jobSchema>;
export type ToolSettings = z.infer<typeof toolSettingsSchema>;
export type ImportMedia = z.infer<typeof importMediaSchema>;
export type RelocateMedia = z.infer<typeof relocateMediaSchema>;
export type ConfigureTools = z.infer<typeof toolsCommandSchema>;
type Receipt = z.infer<typeof receiptSchema>;
export interface MediaBridge {
  chooseFile(
    input: z.infer<typeof chooseFileSchema>,
  ): Promise<ProjectResult<{ grantId: string; name: string } | null>>;
  settings(): Promise<ProjectResult<ToolSettings>>;
  configureTools(input: ConfigureTools): Promise<ProjectResult<Receipt>>;
  import(input: ImportMedia): Promise<ProjectResult<Receipt>>;
  list(
    input: z.infer<typeof mediaListInputSchema>,
  ): Promise<ProjectResult<z.infer<typeof mediaPageSchema>>>;
  metadata(input: z.infer<typeof mediaIdSchema>): Promise<ProjectResult<Media>>;
  jobs(input: { projectId: string }): Promise<ProjectResult<MediaJob[]>>;
  job(input: z.infer<typeof jobIdSchema>): Promise<ProjectResult<MediaJob>>;
  cancel(
    input: z.infer<typeof cancelJobSchema>,
  ): Promise<ProjectResult<Receipt>>;
  relocate(input: RelocateMedia): Promise<ProjectResult<Receipt>>;
}
