import { EventEmitter } from "node:events";
import type { BrowserWindow } from "electron";
import type { RuntimeSupervisor } from "../../electron/main/runtime/supervisor";
import { RuntimeError } from "../../electron/shared/runtime";
import { afterEach, expect, test, vi } from "vitest";

const transport = vi.hoisted(() => ({
  main: new Map<string, (...args: unknown[]) => void>(),
  renderer: new Map<string, (...args: unknown[]) => void>(),
  send: vi.fn(),
  dialog: vi.fn(),
  handlers: new Map<
    string,
    (event: unknown, ...args: unknown[]) => Promise<unknown>
  >(),
}));
vi.mock("electron", () => ({
  protocol: { handle: () => {}, unhandle: () => {} },
  ipcMain: {
    handle: (
      name: string,
      handler: (event: unknown, ...args: unknown[]) => Promise<unknown>,
    ) => transport.handlers.set(name, handler),
    removeHandler: (name: string) => transport.handlers.delete(name),
    on: (name: string, fn: (...args: unknown[]) => void) =>
      transport.main.set(name, fn),
    removeListener: (name: string) => transport.main.delete(name),
  },
  ipcRenderer: {
    on: (name: string, fn: (...args: unknown[]) => void) =>
      transport.renderer.set(name, fn),
    removeListener: (name: string) => transport.renderer.delete(name),
    send: (...args: unknown[]) => transport.send(...args),
  },
  dialog: { showMessageBox: (...args: unknown[]) => transport.dialog(...args) },
}));
vi.mock("../../electron/main/projects/ipc", () => ({
  installProjectIpc: () => ({ dispose: () => {}, current: () => null }),
}));
vi.mock("../../electron/main/projects/media-ipc", () => ({
  installMediaIpc: () => () => {},
}));
vi.mock("../../electron/main/projects/media-stream", () => ({
  serveMedia: async () => new Response(null, { status: 404 }),
}));
import {
  requestRendererFlush,
  confirmRendererLeave,
  createQuitGuard,
  resumeRendererEditing,
} from "../../electron/main/draft-flush";
import { createBeforeLeaveBridge } from "../../electron/preload/draft-flush";
import { installIpc } from "../../electron/main/ipc";

function setup() {
  const events = new EventEmitter();
  const frame = { url: "app://ui/" };
  const send = vi.fn();
  const window = Object.assign(events, {
    isDestroyed: () => false,
    webContents: {
      id: 7,
      mainFrame: frame,
      isDestroyed: () => false,
      send,
      getURL: () => frame.url,
    },
  }) as unknown as BrowserWindow;
  const event = { sender: { id: 7 }, senderFrame: frame };
  return { window, events, frame, event, send };
}
afterEach(() => {
  vi.useRealTimers();
  transport.main.clear();
  transport.renderer.clear();
  transport.handlers.clear();
  transport.send.mockReset();
  transport.dialog.mockReset();
});

test("only the correlated trusted main frame can authorize leaving", async () => {
  const { window, event, send } = setup();
  const pending = requestRendererFlush(window, false);
  const id = send.mock.calls[0][1].requestId;
  const respond = transport.main.get("draft:flush-result")!;
  let settled = false;
  void pending.then(() => {
    settled = true;
  });
  respond({ ...event, sender: { id: 8 } }, { requestId: id, saved: true });
  respond(
    { ...event, senderFrame: { url: "app://ui/" } },
    { requestId: id, saved: true },
  );
  respond(event, { requestId: "wrong", saved: true });
  respond(event, { requestId: id, saved: true, arbitrary: "data" });
  await Promise.resolve();
  expect(settled).toBe(false);
  respond(event, { requestId: id, saved: true });
  expect(await pending).toBe(true);
  expect(transport.main.size).toBe(0);
});

test("concurrent requests share one flush and time out closed after 45 seconds", async () => {
  vi.useFakeTimers();
  const { window, send } = setup();
  const first = requestRendererFlush(window, false);
  const second = requestRendererFlush(window, false);
  expect(send).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(44999);
  expect(transport.main.size).toBe(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(await first).toBe(false);
  expect(await second).toBe(false);
  expect(transport.main.size).toBe(0);
  const next = requestRendererFlush(window, false);
  expect(send.mock.calls[1][1].requestId).not.toBe(
    send.mock.calls[0][1].requestId,
  );
  window.emit("closed");
  expect(await next).toBe(false);
  expect(transport.main.size).toBe(0);
});

test("preload acknowledges initial loading, calls listeners without raw events, and fails closed after unsubscribe", async () => {
  const bridge = createBeforeLeaveBridge();
  const request = transport.renderer.get("draft:flush-request")!;
  const id = "893f1472-9575-43f0-8c3d-0d1c09423d25";
  request({ secret: "electron" }, { requestId: id });
  await vi.waitFor(() =>
    expect(transport.send).toHaveBeenLastCalledWith("draft:flush-result", {
      requestId: id,
      saved: true,
    }),
  );
  const listener = vi.fn().mockResolvedValue(false);
  const unsubscribe = bridge.onBeforeLeave(listener);
  request({}, { requestId: id });
  await vi.waitFor(() =>
    expect(transport.send).toHaveBeenLastCalledWith("draft:flush-result", {
      requestId: id,
      saved: false,
    }),
  );
  expect(listener).toHaveBeenCalledWith();
  unsubscribe();
  transport.send.mockClear();
  request({}, { requestId: id });
  await vi.waitFor(() =>
    expect(transport.send).toHaveBeenCalledWith("draft:flush-result", {
      requestId: id,
      saved: false,
    }),
  );
  bridge.dispose();
  expect(transport.renderer.size).toBe(0);
});

test("preload rejects invalid requests and converts listener failures to denial", async () => {
  const bridge = createBeforeLeaveBridge();
  bridge.onBeforeLeave(async () => {
    throw new Error("draft contents");
  });
  const request = transport.renderer.get("draft:flush-request")!;
  request({}, { requestId: "bad" });
  await Promise.resolve();
  expect(transport.send).not.toHaveBeenCalled();
  request({}, { requestId: "893f1472-9575-43f0-8c3d-0d1c09423d25" });
  await vi.waitFor(() =>
    expect(transport.send.mock.calls[0][1].saved).toBe(false),
  );
  bridge.dispose();
});

test("failed flush requires explicit discard with continue editing the native default", async () => {
  const { window, event, send } = setup();
  transport.dialog.mockResolvedValue({ response: 0 });
  const cancelled = confirmRendererLeave(window, false);
  transport.main.get("draft:flush-result")!(event, {
    requestId: send.mock.calls[0][1].requestId,
    saved: false,
  });
  expect(await cancelled).toBe(false);
  expect(send).toHaveBeenLastCalledWith("draft:resume", {
    requestId: send.mock.calls[0][1].requestId,
  });
  expect(transport.dialog.mock.calls[0][1]).toMatchObject({
    defaultId: 0,
    cancelId: 0,
    buttons: ["继续编辑", "放弃未保存的修改"],
  });
  transport.dialog.mockResolvedValue({ response: 1 });
  const discarded = confirmRendererLeave(window, false);
  transport.main.get("draft:flush-result")!(event, {
    requestId: send.mock.calls[2][1].requestId,
    saved: false,
  });
  expect(await discarded).toBe(true);
});

test("quit guard prevents repeated close/quit while deciding, cancels safely, and stops only after permission", async () => {
  let resolveLeave!: (value: boolean) => void;
  const confirm = vi.fn(
    () =>
      new Promise<boolean>((resolve) => {
        resolveLeave = resolve;
      }),
  );
  let resolveStop!: () => void;
  const stop = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        resolveStop = resolve;
      }),
  );
  const quit = vi.fn();
  const guard = createQuitGuard({ confirm, stop, quit });
  const preventDefault = vi.fn();
  guard.beforeQuit({ preventDefault });
  guard.beforeQuit({ preventDefault });
  guard.beforeClose({ preventDefault });
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(stop).not.toHaveBeenCalled();
  expect(preventDefault).toHaveBeenCalledTimes(3);
  resolveLeave(false);
  await Promise.resolve();
  guard.beforeQuit({ preventDefault });
  expect(confirm).toHaveBeenCalledTimes(2);
  resolveLeave(true);
  await vi.waitFor(() => expect(stop).toHaveBeenCalledTimes(1));
  guard.beforeClose({ preventDefault });
  expect(quit).not.toHaveBeenCalled();
  resolveStop();
  await vi.waitFor(() => expect(quit).toHaveBeenCalledTimes(1));
  preventDefault.mockClear();
  guard.beforeQuit({ preventDefault });
  guard.beforeClose({ preventDefault });
  expect(preventDefault).not.toHaveBeenCalled();
});

test("ready backend restart waits for saved drafts and returns an actionable denial", async () => {
  const { window, event, send } = setup();
  const restart = vi.fn().mockResolvedValue({ state: "ready" });
  const supervisor = {
    snapshot: () => ({ state: "ready" }),
    subscribe: () => () => {},
    restart,
  } as unknown as RuntimeSupervisor;
  const dispose = installIpc(window, supervisor, false);
  const request = transport.handlers.get("runtime:restart")!;
  const denied = request(event, { expectedGeneration: 1 });
  expect(restart).not.toHaveBeenCalled();
  transport.main.get("draft:flush-result")!(event, {
    requestId: send.mock.calls[0][1].requestId,
    saved: false,
  });
  expect(await denied).toMatchObject({
    ok: false,
    error: { code: "DRAFT_FLUSH_FAILED", recoverableAction: "none" },
  });
  expect(restart).not.toHaveBeenCalled();
  const accepted = request(event, { expectedGeneration: 1 });
  transport.main.get("draft:flush-result")!(event, {
    requestId: send.mock.calls[2][1].requestId,
    saved: true,
  });
  expect(await accepted).toMatchObject({ ok: true });
  expect(restart).toHaveBeenCalledWith(1);
  dispose();
});

test("failed backend restarts without discarding or requesting unavailable draft persistence", async () => {
  const { window, event, send } = setup();
  const restart = vi.fn().mockResolvedValue({ state: "ready" });
  const supervisor = {
    snapshot: () => ({ state: "failed" }),
    subscribe: () => () => {},
    restart,
  } as unknown as RuntimeSupervisor;
  const dispose = installIpc(window, supervisor, false);
  expect(
    await transport.handlers.get("runtime:restart")!(event, {
      expectedGeneration: 1,
    }),
  ).toMatchObject({ ok: true });
  expect(send).not.toHaveBeenCalled();
  expect(transport.dialog).not.toHaveBeenCalled();
  expect(restart).toHaveBeenCalledWith(1);
  dispose();
});

test("preload keeps the edit lock after saved acknowledgement until the correlated resume", async () => {
  const bridge = createBeforeLeaveBridge();
  let locked = false;
  bridge.onBeforeLeave(
    async () => {
      locked = true;
      return true;
    },
    () => {
      locked = false;
    },
  );
  const id = "893f1472-9575-43f0-8c3d-0d1c09423d25";
  transport.renderer.get("draft:flush-request")!({}, { requestId: id });
  expect(locked).toBe(true);
  await vi.waitFor(() => expect(transport.send).toHaveBeenCalled());
  expect(locked).toBe(true);
  transport.renderer.get("draft:resume")!(
    {},
    { requestId: "4ac983b6-d7e8-46a8-ae19-46c661388e11" },
  );
  expect(locked).toBe(true);
  transport.renderer.get("draft:resume")!({}, { requestId: id });
  expect(locked).toBe(false);
  bridge.dispose();
});

test("overlapping leave owners cannot resume editing before both release", async () => {
  const { window, event, send } = setup();
  const first = requestRendererFlush(window, false);
  const second = requestRendererFlush(window, false);
  const id = send.mock.calls[0][1].requestId;
  transport.main.get("draft:flush-result")!(event, {
    requestId: id,
    saved: true,
  });
  await Promise.all([first, second]);
  resumeRendererEditing(window);
  expect(send).toHaveBeenCalledTimes(1);
  resumeRendererEditing(window);
  expect(send).toHaveBeenLastCalledWith("draft:resume", { requestId: id });
});

test.each([false, true])(
  "restart finally resumes even when stale generation rejects: %s",
  async (reject) => {
    const { window, event, send } = setup();
    let finish!: () => void;
    const restart = vi.fn(
      () =>
        new Promise<void>((resolve, fail) => {
          finish = () =>
            reject ? fail(new RuntimeError("STALE_RUNTIME")) : resolve();
        }),
    );
    const supervisor = {
      snapshot: () => ({ state: "ready" }),
      subscribe: () => () => {},
      restart,
    } as unknown as RuntimeSupervisor;
    const dispose = installIpc(window, supervisor, false);
    const result = transport.handlers.get("runtime:restart")!(event, {
      expectedGeneration: 1,
    });
    const id = send.mock.calls[0][1].requestId;
    transport.main.get("draft:flush-result")!(event, {
      requestId: id,
      saved: true,
    });
    await vi.waitFor(() => expect(restart).toHaveBeenCalled());
    expect(send).toHaveBeenCalledTimes(1);
    finish();
    await result;
    expect(send).toHaveBeenLastCalledWith("draft:resume", { requestId: id });
    dispose();
  },
);
