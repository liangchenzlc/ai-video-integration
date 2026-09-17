import { dialog, ipcMain, type BrowserWindow } from "electron";
import { basename } from "node:path";
import { randomUUID } from "node:crypto";
import { z } from "zod";
import { RuntimeError } from "../../shared/runtime";
import { isTrustedSender } from "../security";
import type { RuntimeSupervisor } from "../runtime/supervisor";
import { businessRequest } from "./client";
import {
  chooseDirectorySchema,
  createProjectSchema,
  openProjectSchema,
  recentInputSchema,
  operationInputSchema,
  operationSchema,
  receiptSchema,
  sessionSchema,
  recentSchema,
  closedSchema,
  projectError,
  type ProjectSession,
  projectSchema,
} from "../../shared/projects";
import {
  draftSchema,
  draftListSchema,
  draftInputSchema,
  projectInputSchema,
  projectOperationInputSchema,
  saveDraftSchema,
} from "../../shared/drafts";

export function installProjectIpc(
  window: BrowserWindow,
  supervisor: RuntimeSupervisor,
  development: boolean,
): { dispose: () => void; current: () => ProjectSession | null } {
  let current: ProjectSession | null = null;
  let runtimeId: string | null = supervisor.snapshot().runtimeId;
  let busy = false;
  const pendingReleases = new Set<string>();
  const commands = [
    "projects:choose",
    "projects:create",
    "projects:open",
    "projects:open-recent",
    "projects:recent",
    "projects:current",
    "projects:close",
    "projects:operation",
    "drafts:save",
    "drafts:get",
    "drafts:list",
    "drafts:project",
    "drafts:operation",
  ];
  const call = <T>(
    method: "GET" | "POST" | "PUT" | "DELETE",
    path: string,
    schema: z.ZodType<T>,
    body?: unknown,
  ) =>
    supervisor.withConnection((endpoint, signal) =>
      businessRequest(endpoint, signal, {
        method,
        path,
        schema,
        body,
        windowId: window.webContents.id,
        sessionId: current?.projectSessionId,
      }),
    );
  async function closeCurrent() {
    if (current)
      await call(
        "DELETE",
        `/api/v1/project-sessions/${current.projectSessionId}`,
        closedSchema,
      );
    current = null;
    await releasePending();
  }
  async function releasePending() {
    for (const id of pendingReleases) {
      if (id === current?.projectSessionId) {
        pendingReleases.delete(id);
        continue;
      }
      try {
        await call("DELETE", `/api/v1/project-sessions/${id}`, closedSchema);
        pendingReleases.delete(id);
      } catch {
        /* Retain the exact ID for a later idempotent close; never lose the handle. */
      }
    }
  }
  async function register(
    path: string,
    purpose: "createProject" | "openProject",
  ) {
    const grantId = randomUUID();
    await call("POST", "/api/v1/file-grants", receiptSchema, {
      clientOperationId: randomUUID(),
      expectedRevision: 0,
      payload: { grantId, path, purpose, windowId: window.webContents.id },
    });
    return grantId;
  }
  async function open(
    input: z.infer<typeof openProjectSchema>,
    expectedProjectId?: string,
  ) {
    const openingRuntimeId = supervisor.snapshot().runtimeId;
    const verifyRuntime = () => {
      const snapshot = supervisor.snapshot();
      if (
        snapshot.state !== "ready" ||
        snapshot.runtimeId !== openingRuntimeId
      ) {
        if (snapshot.runtimeId !== openingRuntimeId) {
          current = null;
          runtimeId = snapshot.runtimeId;
          pendingReleases.clear();
        }
        throw new RuntimeError(
          snapshot.state === "ready" ? "STALE_RUNTIME" : "BACKEND_UNAVAILABLE",
        );
      }
    };
    const previous = current;
    const opened = await call(
      "POST",
      "/api/v1/project-sessions",
      sessionSchema,
      input,
    );
    verifyRuntime();
    if (expectedProjectId && opened.projectId !== expectedProjectId) {
      if (opened.projectSessionId !== previous?.projectSessionId)
        pendingReleases.add(opened.projectSessionId);
      await releasePending();
      verifyRuntime();
      throw new RuntimeError("PROJECT_NOT_FOUND");
    }
    current = opened;
    runtimeId = openingRuntimeId;
    if (previous && previous.projectSessionId !== opened.projectSessionId)
      pendingReleases.add(previous.projectSessionId);
    await releasePending();
    verifyRuntime();
    return opened;
  }
  for (const channel of commands)
    ipcMain.handle(channel, async (event, ...args: unknown[]) => {
      const mutating =
        !channel.startsWith("drafts:") &&
        !["projects:recent", "projects:current", "projects:operation"].includes(
          channel,
        );
      let ownsBusy = false;
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
        if (runtimeId !== supervisor.snapshot().runtimeId) {
          current = null;
          runtimeId = supervisor.snapshot().runtimeId;
          pendingReleases.clear();
        }
        if (mutating) {
          if (busy) throw new RuntimeError("REQUEST_INVALID");
          busy = true;
          ownsBusy = true;
        }
        let data: unknown;
        if (channel.startsWith("drafts:")) {
          if (args.length !== 1) throw new RuntimeError("REQUEST_INVALID");
          const input = (
            channel === "drafts:save"
              ? saveDraftSchema
              : channel === "drafts:get"
                ? draftInputSchema
                : channel === "drafts:operation"
                  ? projectOperationInputSchema
                  : projectInputSchema
          ).parse(args[0]);
          if (!current || input.projectId !== current.projectId)
            throw new RuntimeError("SESSION_EXPIRED");
          const base = `/api/v1/projects/${input.projectId}`;
          if (channel === "drafts:save") {
            const save = saveDraftSchema.parse(args[0]);
            data = await call(
              "PUT",
              `${base}/drafts/${save.command.payload.draftId}`,
              receiptSchema,
              save.command,
            );
          } else if ("draftId" in input)
            data = await call(
              "GET",
              `${base}/drafts/${input.draftId}`,
              draftSchema,
            );
          else if ("operationId" in input)
            data = await call(
              "GET",
              `${base}/operations/${input.operationId}`,
              operationSchema,
            );
          else
            data =
              channel === "drafts:list"
                ? await call("GET", `${base}/drafts`, draftListSchema)
                : await call("GET", base, projectSchema);
        } else if (
          ["projects:recent", "projects:current", "projects:close"].includes(
            channel,
          )
        ) {
          if (args.length) throw new RuntimeError("REQUEST_INVALID");
          if (channel === "projects:recent")
            data = await call("GET", "/api/v1/recent-projects", recentSchema);
          else if (channel === "projects:current") data = current;
          else {
            await closeCurrent();
            data = { closed: true };
          }
        } else {
          if (args.length !== 1) throw new RuntimeError("REQUEST_INVALID");
          if (channel === "projects:choose") {
            const input = chooseDirectorySchema.parse(args[0]);
            const choice = await dialog.showOpenDialog(window, {
              title:
                input.purpose === "createProject"
                  ? "选择用于新项目的空目录"
                  : "选择项目目录",
              properties: [
                "openDirectory",
                "createDirectory",
                "dontAddToRecent",
              ],
            });
            data =
              choice.canceled || !choice.filePaths[0]
                ? null
                : {
                    grantId: await register(choice.filePaths[0], input.purpose),
                    name: basename(choice.filePaths[0]),
                  };
          } else if (channel === "projects:create") {
            data = await call(
              "POST",
              "/api/v1/projects",
              receiptSchema,
              createProjectSchema.parse(args[0]),
            );
          } else if (channel === "projects:open")
            data = await open(openProjectSchema.parse(args[0]));
          else if (channel === "projects:open-recent") {
            const input = recentInputSchema.parse(args[0]);
            if (current?.projectId === input.projectId) data = current;
            else {
              const directory = await call(
                "GET",
                `/api/v1/private/recent-projects/${input.projectId}/directory`,
                z.strictObject({ path: z.string().min(1).max(32767) }),
              );
              const grant = await register(directory.path, "openProject");
              data = await open(
                {
                  directoryGrantId: grant,
                  requestedMode: "write",
                },
                input.projectId,
              );
            }
          } else {
            const input = operationInputSchema.parse(args[0]);
            data = await call(
              "GET",
              `/api/v1/operations/${input.operationId}`,
              operationSchema,
            );
          }
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
      } finally {
        if (ownsBusy) busy = false;
      }
    });
  return {
    dispose: () => {
      for (const command of commands) ipcMain.removeHandler(command);
    },
    current: () =>
      runtimeId === supervisor.snapshot().runtimeId ? current : null,
  };
}
