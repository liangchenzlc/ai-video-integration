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

import { installVersionsIpc } from "../../electron/main/projects/versions-ipc";

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
  dispose = installVersionsIpc(
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
  dispose = undefined;
  mocks.request.mockReset();
});

test("version IPC binds artifact routes to the open project before transport", async () => {
  const current = setup();
  const artifactId = randomUUID();
  expect(
    await mocks.handlers.get("versions:artifact")!(event, {
      projectId: randomUUID(),
      artifactId,
    }),
  ).toMatchObject({ ok: false, error: { code: "SESSION_EXPIRED" } });
  expect(
    await mocks.handlers.get("versions:artifact")!(
      { ...event, senderFrame: { url: frame.url } } as IpcMainInvokeEvent,
      { projectId: current.projectId, artifactId },
    ),
  ).toMatchObject({ ok: false, error: { code: "SOURCE_REJECTED" } });
  expect(
    await mocks.handlers.get("versions:artifact")!(event, {
      projectId: current.projectId,
      artifactId,
      path: "/private",
    }),
  ).toMatchObject({ ok: false, error: { code: "REQUEST_INVALID" } });
  expect(mocks.request).not.toHaveBeenCalled();
});

test("adoption preview is a plain read calculation while adoption preserves the exact command", async () => {
  const current = setup();
  const artifactId = randomUUID();
  const toRevisionId = randomUUID();
  const preview = {
    projectId: current.projectId,
    artifactId,
    toRevisionId,
    expectedRevision: 23,
  };
  const command = {
    clientOperationId: randomUUID(),
    expectedRevision: 23,
    payload: { previewId: randomUUID(), toRevisionId, confirm: false },
  };
  mocks.request.mockResolvedValue({});

  await mocks.handlers.get("versions:preview")!(event, preview);
  await mocks.handlers.get("versions:adopt")!(event, {
    projectId: current.projectId,
    artifactId,
    command,
  });

  expect(mocks.request.mock.calls[0][2]).toMatchObject({
    method: "POST",
    path: `/api/v1/projects/${current.projectId}/artifacts/${artifactId}/adoption-preview`,
    body: { toRevisionId, expectedRevision: 23 },
    sessionId: current.projectSessionId,
    windowId: 1,
  });
  expect(mocks.request.mock.calls[1][2]).toMatchObject({
    method: "POST",
    path: `/api/v1/projects/${current.projectId}/artifacts/${artifactId}/adoptions`,
    body: command,
    sessionId: current.projectSessionId,
    windowId: 1,
  });
});

test("read-only sessions can browse and preview but cannot run checks or mutate", async () => {
  const current = setup("read");
  const input = {
    projectId: current.projectId,
    command: {
      clientOperationId: randomUUID(),
      expectedRevision: 4,
      payload: {
        revisionIds: [randomUUID()],
        ruleIds: ["structural", "references"],
      },
    },
  };
  expect(
    await mocks.handlers.get("versions:runChecks")!(event, input),
  ).toMatchObject({ ok: false, error: { code: "PROJECT_READ_ONLY" } });
  expect(mocks.request).not.toHaveBeenCalled();
});

test("version commands reject mismatched route identities and empty local checks", async () => {
  const current = setup();
  expect(
    await mocks.handlers.get("versions:undo")!(event, {
      projectId: current.projectId,
      adoptionId: randomUUID(),
      command: {
        clientOperationId: randomUUID(),
        expectedRevision: 4,
        payload: { adoptionId: randomUUID() },
      },
    }),
  ).toMatchObject({ ok: false, error: { code: "REQUEST_INVALID" } });
  expect(
    await mocks.handlers.get("versions:runChecks")!(event, {
      projectId: current.projectId,
      command: {
        clientOperationId: randomUUID(),
        expectedRevision: 4,
        payload: { revisionIds: [], ruleIds: [] },
      },
    }),
  ).toMatchObject({ ok: false, error: { code: "REQUEST_INVALID" } });
  expect(mocks.request).not.toHaveBeenCalled();
});

test("all nine finite version handlers clean up", () => {
  setup();
  expect(
    [...mocks.handlers.keys()].filter((key) => key.startsWith("versions:")),
  ).toHaveLength(9);
  dispose?.();
  expect(
    [...mocks.handlers.keys()].filter((key) => key.startsWith("versions:")),
  ).toHaveLength(0);
});
