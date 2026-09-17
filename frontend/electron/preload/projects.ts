import { ipcRenderer } from "electron";
import { z } from "zod";
import {
  chooseDirectorySchema,
  directoryChoiceSchema,
  createProjectSchema,
  receiptSchema,
  openProjectSchema,
  sessionSchema,
  recentInputSchema,
  recentSchema,
  closedSchema,
  operationInputSchema,
  operationSchema,
  projectError,
  projectSchema,
  type ProjectResult,
  type ProjectsBridge,
} from "../shared/projects";
import {
  draftSchema,
  draftListSchema,
  draftInputSchema,
  projectInputSchema,
  projectOperationInputSchema,
  saveDraftSchema,
} from "../shared/drafts";
import {
  chooseFileSchema,
  toolSettingsSchema,
  toolsCommandSchema,
  importMediaSchema,
  mediaListInputSchema,
  mediaIdSchema,
  mediaPageSchema,
  mediaSchema,
  jobIdSchema,
  jobSchema,
  cancelJobSchema,
  relocateMediaSchema,
} from "../shared/media";

export async function invoke<T>(
  channel: string,
  schema: z.ZodType<T>,
  args: unknown[] = [],
): Promise<ProjectResult<T>> {
  try {
    const value: unknown = await ipcRenderer.invoke(channel, ...args);
    const success = z
      .strictObject({ ok: z.literal(true), data: schema })
      .safeParse(value);
    if (success.success) return success.data;
    const failure = z
      .strictObject({
        ok: z.literal(false),
        error: z.strictObject({
          code: z.string(),
          message: z.string().max(256),
        }),
      })
      .safeParse(value);
    if (failure.success)
      return { ok: false, error: projectError(failure.data.error.code) };
  } catch {
    /* Never expose Electron events or raw transport exceptions. */
  }
  return { ok: false, error: projectError("BACKEND_UNAVAILABLE") };
}
export function checked<I, T>(
  channel: string,
  input: unknown,
  inputSchema: z.ZodType<I>,
  outputSchema: z.ZodType<T>,
): Promise<ProjectResult<T>> {
  const parsed = inputSchema.safeParse(input);
  return parsed.success
    ? invoke(channel, outputSchema, [parsed.data])
    : Promise.resolve({ ok: false, error: projectError("REQUEST_INVALID") });
}
export const projectsBridge: ProjectsBridge = Object.freeze({
  media: Object.freeze({
    chooseFile: (input: unknown) =>
      checked("media:choose", input, chooseFileSchema, directoryChoiceSchema),
    settings: () => invoke("media:settings", toolSettingsSchema),
    configureTools: (input: unknown) =>
      checked("media:configure", input, toolsCommandSchema, receiptSchema),
    import: (input: unknown) =>
      checked("media:import", input, importMediaSchema, receiptSchema),
    list: (input: unknown) =>
      checked("media:list", input, mediaListInputSchema, mediaPageSchema),
    metadata: (input: unknown) =>
      checked("media:metadata", input, mediaIdSchema, mediaSchema),
    jobs: (input: unknown) =>
      checked(
        "media:jobs",
        input,
        projectInputSchema,
        z.array(jobSchema).max(50),
      ),
    job: (input: unknown) =>
      checked("media:job", input, jobIdSchema, jobSchema),
    cancel: (input: unknown) =>
      checked("media:cancel", input, cancelJobSchema, receiptSchema),
    relocate: (input: unknown) =>
      checked("media:relocate", input, relocateMediaSchema, receiptSchema),
  }),
  drafts: Object.freeze({
    save: (input: unknown) =>
      checked("drafts:save", input, saveDraftSchema, receiptSchema),
    get: (input: unknown) =>
      checked("drafts:get", input, draftInputSchema, draftSchema),
    list: (input: unknown) =>
      checked("drafts:list", input, projectInputSchema, draftListSchema),
    project: (input: unknown) =>
      checked("drafts:project", input, projectInputSchema, projectSchema),
    operation: (input: unknown) =>
      checked(
        "drafts:operation",
        input,
        projectOperationInputSchema,
        operationSchema,
      ),
  }),
  chooseDirectory: (input: unknown) =>
    checked(
      "projects:choose",
      input,
      chooseDirectorySchema,
      directoryChoiceSchema,
    ),
  create: (input: unknown) =>
    checked("projects:create", input, createProjectSchema, receiptSchema),
  open: (input: unknown) =>
    checked("projects:open", input, openProjectSchema, sessionSchema),
  openRecent: (input: unknown) =>
    checked("projects:open-recent", input, recentInputSchema, sessionSchema),
  recent: () => invoke("projects:recent", recentSchema),
  current: () => invoke("projects:current", sessionSchema.nullable()),
  close: () => invoke("projects:close", closedSchema),
  operation: (input: unknown) =>
    checked("projects:operation", input, operationInputSchema, operationSchema),
});
