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
      handler: (
        event: IpcMainInvokeEvent,
        ...args: unknown[]
      ) => Promise<unknown>,
    ) => mocks.handlers.set(key, handler),
    removeHandler: (key: string) => mocks.handlers.delete(key),
  },
}));
vi.mock("../../electron/main/projects/client", () => ({
  businessRequest: mocks.request,
}));
import { installSettingsIpc } from "../../electron/main/projects/settings-ipc";
import {
  settingsDetailsSchema,
  settingsSchema,
} from "../../electron/shared/settings";
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
  dispose = installSettingsIpc(
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
test("settings rejects forged frames, unsafe provider paths, extra fields and stale project ownership", async () => {
  setup();
  expect(
    await mocks.handlers.get("settings:get")!({
      ...event,
      senderFrame: { url: frame.url },
    } as IpcMainInvokeEvent),
  ).toMatchObject({ ok: false, error: { code: "SOURCE_REJECTED" } });
  expect(
    await mocks.handlers.get("settings:set-credential")!(event, {
      providerId: "../settings",
      command: {
        clientOperationId: randomUUID(),
        expectedRevision: 0,
        payload: {
          secret: { kind: "api_key", apiKey: "sentinel" },
          persistence: "dpapi",
        },
      },
    }),
  ).toMatchObject({ ok: false, error: { code: "REQUEST_INVALID" } });
  expect(
    await mocks.handlers.get("settings:stage-models")!(event, {
      projectId: randomUUID(),
    }),
  ).toMatchObject({ ok: false, error: { code: "SESSION_EXPIRED" } });
  expect(
    await mocks.handlers.get("settings:get")!(event, { path: "/private" }),
  ).toMatchObject({ ok: false, error: { code: "REQUEST_INVALID" } });
  expect(mocks.request).not.toHaveBeenCalled();
});
test("settings uses static secret-safe errors and forwards project CAS with its bound session", async () => {
  const current = setup();
  mocks.request.mockRejectedValueOnce(new Error("secret-sentinel"));
  const error = await mocks.handlers.get("settings:get")!(event);
  expect(error).toMatchObject({
    ok: false,
    error: { code: "BACKEND_UNAVAILABLE" },
  });
  expect(JSON.stringify(error)).not.toContain("secret-sentinel");
  mocks.request.mockResolvedValueOnce({});
  const command = {
    clientOperationId: randomUUID(),
    expectedRevision: 42,
    payload: { phase: "speech", capabilityId: randomUUID() },
  };
  await mocks.handlers.get("settings:configure-stage")!(event, {
    projectId: current.projectId,
    command,
  });
  expect(mocks.request.mock.calls[1][2]).toMatchObject({
    method: "PUT",
    path: `/api/v1/projects/${current.projectId}/stage-models`,
    sessionId: current.projectSessionId,
    body: command,
  });
});
test("read DTOs reject secret or path fields even inside provider and capability data", () => {
  expect(
    settingsSchema.safeParse({
      revision: 0,
      providers: [
        {
          providerId: "test",
          credentialConfigured: true,
          maskedSuffix: "1234",
          storageConfigured: false,
          apiKey: "sentinel",
        },
      ],
      ffmpegConfigured: false,
      capabilities: [],
    }).success,
  ).toBe(false);
  expect(
    settingsDetailsSchema.safeParse({
      credentials: [],
      storageProfiles: [],
      toolSummary: {
        version: "7",
        h264: true,
        aac: true,
        subtitles: true,
        path: "private",
      },
    }).success,
  ).toBe(false);
});
