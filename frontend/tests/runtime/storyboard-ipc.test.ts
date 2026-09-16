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
import { installStoryboardIpc } from "../../electron/main/projects/storyboard-ipc";

const frame = { url: "app://ui/" };
const event = {
  sender: { id: 1 },
  senderFrame: frame,
} as unknown as IpcMainInvokeEvent;
let dispose: (() => void) | undefined;
function setup(mode: "read" | "write" = "write") {
  const current = {
    projectId: randomUUID(),
    projectSessionId: randomUUID(),
    mode,
  } as ProjectSession;
  dispose = installStoryboardIpc(
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
  mocks.request.mockResolvedValue({});
  return current;
}
afterEach(() => {
  dispose?.();
  mocks.request.mockReset();
});

test("storyboard keeps project and read-only boundaries for exact finite commands", async () => {
  const current = setup("read");
  const shotId = randomUUID();
  const input = {
    projectId: current.projectId,
    command: {
      clientOperationId: randomUUID(),
      expectedRevision: 3,
      payload: { shotIds: [shotId] },
    },
  };
  expect(
    await mocks.handlers.get("storyboard:reorder")!(event, input),
  ).toMatchObject({ ok: false, error: { code: "PROJECT_READ_ONLY" } });
  expect(
    await mocks.handlers.get("storyboard:list")!(event, {
      projectId: randomUUID(),
    }),
  ).toMatchObject({ ok: false, error: { code: "SESSION_EXPIRED" } });
  expect(mocks.request).not.toHaveBeenCalled();
  await mocks.handlers.get("storyboard:prompt")!(event, {
    projectId: current.projectId,
    shotId,
    phase: "image",
  });
  expect(mocks.request.mock.calls[0][2]).toMatchObject({
    method: "GET",
    path: `/api/v1/projects/${current.projectId}/storyboard/shots/${shotId}/prompt?phase=image`,
    sessionId: current.projectSessionId,
    windowId: 1,
  });
});

test("reference verification preserves mismatch and note, duplicate shot IDs reject before transport", async () => {
  const current = setup();
  const shotId = randomUUID();
  const command = {
    clientOperationId: randomUUID(),
    expectedRevision: 3,
    payload: {
      draftId: randomUUID(),
      mediaId: randomUUID(),
      role: "firstFrame",
      matchesPurpose: false,
      note: "Already complete",
    },
  };
  await mocks.handlers.get("storyboard:verify")!(event, {
    projectId: current.projectId,
    command,
  });
  expect(mocks.request.mock.calls[0][2]).toMatchObject({
    method: "POST",
    body: command,
  });
  expect(
    await mocks.handlers.get("storyboard:reorder")!(event, {
      projectId: current.projectId,
      command: { ...command, payload: { shotIds: [shotId, shotId] } },
    }),
  ).toMatchObject({ ok: false, error: { code: "REQUEST_INVALID" } });
  expect(mocks.request).toHaveBeenCalledTimes(1);
});
