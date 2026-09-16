import { z } from "zod";
import { projectUuid, receiptSchema, type ProjectResult } from "./projects";
import type { jobSchema } from "./media";
const integer = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
export const providerIdSchema = z
  .string()
  .regex(/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$/);
export const phaseSchema = z.enum([
  "story_adaptation",
  "story_outline",
  "story_scene",
  "story_dialogue",
  "image_character",
  "image_location",
  "image_prop",
  "image_keyframe",
  "video",
  "speech",
  "lipsync",
  "music",
  "sfx",
  "check",
]);
export const capabilityProfileSchema = z.strictObject({
  id: projectUuid,
  providerId: providerIdSchema,
  modelId: z.string().min(1).max(200),
  region: z.string().min(1).max(100),
  version: z.string().min(1).max(100),
  stage: z.enum([
    "story",
    "image",
    "video",
    "speech",
    "lipsync",
    "music",
    "sfx",
    "check",
  ]),
  accountState: z.enum(["unknown", "available", "unavailable"]),
  interfaceState: z.enum(["unverified", "verified", "unavailable"]),
  qualityState: z.enum(["unverified", "research_only", "verified"]),
  enabled: z.boolean(),
  maxReferences: integer.max(16),
  supportedReferenceRoles: z.array(z.string().min(1).max(100)).max(16),
  durationOptionsMs: z.array(integer.min(1)).max(100),
  supportsQuery: z.boolean(),
  supportsCancel: z.boolean(),
  priceSource: z.string().min(1).max(2000),
  priceDate: z.string().min(1).max(40),
  restrictions: z.array(z.string().min(1).max(2000)).max(1000),
  phases: z.array(phaseSchema).min(1).max(14),
  supportsAudioDrive: z.boolean(),
  supportsLipsync: z.boolean(),
  voicePresets: z.array(z.string().min(1).max(200)).max(1000),
  maxInputBytes: integer.min(1).nullable(),
  maxInputCodePoints: integer.min(1).nullable(),
  resultLifetimeSeconds: integer.min(1).nullable(),
  supportsAnonymousResultDownload: z.boolean(),
});
export const settingsSchema = z.strictObject({
  revision: integer,
  providers: z
    .array(
      z.strictObject({
        providerId: providerIdSchema,
        credentialConfigured: z.boolean(),
        maskedSuffix: z.string().length(4).nullable(),
        storageConfigured: z.boolean(),
      }),
    )
    .max(1000),
  ffmpegConfigured: z.boolean(),
  capabilities: z.array(capabilityProfileSchema).max(1000),
});
const persistenceSchema = z.enum(["dpapi", "session_only"]);
export const settingsDetailsSchema = z.strictObject({
  credentials: z
    .array(
      z.strictObject({
        id: projectUuid,
        providerId: providerIdSchema,
        kind: z.enum(["api_key", "oss"]),
        persistence: persistenceSchema,
        maskedSuffix: z.string().length(4),
      }),
    )
    .max(1000),
  storageProfiles: z
    .array(
      z.strictObject({
        id: projectUuid,
        providerId: providerIdSchema,
        region: z.string().min(1).max(100),
        bucket: z.string().min(1).max(100),
        credentialRef: projectUuid,
        retentionHours: integer.min(1).max(168),
        persistence: persistenceSchema,
      }),
    )
    .max(1000),
  toolSummary: z
    .strictObject({
      version: z.string().min(1).max(200),
      h264: z.boolean(),
      aac: z.boolean(),
      subtitles: z.boolean(),
    })
    .nullable(),
});
const command = <T extends z.ZodType>(payload: T) =>
  z.strictObject({
    clientOperationId: projectUuid,
    expectedRevision: integer,
    payload,
  });
export const credentialSecretSchema = z.discriminatedUnion("kind", [
  z.strictObject({
    kind: z.literal("api_key"),
    apiKey: z.string().min(1).max(8192),
  }),
  z.strictObject({
    kind: z.literal("oss"),
    accessKeyId: z.string().min(1).max(256),
    accessKeySecret: z.string().min(1).max(8192),
    securityToken: z.string().min(1).max(16384).nullable(),
  }),
]);
export const setCredentialSchema = z.strictObject({
  providerId: providerIdSchema,
  command: command(
    z.strictObject({
      secret: credentialSecretSchema,
      persistence: persistenceSchema,
    }),
  ),
});
export const deleteCredentialSchema = z.strictObject({
  providerId: providerIdSchema,
  command: command(z.strictObject({ confirmed: z.literal(true) })),
});
export const storageCommandSchema = command(
  z.strictObject({
    providerId: providerIdSchema,
    region: z.string().min(1).max(100),
    bucket: z.string().min(1).max(100),
    credentialRef: projectUuid,
    retentionHours: integer.min(1).max(168),
  }),
);
export const configureStageSchema = z.strictObject({
  projectId: projectUuid,
  command: command(
    z.strictObject({ phase: phaseSchema, capabilityId: projectUuid }),
  ),
});
export const stageModelsSchema = z
  .array(
    z.strictObject({
      phase: phaseSchema,
      capabilityId: projectUuid,
      capabilityVersion: z.string().min(1).max(100),
    }),
  )
  .max(14);
export const connectionCheckSchema = command(
  z.strictObject({ capabilityId: projectUuid }),
);
export const globalJobInputSchema = z.strictObject({ jobId: projectUuid });
export type Settings = z.infer<typeof settingsSchema>;
export type SettingsDetails = z.infer<typeof settingsDetailsSchema>;
export type CapabilityProfile = z.infer<typeof capabilityProfileSchema>;
export type Phase = z.infer<typeof phaseSchema>;
export type CredentialSecret = z.infer<typeof credentialSecretSchema>;
type Receipt = z.infer<typeof receiptSchema>;
export interface SettingsBridge {
  get(): Promise<ProjectResult<Settings>>;
  details(): Promise<ProjectResult<SettingsDetails>>;
  setCredential(
    input: z.infer<typeof setCredentialSchema>,
  ): Promise<ProjectResult<Receipt>>;
  deleteCredential(
    input: z.infer<typeof deleteCredentialSchema>,
  ): Promise<ProjectResult<Receipt>>;
  configureStorage(
    input: z.infer<typeof storageCommandSchema>,
  ): Promise<ProjectResult<Receipt>>;
  configureStage(
    input: z.infer<typeof configureStageSchema>,
  ): Promise<ProjectResult<Receipt>>;
  stageModels(input: {
    projectId: string;
  }): Promise<ProjectResult<z.infer<typeof stageModelsSchema>>>;
  checkConnection(
    input: z.infer<typeof connectionCheckSchema>,
  ): Promise<ProjectResult<Receipt>>;
  job(
    input: z.infer<typeof globalJobInputSchema>,
  ): Promise<ProjectResult<z.infer<typeof jobSchema>>>;
}
