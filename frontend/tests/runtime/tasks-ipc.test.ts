import { randomUUID } from "node:crypto";
import { afterEach, expect, test, vi } from "vitest";
import type { BrowserWindow, IpcMainInvokeEvent } from "electron";
import type { RuntimeSupervisor } from "../../electron/main/runtime/supervisor";
import type { ProjectSession } from "../../electron/shared/projects";
const mocks = vi.hoisted(() => ({
  handlers: new Map<
    string,
    (event: IpcMainInvokeEvent, ...args: unknown[]) => Promise<unknown>
  >(),
  request: vi.fn(),
}));
vi.mock("electron", () => ({
  ipcMain: {
    handle: (
      key: string,
      fn: (event: IpcMainInvokeEvent, ...args: unknown[]) => Promise<unknown>,
    ) => mocks.handlers.set(key, fn),
    removeHandler: (key: string) => mocks.handlers.delete(key),
  },
}));
vi.mock("../../electron/main/projects/client", () => ({
  businessRequest: mocks.request,
}));
import { installTasksIpc } from "../../electron/main/projects/tasks-ipc";
const frame = { url: "app://ui/" };
const event = {
  sender: { id: 1 },
  senderFrame: frame,
} as unknown as IpcMainInvokeEvent;
let dispose: () => void;
function setup() {
  const current = {
    projectId: randomUUID(),
    projectSessionId: randomUUID(),
    mode: "write",
  } as ProjectSession;
  dispose = installTasksIpc(
    {
      isDestroyed: () => false,
      webContents: { id: 1, mainFrame: frame },
    } as unknown as BrowserWindow,
    {
      withConnection: (
        work: (endpoint: unknown, signal: AbortSignal) => Promise<unknown>,
      ) => work({}, new AbortController().signal),
    } as RuntimeSupervisor,
    false,
    () => current,
  );
  return current;
}
afterEach(() => {
  dispose?.();
  mocks.request.mockReset();
});
test("task IPC rejects wrong project, forged frame, extra arguments and arbitrary path before transport", async () => {
  const current = setup();
  expect(
    await mocks.handlers.get("tasks:budget")!(event, {
      projectId: randomUUID(),
    }),
  ).toMatchObject({ ok: false, error: { code: "SESSION_EXPIRED" } });
  expect(
    await mocks.handlers.get("tasks:activity")!(
      { ...event, senderFrame: { url: frame.url } } as IpcMainInvokeEvent,
      {},
    ),
  ).toMatchObject({ ok: false, error: { code: "SOURCE_REJECTED" } });
  expect(
    await mocks.handlers.get("tasks:budget")!(event, {
      projectId: current.projectId,
      path: "/private",
    }),
  ).toMatchObject({ ok: false, error: { code: "REQUEST_INVALID" } });
  expect(
    await mocks.handlers.get("tasks:activity")!(event, {}, {}),
  ).toMatchObject({ ok: false, error: { code: "REQUEST_INVALID" } });
  expect(mocks.request).not.toHaveBeenCalled();
});
test("task start forwards exact authorization and operation identity with bound window session", async () => {
  const current = setup();
  const command = {
    clientOperationId: randomUUID(),
    expectedRevision: 23,
    payload: {
      planId: randomUUID(),
      authorizedMaximumMicroCny: 1234567,
      disclosureAccepted: true,
    },
  };
  mocks.request.mockResolvedValue({});
  await mocks.handlers.get("tasks:start")!(event, {
    projectId: current.projectId,
    command,
  });
  expect(mocks.request.mock.calls[0][2]).toMatchObject({
    method: "POST",
    path: `/api/v1/projects/${current.projectId}/tasks`,
    body: command,
    sessionId: current.projectSessionId,
    windowId: 1,
  });
  current.mode = "read";
  expect(
    await mocks.handlers.get("tasks:start")!(event, {
      projectId: current.projectId,
      command,
    }),
  ).toMatchObject({ ok: false, error: { code: "PROJECT_READ_ONLY" } });
  expect(mocks.request).toHaveBeenCalledTimes(1);
});
test("activity has no project session and all task handlers clean up", async () => {
  setup();
  mocks.request.mockResolvedValue([]);
  expect(await mocks.handlers.get("tasks:activity")!(event, {})).toEqual({
    ok: true,
    data: [],
  });
  expect(mocks.request.mock.calls[0][2]).toMatchObject({
    path: "/api/v1/task-activity",
    sessionId: undefined,
  });
  dispose();
  expect(mocks.handlers.size).toBe(0);
});
