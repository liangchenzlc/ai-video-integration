import { randomUUID } from "node:crypto";
import { afterEach, expect, test, vi } from "vitest";
import type { BrowserWindow, IpcMainInvokeEvent } from "electron";
import type { RuntimeSupervisor } from "../../electron/main/runtime/supervisor";
import type { ProjectSession } from "../../electron/shared/projects";
import { versionRoutes } from "../../electron/shared/versions";

const mocks = vi.hoisted(() => ({
  handlers: new Map<
    string,
    (event: IpcMainInvokeEvent, ...args: unknown[]) => Promise<unknown>
  >(),
  request: vi.fn(),
  choose: vi.fn(),
}));
vi.mock("electron", () => ({
  ipcMain: {
    handle: (
      key: string,
      callback: (
        event: IpcMainInvokeEvent,
        ...args: unknown[]
      ) => Promise<unknown>,
    ) => mocks.handlers.set(key, callback),
    removeHandler: (key: string) => mocks.handlers.delete(key),
  },
  dialog: { showSaveDialog: mocks.choose },
}));
vi.mock("../../electron/main/projects/client", () => ({
  businessRequest: mocks.request,
}));
import { installProductionIpc } from "../../electron/main/projects/production-ipc";

const frame = { url: "app://ui/" };
const event = {
  sender: { id: 1 },
  senderFrame: frame,
} as unknown as IpcMainInvokeEvent;
let dispose: (() => void) | undefined;
function setup(current: ProjectSession | null = null) {
  const state = { current, beforeRequest: () => {} };
  dispose = installProductionIpc(
    {
      isDestroyed: () => false,
      webContents: { id: 1, mainFrame: frame },
    } as unknown as BrowserWindow,
    {
      withConnection: async (
        callback: (endpoint: unknown, signal: AbortSignal) => Promise<unknown>,
      ) => {
        state.beforeRequest();
        return callback({}, new AbortController().signal);
      },
    } as RuntimeSupervisor,
    false,
    () => state.current,
  );
  return state;
}
function session(mode: "read" | "write" = "write") {
  return {
    projectId: randomUUID(),
    projectSessionId: randomUUID(),
    mode,
  } as ProjectSession;
}
const invoke = (method: string, input: unknown, sender = event) =>
  mocks.handlers.get(`production:${method}`)!(sender, input);
afterEach(() => {
  dispose?.();
  mocks.request.mockReset();
  mocks.choose.mockReset();
});

test("production routes reject foreign senders, project IDs and readonly writes before transport", async () => {
  const current = session("read");
  setup(current);
  expect(
    await invoke("index", { projectId: current.projectId }, {
      ...event,
      senderFrame: { url: frame.url },
    } as IpcMainInvokeEvent),
  ).toMatchObject({ ok: false, error: { code: "SOURCE_REJECTED" } });
  expect(await invoke("index", { projectId: randomUUID() })).toMatchObject({
    ok: false,
    error: { code: "SESSION_EXPIRED" },
  });
  expect(
    await invoke("animatic", {
      projectId: current.projectId,
      command: {
        clientOperationId: randomUUID(),
        expectedRevision: 1,
        payload: { timelineRevisionId: randomUUID() },
      },
    }),
  ).toMatchObject({ ok: false, error: { code: "PROJECT_READ_ONLY" } });
  expect(
    await invoke("chooseTarget", {
      purpose: "diagnostic",
      path: "C:/unauthorized.zip",
    }),
  ).toMatchObject({ ok: false, error: { code: "REQUEST_INVALID" } });
  expect(mocks.request).not.toHaveBeenCalled();
  expect(mocks.choose).not.toHaveBeenCalled();
});

test("runtime diagnostics work without a project while project requests freeze the original session", async () => {
  const state = setup();
  mocks.request.mockResolvedValue({ files: [] });
  expect(
    await invoke("diagnosticPreview", {
      projectId: null,
      includeProject: false,
      includeContent: false,
    }),
  ).toMatchObject({ ok: true });
  expect(mocks.request.mock.lastCall?.[2].sessionId).toBeUndefined();
  const original = session();
  expect(
    await invoke("diagnosticPreview", {
      projectId: original.projectId,
      includeProject: true,
      includeContent: true,
    }),
  ).toMatchObject({ ok: false, error: { code: "SESSION_EXPIRED" } });
  state.current = original;
  state.beforeRequest = () => {
    state.current = session();
  };
  expect(
    await invoke("diagnostic", {
      command: {
        clientOperationId: randomUUID(),
        expectedRevision: 0,
        payload: {
          projectId: original.projectId,
          includeProject: true,
          includeContent: true,
          targetGrantId: randomUUID(),
        },
      },
    }),
  ).toMatchObject({ ok: true });
  expect(mocks.request.mock.lastCall?.[2]).toMatchObject({
    sessionId: original.projectSessionId,
    body: { payload: { projectId: original.projectId } },
  });
  const count = mocks.request.mock.calls.length;
  expect(
    await invoke("diagnosticPreview", {
      projectId: original.projectId,
      includeProject: true,
      includeContent: true,
    }),
  ).toMatchObject({ ok: false, error: { code: "SESSION_EXPIRED" } });
  expect(mocks.request).toHaveBeenCalledTimes(count);
});

test("native export choice exposes a grant and filename without returning its filesystem path", async () => {
  setup(session());
  mocks.choose.mockResolvedValue({
    canceled: false,
    filePath: "C:\\local-output\\film.mp4",
  });
  mocks.request.mockResolvedValue({});
  const result = await invoke("chooseTarget", { purpose: "export" });
  expect(result).toMatchObject({
    ok: true,
    data: { name: "film.mp4", grantId: expect.any(String), exists: false },
  });
  expect(JSON.stringify(result)).not.toContain("local-output");
  expect(mocks.request.mock.lastCall?.[2]).toMatchObject({
    path: "/api/v1/file-grants",
    body: {
      payload: {
        purpose: "exportFilm",
        path: "C:\\local-output\\film.mp4",
        windowId: 1,
      },
    },
  });
});

test("the finite version bridge admits all local delivery rules and rejects unknown ones", () => {
  const input = {
    projectId: randomUUID(),
    command: {
      clientOperationId: randomUUID(),
      expectedRevision: 2,
      payload: {
        revisionIds: [randomUUID()],
        ruleIds: [
          "structural",
          "references",
          "media.available",
          "timeline.bounds",
          "dialogue.timing",
          "rights.source",
          "audio.delivery",
          "requirement.coverage",
        ],
      },
    },
  };
  expect(versionRoutes.runChecks.input.safeParse(input).success).toBe(true);
  input.command.payload.ruleIds.push("remote_paid_check");
  expect(versionRoutes.runChecks.input.safeParse(input).success).toBe(false);
});
