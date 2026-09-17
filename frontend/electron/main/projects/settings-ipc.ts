import { ipcMain, type BrowserWindow } from "electron";
import { z } from "zod";
import { RuntimeError } from "../../shared/runtime";
import {
  projectError,
  receiptSchema,
  type ProjectSession,
} from "../../shared/projects";
import { projectInputSchema } from "../../shared/drafts";
import { jobSchema } from "../../shared/media";
import {
  settingsSchema,
  settingsDetailsSchema,
  setCredentialSchema,
  deleteCredentialSchema,
  storageCommandSchema,
  configureStageSchema,
  stageModelsSchema,
  connectionCheckSchema,
  globalJobInputSchema,
} from "../../shared/settings";
import type { RuntimeSupervisor } from "../runtime/supervisor";
import { isTrustedSender } from "../security";
import { businessRequest } from "./client";
export function installSettingsIpc(
  window: BrowserWindow,
  supervisor: RuntimeSupervisor,
  development: boolean,
  getCurrent: () => ProjectSession | null,
): () => void {
  const channels = [
    "settings:get",
    "settings:details",
    "settings:set-credential",
    "settings:delete-credential",
    "settings:configure-storage",
    "settings:configure-stage",
    "settings:stage-models",
    "settings:check-connection",
    "settings:job",
  ];
  const call = <T>(
    method: "GET" | "POST" | "PUT",
    path: string,
    schema: z.ZodType<T>,
    body?: unknown,
    projectId?: string,
  ) => {
    const current = getCurrent();
    if (projectId && current?.projectId !== projectId)
      throw new RuntimeError("SESSION_EXPIRED");
    if (projectId && method !== "GET" && current?.mode !== "write")
      throw new RuntimeError("PROJECT_READ_ONLY");
    return supervisor.withConnection((endpoint, signal) =>
      businessRequest(endpoint, signal, {
        method,
        path,
        schema,
        body,
        windowId: window.webContents.id,
        sessionId: projectId ? current?.projectSessionId : undefined,
      }),
    );
  };
  for (const channel of channels)
    ipcMain.handle(channel, async (event, ...args: unknown[]) => {
      try {
        if (
          window.isDestroyed() ||
          !isTrustedSender(
            event.sender.id,
            window.webContents.id,
            event.senderFrame === window.webContents.mainFrame,
            event.senderFrame?.url ?? "",
            development,
          )
        )
          throw new RuntimeError("SOURCE_REJECTED");
        if (
          args.length !==
          (["settings:get", "settings:details"].includes(channel) ? 0 : 1)
        )
          throw new RuntimeError("REQUEST_INVALID");
        let data: unknown;
        if (channel === "settings:get")
          data = await call("GET", "/api/v1/settings", settingsSchema);
        else if (channel === "settings:details")
          data = await call(
            "GET",
            "/api/v1/settings/details",
            settingsDetailsSchema,
          );
        else if (channel === "settings:set-credential") {
          const input = setCredentialSchema.parse(args[0]);
          data = await call(
            "PUT",
            `/api/v1/credentials/${input.providerId}`,
            receiptSchema,
            input.command,
          );
        } else if (channel === "settings:delete-credential") {
          const input = deleteCredentialSchema.parse(args[0]);
          data = await call(
            "POST",
            `/api/v1/credentials/${input.providerId}/delete`,
            receiptSchema,
            input.command,
          );
        } else if (channel === "settings:configure-storage")
          data = await call(
            "PUT",
            "/api/v1/settings/storage",
            receiptSchema,
            storageCommandSchema.parse(args[0]),
          );
        else if (channel === "settings:configure-stage") {
          const input = configureStageSchema.parse(args[0]);
          data = await call(
            "PUT",
            `/api/v1/projects/${input.projectId}/stage-models`,
            receiptSchema,
            input.command,
            input.projectId,
          );
        } else if (channel === "settings:stage-models") {
          const input = projectInputSchema.parse(args[0]);
          data = await call(
            "GET",
            `/api/v1/projects/${input.projectId}/stage-models`,
            stageModelsSchema,
            undefined,
            input.projectId,
          );
        } else if (channel === "settings:check-connection")
          data = await call(
            "POST",
            "/api/v1/connection-checks",
            receiptSchema,
            connectionCheckSchema.parse(args[0]),
          );
        else {
          const input = globalJobInputSchema.parse(args[0]);
          data = await call("GET", `/api/v1/jobs/${input.jobId}`, jobSchema);
        }
        return { ok: true, data };
      } catch (error) {
        return {
          ok: false,
          error: projectError(
            error instanceof RuntimeError
              ? error.code
              : error instanceof z.ZodError
                ? "REQUEST_INVALID"
                : "BACKEND_UNAVAILABLE",
          ),
        };
      }
    });
  return () => {
    for (const channel of channels) ipcMain.removeHandler(channel);
  };
}
