import { dialog, ipcMain, type BrowserWindow } from "electron";
import { basename } from "node:path";
import { existsSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { z } from "zod";
import { RuntimeError } from "../../shared/runtime";
import {
  projectError,
  receiptSchema,
  type ProjectSession,
} from "../../shared/projects";
import { productionRoutes, chooseTargetSchema } from "../../shared/production";
import type { RuntimeSupervisor } from "../runtime/supervisor";
import { isTrustedSender } from "../security";
import { businessRequest } from "./client";

export function installProductionIpc(
  window: BrowserWindow,
  supervisor: RuntimeSupervisor,
  development: boolean,
  getCurrent: () => ProjectSession | null,
): () => void {
  const channels = [...Object.keys(productionRoutes), "chooseTarget"];
  for (const name of channels)
    ipcMain.handle(`production:${name}`, async (event, ...args: unknown[]) => {
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
        if (args.length !== 1) throw new RuntimeError("REQUEST_INVALID");
        const current = getCurrent();
        if (name === "chooseTarget") {
          const input = chooseTargetSchema.parse(args[0]);
          if (
            input.purpose === "export" &&
            (!current || current.mode !== "write")
          )
            throw new RuntimeError("PROJECT_READ_ONLY");
          const selected = await dialog.showSaveDialog(window, {
            title:
              input.purpose === "export"
                ? "保存 MP4 成片"
                : "保存本地诊断包（请选择未使用的文件名）",
            defaultPath: input.purpose === "export" ? "成片.mp4" : "诊断.zip",
            properties: ["showOverwriteConfirmation", "dontAddToRecent"],
            filters: [
              {
                name: input.purpose === "export" ? "MP4视频" : "ZIP诊断包",
                extensions: [input.purpose === "export" ? "mp4" : "zip"],
              },
            ],
          });
          if (selected.canceled || !selected.filePath)
            return { ok: true, data: null };
          if (
            current &&
            getCurrent()?.projectSessionId !== current.projectSessionId
          )
            throw new RuntimeError("SESSION_EXPIRED");
          const grantId = randomUUID();
          await supervisor.withConnection((endpoint, signal) =>
            businessRequest(endpoint, signal, {
              method: "POST",
              path: "/api/v1/file-grants",
              schema: receiptSchema,
              windowId: window.webContents.id,
              body: {
                clientOperationId: randomUUID(),
                expectedRevision: 0,
                payload: {
                  grantId,
                  path: selected.filePath,
                  purpose:
                    input.purpose === "export" ? "exportFilm" : "diagnostic",
                  windowId: window.webContents.id,
                },
              },
            }),
          );
          return {
            ok: true,
            data: {
              grantId,
              name: basename(selected.filePath),
              exists: existsSync(selected.filePath),
            },
          };
        }
        const route = productionRoutes[name as keyof typeof productionRoutes];
        const input = route.input.parse(args[0]);
        const global = "global" in route && route.global;
        if (!global) {
          if (!("projectId" in input) || current?.projectId !== input.projectId)
            throw new RuntimeError("SESSION_EXPIRED");
          if (route.mutating && current.mode !== "write")
            throw new RuntimeError("PROJECT_READ_ONLY");
        }
        const body =
          "body" in route
            ? (route.body as (value: unknown) => unknown)(input)
            : undefined;
        const diagnosticOptions =
          global && body !== undefined
            ? name === "diagnosticPreview"
              ? (body as { includeProject: boolean; projectId: string | null })
              : (
                  body as {
                    payload: {
                      includeProject: boolean;
                      projectId: string | null;
                    };
                  }
                ).payload
            : null;
        const diagnosticProject = diagnosticOptions?.includeProject;
        if (
          diagnosticProject &&
          (!current || diagnosticOptions.projectId !== current.projectId)
        )
          throw new RuntimeError("SESSION_EXPIRED");
        const data = await supervisor.withConnection((endpoint, signal) =>
          businessRequest(endpoint, signal, {
            method: route.method,
            path: route.path(input),
            schema: route.output as z.ZodType,
            body,
            windowId: window.webContents.id,
            sessionId:
              global && !diagnosticProject
                ? undefined
                : current?.projectSessionId,
          }),
        );
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
    for (const name of channels) ipcMain.removeHandler(`production:${name}`);
  };
}
