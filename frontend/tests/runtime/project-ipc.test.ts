import { randomUUID } from "node:crypto";
import type { BrowserWindow, IpcMainInvokeEvent } from "electron";
import { afterEach, expect, test, vi } from "vitest";
import {
  RuntimeError,
  type RuntimeSnapshot,
} from "../../electron/shared/runtime";
import type { RuntimeSupervisor } from "../../electron/main/runtime/supervisor";
import type { ProjectSession } from "../../electron/shared/projects";

const mocks = vi.hoisted(() => ({
  handlers: new Map<
    string,
    (event: unknown, ...args: unknown[]) => Promise<unknown>
  >(),
  request: vi.fn(),
}));
vi.mock("electron", () => ({
  dialog: {},
  ipcMain: {
    handle: (
      key: string,
      handler: (event: unknown, ...args: unknown[]) => Promise<unknown>,
    ) => mocks.handlers.set(key, handler),
    removeHandler: (key: string) => mocks.handlers.delete(key),
  },
}));
vi.mock("../../electron/main/projects/client", () => ({
  businessRequest: mocks.request,
}));
import { installProjectIpc } from "../../electron/main/projects/ipc";

const frame = { url: "app://ui/" };
const event = {
  sender: { id: 1 },
  senderFrame: frame,
} as unknown as IpcMainInvokeEvent;
function session(): ProjectSession {
  const id = randomUUID();
  return {
    projectId: id,
    projectSessionId: randomUUID(),
    mode: "write",
    project: {
      id,
      name: "story",
      revision: 0,
      eventSequence: 0,
      formatVersion: 1,
      aspect: "16:9",
      resolution: "1080p",
      fps: { numerator: 24, denominator: 1 },
      targetMs: 30000,
      budgetMicroCny: 0,
      executionMode: null,
      savedAt: null,
      readOnly: false,
    },
  };
}
let dispose: (() => void) | undefined;
function setup() {
  const runtime: RuntimeSnapshot = {
    runtimeId: randomUUID(),
    state: "ready",
    generation: 1,
    revision: 1,
    frontendVersion: "0.1.0",
    backendVersion: "0.1.0",
    errorCode: null,
    recoverableAction: "none",
    canRestart: true,
  };
  const window = {
    isDestroyed: () => false,
    webContents: { id: 1, mainFrame: frame },
  } as unknown as BrowserWindow;
  const supervisor = {
    snapshot: () => ({ ...runtime }),
    withConnection: (work: (e: unknown, s: AbortSignal) => Promise<unknown>) =>
      work({}, new AbortController().signal),
  } as unknown as RuntimeSupervisor;
  dispose = installProjectIpc(window, supervisor, false).dispose;
  return runtime;
}
function call(name: string, input?: unknown) {
  return mocks.handlers.get(name)!(
    event,
    ...(input === undefined ? [] : [input]),
  );
}
afterEach(() => {
  dispose?.();
  mocks.request.mockReset();
});

test("draft commands bind to the current project session and fixed paths", async () => {
  setup();
  const current = session();
  mocks.request.mockResolvedValueOnce(current);
  await call("projects:open", {
    directoryGrantId: randomUUID(),
    requestedMode: "write",
  });
  mocks.request.mockClear();
  expect(await call("drafts:list", { projectId: randomUUID() })).toMatchObject({
    ok: false,
    error: { code: "SESSION_EXPIRED" },
  });
  expect(mocks.request).not.toHaveBeenCalled();
  const draftId = randomUUID();
  const command = {
    clientOperationId: randomUUID(),
    expectedRevision: 0,
    payload: {
      draftId,
      artifactId: randomUUID(),
      baseRevisionId: null,
      content: { kind: "story", content: { sourceText: "" } },
    },
  };
  const receipt = {
    operationId: command.clientOperationId,
    committedRevision: 1,
    resourceId: draftId,
    state: "committed",
  };
  mocks.request.mockResolvedValue(receipt);
  expect(
    await call("drafts:save", { projectId: current.projectId, command }),
  ).toEqual({ ok: true, data: receipt });
  expect(mocks.request.mock.calls[0][2]).toMatchObject({
    method: "PUT",
    path: `/api/v1/projects/${current.projectId}/drafts/${draftId}`,
    sessionId: current.projectSessionId,
    body: command,
  });
});

test("failed switch retains the previous current session", async () => {
  setup();
  const a = session();
  mocks.request.mockResolvedValueOnce(a);
  await call("projects:open", {
    directoryGrantId: randomUUID(),
    requestedMode: "write",
  });
  mocks.request.mockImplementation(
    async (_e, _s, options: { method: string }) => {
      if (options.method === "DELETE") return { closed: true };
      throw new RuntimeError("PROJECT_CORRUPT");
    },
  );
  expect(
    await call("projects:open", {
      directoryGrantId: randomUUID(),
      requestedMode: "write",
    }),
  ).toMatchObject({ ok: false });
  expect(await call("projects:current")).toEqual({ ok: true, data: a });
});

test("recent project identity mismatch cannot replace current project", async () => {
  setup();
  const a = session(),
    b = session(),
    wanted = randomUUID();
  mocks.request.mockResolvedValueOnce(a);
  await call("projects:open", {
    directoryGrantId: randomUUID(),
    requestedMode: "write",
  });
  mocks.request.mockImplementation(
    async (_e, _s, options: { method: string; path: string }) => {
      if (options.path.endsWith("/directory"))
        return { path: "C:\\known-project" };
      if (options.path.endsWith("/file-grants"))
        return {
          operationId: randomUUID(),
          committedRevision: 0,
          resourceId: randomUUID(),
          state: "committed",
        };
      if (options.method === "DELETE") return { closed: true };
      return b;
    },
  );
  expect(
    await call("projects:open-recent", { projectId: wanted }),
  ).toMatchObject({ ok: false, error: { code: "PROJECT_NOT_FOUND" } });
  expect(await call("projects:current")).toEqual({ ok: true, data: a });
});

test.each([
  { changedRuntime: true, state: "ready" },
  { changedRuntime: true, state: "stopping" },
] as const)(
  "open rejects runtime invalidation during cleanup (changed=$changedRuntime, state=$state)",
  async ({ changedRuntime, state }) => {
    const runtime = setup();
    const a = session(),
      b = session(),
      c = session();
    const input = { directoryGrantId: randomUUID(), requestedMode: "write" };
    mocks.request.mockResolvedValueOnce(a);
    expect(await call("projects:open", input)).toEqual({ ok: true, data: a });

    const released: string[] = [];
    mocks.request.mockImplementation(
      async (_e, _s, options: { method: string; path: string }) => {
        if (options.method === "DELETE") {
          released.push(options.path);
          if (changedRuntime) runtime.runtimeId = randomUUID();
          runtime.state = state;
          throw new RuntimeError("STALE_RUNTIME");
        }
        return b;
      },
    );
    expect(await call("projects:open", input)).toMatchObject({
      ok: false,
      error: { code: "BACKEND_UNAVAILABLE" },
    });
    expect(await call("projects:current")).toEqual({ ok: true, data: null });

    runtime.state = "ready";
    mocks.request.mockImplementation(
      async (_e, _s, options: { method: string; path: string }) => {
        if (options.method === "DELETE") {
          released.push(options.path);
          return { closed: true };
        }
        return c;
      },
    );
    expect(await call("projects:open", input)).toEqual({ ok: true, data: c });
    expect(released).toEqual([
      `/api/v1/project-sessions/${a.projectSessionId}`,
    ]);
  },
);

test.each(["disconnected", "stopping"] as const)(
  "same-runtime %s during cleanup retains sessions for recovery and close",
  async (state) => {
    const runtime = setup();
    const a = session(),
      b = session();
    const input = { directoryGrantId: randomUUID(), requestedMode: "write" };
    mocks.request.mockResolvedValueOnce(a);
    await call("projects:open", input);
    mocks.request.mockResolvedValueOnce(b);
    mocks.request.mockImplementationOnce(async () => {
      runtime.state = state;
      throw new RuntimeError("STALE_RUNTIME");
    });
    expect(await call("projects:open", input)).toMatchObject({
      ok: false,
      error: { code: "BACKEND_UNAVAILABLE" },
    });

    runtime.state = "ready";
    expect(await call("projects:current")).toEqual({ ok: true, data: b });
    const released: string[] = [];
    mocks.request.mockImplementation(
      async (_e, _s, options: { method: string; path: string }) => {
        if (options.method !== "DELETE")
          throw new Error("Expected session close");
        released.push(options.path);
        return { closed: true };
      },
    );
    expect(await call("projects:close")).toEqual({
      ok: true,
      data: { closed: true },
    });
    expect(released).toEqual([
      `/api/v1/project-sessions/${b.projectSessionId}`,
      `/api/v1/project-sessions/${a.projectSessionId}`,
    ]);
    expect(await call("projects:current")).toEqual({ ok: true, data: null });
  },
);

test("lost cleanup response retains its session ID for a later close", async () => {
  setup();
  const a = session(),
    b = session();
  const input = { directoryGrantId: randomUUID(), requestedMode: "write" };
  mocks.request.mockResolvedValueOnce(a);
  await call("projects:open", input);
  mocks.request.mockResolvedValueOnce(b);
  mocks.request.mockRejectedValueOnce(new RuntimeError("BACKEND_UNAVAILABLE"));
  expect(await call("projects:open", input)).toEqual({ ok: true, data: b });
  expect(await call("projects:current")).toEqual({ ok: true, data: b });

  const released: string[] = [];
  mocks.request.mockImplementation(
    async (_e, _s, options: { path: string }) => {
      released.push(options.path);
      return { closed: true };
    },
  );
  expect(await call("projects:close")).toEqual({
    ok: true,
    data: { closed: true },
  });
  expect(released).toEqual([
    `/api/v1/project-sessions/${b.projectSessionId}`,
    `/api/v1/project-sessions/${a.projectSessionId}`,
  ]);
  expect(await call("projects:current")).toEqual({ ok: true, data: null });
});
