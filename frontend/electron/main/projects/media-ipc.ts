import { dialog, ipcMain, type BrowserWindow } from "electron";
import { basename } from "node:path";
import { randomUUID } from "node:crypto";
import { z } from "zod";
import { RuntimeError } from "../../shared/runtime";
import {
  projectError,
  receiptSchema,
  type ProjectSession,
} from "../../shared/projects";
import { projectInputSchema } from "../../shared/drafts";
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
} from "../../shared/media";
import type { RuntimeSupervisor } from "../runtime/supervisor";
import { isTrustedSender } from "../security";
import { businessRequest } from "./client";

export function installMediaIpc(
  window: BrowserWindow,
  supervisor: RuntimeSupervisor,
  development: boolean,
  getCurrent: () => ProjectSession | null,
): () => void {
  const channels = [
    "media:choose",
    "media:settings",
    "media:configure",
    "media:import",
    "media:list",
    "media:metadata",
    "media:jobs",
    "media:job",
    "media:cancel",
    "media:relocate",
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
        if (args.length !== (channel === "media:settings" ? 0 : 1))
          throw new RuntimeError("REQUEST_INVALID");
        let data: unknown;
        if (channel === "media:choose") {
          const input = chooseFileSchema.parse(args[0]);
          const selected = await dialog.showOpenDialog(window, {
            title:
              input.purpose === "ffmpeg"
                ? "选择本机 FFmpeg 可执行文件"
                : "选择要复制到项目的素材",
            properties: ["openFile", "dontAddToRecent"],
            filters:
              input.purpose === "ffmpeg"
                ? [{ name: "FFmpeg", extensions: ["exe"] }]
                : [
                    {
                      name: "图片、音频与视频",
                      extensions: [
                        "png",
                        "jpg",
                        "jpeg",
                        "mp4",
                        "wav",
                        "mp3",
                        "m4a",
                      ],
                    },
                  ],
          });
          if (selected.canceled || !selected.filePaths[0]) data = null;
          else {
            const grantId = randomUUID();
            await call("POST", "/api/v1/file-grants", receiptSchema, {
              clientOperationId: randomUUID(),
              expectedRevision: 0,
              payload: {
                grantId,
                path: selected.filePaths[0],
                purpose: input.purpose,
                windowId: window.webContents.id,
              },
            });
            data = { grantId, name: basename(selected.filePaths[0]) };
          }
        } else if (channel === "media:settings")
          data = await call("GET", "/api/v1/settings", toolSettingsSchema);
        else if (channel === "media:configure")
          data = await call(
            "PUT",
            "/api/v1/settings/media-tools",
            receiptSchema,
            toolsCommandSchema.parse(args[0]),
          );
        else if (channel === "media:import") {
          const input = importMediaSchema.parse(args[0]);
          data = await call(
            "POST",
            `/api/v1/projects/${input.projectId}/imports`,
            receiptSchema,
            input.command,
            input.projectId,
          );
        } else if (channel === "media:list") {
          const input = mediaListInputSchema.parse(args[0]);
          const query = `?limit=${input.limit ?? 50}${input.cursor ? `&cursor=${input.cursor}` : ""}`;
          data = await call(
            "GET",
            `/api/v1/projects/${input.projectId}/media${query}`,
            mediaPageSchema,
            undefined,
            input.projectId,
          );
        } else if (channel === "media:metadata") {
          const input = mediaIdSchema.parse(args[0]);
          data = await call(
            "GET",
            `/api/v1/projects/${input.projectId}/media/${input.mediaId}/metadata`,
            mediaSchema,
            undefined,
            input.projectId,
          );
        } else if (channel === "media:jobs") {
          const input = projectInputSchema.parse(args[0]);
          data = await call(
            "GET",
            `/api/v1/projects/${input.projectId}/jobs`,
            z.array(jobSchema).max(50),
            undefined,
            input.projectId,
          );
        } else if (channel === "media:job") {
          const input = jobIdSchema.parse(args[0]);
          data = await call(
            "GET",
            `/api/v1/projects/${input.projectId}/jobs/${input.jobId}`,
            jobSchema,
            undefined,
            input.projectId,
          );
        } else if (channel === "media:cancel") {
          const input = cancelJobSchema.parse(args[0]);
          data = await call(
            "POST",
            `/api/v1/projects/${input.projectId}/jobs/${input.jobId}/cancel`,
            receiptSchema,
            input.command,
            input.projectId,
          );
        } else {
          const input = relocateMediaSchema.parse(args[0]);
          data = await call(
            "POST",
            `/api/v1/projects/${input.projectId}/media/${input.mediaId}/relocate`,
            receiptSchema,
            input.command,
            input.projectId,
          );
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
