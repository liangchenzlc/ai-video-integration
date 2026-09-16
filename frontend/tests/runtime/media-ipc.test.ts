import { randomUUID } from "node:crypto";
import type { BrowserWindow, IpcMainInvokeEvent } from "electron";
import { afterEach, expect, test, vi } from "vitest";
import type { RuntimeSupervisor } from "../../electron/main/runtime/supervisor";
import type { ProjectSession } from "../../electron/shared/projects";

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
      handler: (
        event: IpcMainInvokeEvent,
        ...args: unknown[]
      ) => Promise<unknown>,
    ) => mocks.handlers.set(key, handler),
    removeHandler: (key: string) => mocks.handlers.delete(key),
  },
  dialog: { showOpenDialog: mocks.choose },
}));
vi.mock("../../electron/main/projects/client", () => ({
  businessRequest: mocks.request,
}));
import { installMediaIpc } from "../../electron/main/projects/media-ipc";

const frame = { url: "app://ui/" };
const event = {
  sender: { id: 1 },
  senderFrame: frame,
} as unknown as IpcMainInvokeEvent;
let dispose: (() => void) | undefined;
function setup() {
  const current = {
    projectId: randomUUID(),
    projectSessionId: randomUUID(),
    mode: "write",
  } as ProjectSession;
  const window = {
    isDestroyed: () => false,
    webContents: { id: 1, mainFrame: frame },
  } as unknown as BrowserWindow;
  const supervisor = {
    withConnection: (
      work: (endpoint: unknown, signal: AbortSignal) => Promise<unknown>,
    ) => work({}, new AbortController().signal),
  } as RuntimeSupervisor;
  dispose = installMediaIpc(window, supervisor, false, () => current);
  return current;
}
afterEach(() => {
  dispose?.();
  mocks.request.mockReset();
  mocks.choose.mockReset();
});

test("media IPC requires a trusted main frame and current project", async () => {
  setup();
  expect(
    await mocks.handlers.get("media:settings")!({
      ...event,
      sender: { id: 2 },
    } as IpcMainInvokeEvent),
  ).toMatchObject({ ok: false, error: { code: "SOURCE_REJECTED" } });
  expect(
    await mocks.handlers.get("media:list")!(event, { projectId: randomUUID() }),
  ).toMatchObject({ ok: false, error: { code: "SESSION_EXPIRED" } });
  expect(
    await mocks.handlers.get("media:choose")!(event, {
      purpose: "ffmpeg",
      path: "C:\\injected.exe",
    }),
  ).toMatchObject({ ok: false, error: { code: "REQUEST_INVALID" } });
  expect(mocks.request).not.toHaveBeenCalled();
  expect(mocks.choose).not.toHaveBeenCalled();
});

test("native file selection registers path privately and returns only a grant and basename", async () => {
  setup();
  mocks.choose.mockResolvedValueOnce({
    canceled: false,
    filePaths: ["C:\\private-source\\ffmpeg.exe"],
  });
  mocks.request.mockResolvedValueOnce({});
  const result = await mocks.handlers.get("media:choose")!(event, {
    purpose: "ffmpeg",
  });
  expect(result).toMatchObject({ ok: true, data: { name: "ffmpeg.exe" } });
  expect(JSON.stringify(result)).not.toContain("private-source");
  expect(mocks.request.mock.calls[0][2]).toMatchObject({
    method: "POST",
    path: "/api/v1/file-grants",
    windowId: 1,
    body: {
      payload: {
        purpose: "ffmpeg",
        path: "C:\\private-source\\ffmpeg.exe",
        windowId: 1,
      },
    },
  });
});

test("media pagination and import route carry the bound project session", async () => {
  const current = setup();
  mocks.request.mockResolvedValue({ items: [], nextCursor: null });
  const cursor = randomUUID();
  expect(
    await mocks.handlers.get("media:list")!(event, {
      projectId: current.projectId,
      cursor,
      limit: 24,
    }),
  ).toMatchObject({ ok: true });
  expect(mocks.request.mock.calls[0][2]).toMatchObject({
    method: "GET",
    path: `/api/v1/projects/${current.projectId}/media?limit=24&cursor=${cursor}`,
    sessionId: current.projectSessionId,
  });
  const command = {
    clientOperationId: randomUUID(),
    expectedRevision: 1,
    payload: { fileGrantId: randomUUID(), purpose: "reference" },
  };
  await mocks.handlers.get("media:import")!(event, {
    projectId: current.projectId,
    command,
  });
  expect(mocks.request.mock.calls[1][2]).toMatchObject({
    method: "POST",
    path: `/api/v1/projects/${current.projectId}/imports`,
    sessionId: current.projectSessionId,
    body: command,
  });
});
