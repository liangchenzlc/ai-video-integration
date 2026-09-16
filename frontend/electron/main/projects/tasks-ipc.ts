import { ipcMain, type BrowserWindow } from "electron";
import { z } from "zod";
import { RuntimeError } from "../../shared/runtime";
import { projectError, type ProjectSession } from "../../shared/projects";
import { taskRoutes } from "../../shared/tasks";
import type { RuntimeSupervisor } from "../runtime/supervisor";
import { isTrustedSender } from "../security";
import { businessRequest } from "./client";
export function installTasksIpc(
  window: BrowserWindow,
  supervisor: RuntimeSupervisor,
  development: boolean,
  getCurrent: () => ProjectSession | null,
): () => void {
  for (const [name, route] of Object.entries(taskRoutes))
    ipcMain.handle(`tasks:${name}`, async (event, ...args: unknown[]) => {
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
        if ("projectId" in input && current?.projectId !== input.projectId)
          throw new RuntimeError("SESSION_EXPIRED");
        if (
          "projectId" in input &&
          route.method !== "GET" &&
          current?.mode !== "write"
        )
          throw new RuntimeError("PROJECT_READ_ONLY");
        const data = await supervisor.withConnection((endpoint, signal) =>
          businessRequest(endpoint, signal, {
            method: route.method,
            path: route.path(input),
            schema: route.output as z.ZodType,
            body: "command" in input ? input.command : undefined,
            windowId: window.webContents.id,
            sessionId:
              "projectId" in input ? current?.projectSessionId : undefined,
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
    for (const name of Object.keys(taskRoutes))
      ipcMain.removeHandler(`tasks:${name}`);
  };
}
