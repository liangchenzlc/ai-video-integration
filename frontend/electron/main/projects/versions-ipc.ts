import { ipcMain, type BrowserWindow } from "electron";
import { z } from "zod";
import { RuntimeError } from "../../shared/runtime";
import { projectError, type ProjectSession } from "../../shared/projects";
import { versionRoutes } from "../../shared/versions";
import type { RuntimeSupervisor } from "../runtime/supervisor";
import { isTrustedSender } from "../security";
import { businessRequest } from "./client";

export function installVersionsIpc(
  window: BrowserWindow,
  supervisor: RuntimeSupervisor,
  development: boolean,
  getCurrent: () => ProjectSession | null,
): () => void {
  for (const [name, route] of Object.entries(versionRoutes))
    ipcMain.handle(`versions:${name}`, async (event, ...args: unknown[]) => {
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
        const input = route.input.parse(args[0]);
        const current = getCurrent();
        if (current?.projectId !== input.projectId)
          throw new RuntimeError("SESSION_EXPIRED");
        if (route.mutating && current.mode !== "write")
          throw new RuntimeError("PROJECT_READ_ONLY");
        const buildPath = route.path as (
          value: Record<string, unknown>,
        ) => string;
        const buildBody = route.body as
          ((value: unknown) => unknown) | undefined;
        const data = await supervisor.withConnection((endpoint, signal) =>
          businessRequest(endpoint, signal, {
            method: route.method,
            path: buildPath(input),
            schema: route.output as z.ZodType,
            body: buildBody?.(input),
            windowId: window.webContents.id,
            sessionId: current.projectSessionId,
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
    for (const name of Object.keys(versionRoutes))
      ipcMain.removeHandler(`versions:${name}`);
  };
}
