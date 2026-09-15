import { z } from "zod";
export const recoverySchema = z.enum([
  "none",
  "retry_connection",
  "restart_backend",
  "repair_installation",
]);
export const snapshotSchema = z.strictObject({
  state: z.enum([
    "stopped",
    "starting",
    "ready",
    "disconnected",
    "stopping",
    "failed",
    "incompatible",
  ]),
  runtimeId: z.string().uuid().nullable(),
  generation: z.number().int().min(0).max(2147483647),
  revision: z.number().int().nonnegative(),
  frontendVersion: z.string(),
  backendVersion: z.string().nullable(),
  errorCode: z.string().nullable(),
  recoverableAction: recoverySchema,
  canRestart: z.boolean(),
});
export const restartSchema = z.strictObject({
  expectedGeneration: z.number().int().min(0).max(2147483647),
});
export const helpSchema = z.strictObject({ helpId: z.literal("runtime-help") });
export const capabilitySchema = z.strictObject({
  runtimeId: z.string().uuid(),
  generation: z.number().int().positive(),
  capabilities: z
    .array(
      z.strictObject({
        id: z.enum([
          "runtime",
          "projects",
          "credentials",
          "story",
          "visualAssets",
          "storyboard",
          "video",
          "audio",
          "timeline",
          "checks",
          "exports",
          "costs",
        ]),
        enabled: z.boolean(),
        reasonCode: z.enum(["AVAILABLE", "NOT_IMPLEMENTED"]),
      }),
    )
    .length(12),
});
export const bridgeErrorSchema = z.strictObject({
  ok: z.literal(false),
  error: z.strictObject({
    code: z.string(),
    message: z.string(),
    recoverableAction: recoverySchema,
  }),
});
