import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import type { ChildProcessWithoutNullStreams } from "node:child_process";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RuntimeSupervisor } from "../../electron/main/runtime/supervisor";
import {
  FrameDecoder,
  FrameEncoder,
} from "../../electron/main/runtime/control-codec";
import { RuntimeError, type HealthData } from "../../electron/shared/runtime";
import type { Endpoint } from "../../electron/main/runtime/http-client";

function fixture() {
  let pid = 100;
  const children: Array<ReturnType<typeof child>> = [];
  function child() {
    const emitter = new EventEmitter();
    return Object.assign(emitter, {
      pid: pid++,
      stdin: new PassThrough(),
      stdout: new PassThrough(),
      stderr: new PassThrough(),
      kill: vi.fn(),
    });
  }
  const health = vi.fn(async (e: Endpoint): Promise<HealthData> => ({
    status: "ready",
    runtimeId: e.runtimeId,
    generation: e.generation,
    apiVersion: 1,
    controlVersion: 1,
    backendVersion: "0.1.0",
    uptimeMs: 1,
  }));
  const supervisor = new RuntimeSupervisor({
    appDataDir: "C:\\测试 数据",
    version: "0.1.0",
    mode: "development",
    launch: () => {
      const c = child();
      children.push(c);
      return c as unknown as ChildProcessWithoutNullStreams;
    },
    http: { health, capabilities: vi.fn() },
  });
  async function begin() {
    await supervisor.start();
    const c = children.at(-1)!;
    c.emit("spawn");
    const state = supervisor.snapshot();
    const encoder = new FrameEncoder(
      "supervisorToMain",
      state.runtimeId!,
      state.generation,
    );
    const send = (
      type: Parameters<FrameEncoder["encode"]>[0],
      payload: Record<string, unknown>,
    ) => c.stdout.write(encoder.encode(type, payload));
    send("booted", { supervisorPid: c.pid, apiPid: 500 });
    return { c, send };
  }
  async function ready() {
    const x = await begin();
    x.send("ready", {
      host: "127.0.0.1",
      port: 9999,
      apiPid: 500,
      apiVersion: 1,
      backendVersion: "0.1.0",
    });
    await Promise.resolve();
    return x;
  }
  return { supervisor, children, health, begin, ready };
}
afterEach(() => vi.useRealTimers());
describe("runtime lifecycle", () => {
  it.each(["ENOENT", "EACCES"])(
    "missing or inaccessible backend %s fails safely",
    async (code) => {
      const supervisor = new RuntimeSupervisor({
        launch: () => {
          throw new Error(code + " SECRET_SENTINEL");
        },
        appDataDir: "C:\\test",
        version: "0.1.0",
        mode: "development",
      });
      await supervisor.start();
      expect(supervisor.snapshot()).toMatchObject({
        state: "failed",
        errorCode: "SPAWN_FAILED",
        canRestart: true,
      });
      expect(JSON.stringify(supervisor.snapshot())).not.toContain(
        "SECRET_SENTINEL",
      );
      await supervisor.stop("app_exit");
      expect(supervisor.snapshot().state).toBe("stopped");
    },
  );
  it("API exit error after ready is disconnected and permits explicit recovery", async () => {
    vi.useFakeTimers();
    const f = fixture();
    const { c, send } = await f.ready();
    send("error", { code: "API_EXITED", message: "SECRET_SENTINEL" });
    c.emit("close", 1);
    expect(f.supervisor.snapshot()).toMatchObject({
      state: "disconnected",
      canRestart: true,
      errorCode: "API_EXITED",
    });
  });
  it("requires authenticated health, waits for stopped AND close, merges duplicate restarts", async () => {
    vi.useFakeTimers();
    const f = fixture();
    const { c, send } = await f.ready();
    expect(f.supervisor.snapshot().state).toBe("ready");
    const first = await f.supervisor.restart(1);
    expect(first.state).toBe("stopping");
    expect(await f.supervisor.restart(1)).toEqual(first);
    send("stop_ack", { forSeq: 2 });
    expect(f.supervisor.snapshot().state).toBe("stopping");
    send("stopped", {
      reason: "user_restart",
      forced: false,
      activeJobProcesses: 0,
    });
    expect(f.children).toHaveLength(1);
    c.emit("close", 0);
    await vi.advanceTimersByTimeAsync(0);
    expect(f.children).toHaveLength(2);
    expect(f.supervisor.snapshot().generation).toBe(2);
    c.emit("close", 1);
    expect(f.supervisor.snapshot().state).toBe("starting");
    await expect(f.supervisor.restart(1)).rejects.toMatchObject({
      code: "STALE_RUNTIME",
    });
  });
  it("close intent prevents a restart already accepted", async () => {
    vi.useFakeTimers();
    const f = fixture();
    const { c, send } = await f.ready();
    await f.supervisor.restart(1);
    const stopping = f.supervisor.stop("app_exit");
    send("stopped", {
      reason: "user_restart",
      forced: false,
      activeJobProcesses: 0,
    });
    c.emit("close");
    await stopping;
    await vi.advanceTimersByTimeAsync(0);
    expect(f.children).toHaveLength(1);
    expect(f.supervisor.snapshot().canRestart).toBe(false);
  });
  it("late health cannot undo closing", async () => {
    vi.useFakeTimers();
    const f = fixture();
    let complete!: (v: HealthData) => void;
    f.health.mockImplementation(
      (e) =>
        new Promise((resolve) => {
          complete = () =>
            resolve({
              status: "ready",
              ...e,
              apiVersion: 1,
              controlVersion: 1,
              uptimeMs: 1,
            });
        }),
    );
    const { c, send } = await f.ready();
    const stopped = f.supervisor.stop("app_exit");
    complete({} as HealthData);
    await Promise.resolve();
    expect(f.supervisor.snapshot().state).toBe("stopping");
    send("stopped", {
      reason: "app_exit",
      forced: false,
      activeJobProcesses: 0,
    });
    c.emit("close");
    await stopped;
  });
  it("three transient health failures disconnect; same instance can recover", async () => {
    vi.useFakeTimers();
    const f = fixture();
    await f.ready();
    f.health
      .mockRejectedValueOnce(new RuntimeError("BACKEND_NOT_READY"))
      .mockRejectedValueOnce(new RuntimeError("BACKEND_UNAVAILABLE"))
      .mockRejectedValueOnce(new RuntimeError("BACKEND_UNAVAILABLE"));
    await vi.advanceTimersByTimeAsync(10000);
    expect(f.supervisor.snapshot().state).toBe("ready");
    await vi.advanceTimersByTimeAsync(5000);
    expect(f.supervisor.snapshot().state).toBe("disconnected");
    await vi.advanceTimersByTimeAsync(5000);
    expect(f.supervisor.snapshot().state).toBe("ready");
  });
  it("authentication failure disconnects immediately without retrying old token", async () => {
    vi.useFakeTimers();
    const f = fixture();
    await f.ready();
    f.health.mockRejectedValue(new RuntimeError("AUTH_INVALID"));
    await vi.advanceTimersByTimeAsync(5000);
    expect(f.supervisor.snapshot().errorCode).toBe("AUTH_INVALID");
    await vi.advanceTimersByTimeAsync(20000);
    expect(f.health).toHaveBeenCalledTimes(2);
  });
  it("stop timeout kills only held child and forbids restart even after exit", async () => {
    vi.useFakeTimers();
    const f = fixture();
    const { c } = await f.ready();
    const stop = f.supervisor.stop("user_restart");
    const rejected = expect(stop).rejects.toMatchObject({
      code: "STOP_TIMEOUT",
    });
    await vi.advanceTimersByTimeAsync(8000);
    await rejected;
    expect(c.kill).toHaveBeenCalledTimes(1);
    c.emit("close");
    expect(f.supervisor.snapshot()).toMatchObject({
      errorCode: "STOP_TIMEOUT",
      canRestart: false,
    });
  });
  it("unexpected exit permits explicit recovery through Job kill-on-close", async () => {
    vi.useFakeTimers();
    const f = fixture();
    const { c } = await f.ready();
    c.emit("close", 1);
    expect(f.supervisor.snapshot()).toMatchObject({
      state: "disconnected",
      canRestart: true,
    });
    await f.supervisor.restart(1);
    await vi.advanceTimersByTimeAsync(0);
    expect(f.children).toHaveLength(2);
  });
  it("startup timeout cleans up and never publishes ready", async () => {
    vi.useFakeTimers();
    const f = fixture();
    const { c, send } = await f.begin();
    await vi.advanceTimersByTimeAsync(30000);
    expect(f.supervisor.snapshot().state).toBe("stopping");
    send("stopped", {
      reason: "user_restart",
      forced: true,
      activeJobProcesses: 0,
    });
    c.emit("close");
    expect(f.supervisor.snapshot()).toMatchObject({
      state: "failed",
      errorCode: "START_TIMEOUT",
      canRestart: true,
    });
  });
  it("versions mismatch and arbitrary child error text never reaches snapshot", async () => {
    vi.useFakeTimers();
    const f = fixture();
    const { c, send } = await f.begin();
    send("ready", {
      host: "127.0.0.1",
      port: 1234,
      apiPid: 500,
      apiVersion: 1,
      backendVersion: "0.2.0",
    });
    send("error", { code: "INTERNAL_ERROR", message: "SECRET_SENTINEL" });
    c.emit("close");
    expect(f.supervisor.snapshot()).toMatchObject({
      state: "incompatible",
      backendVersion: null,
      canRestart: false,
    });
    expect(JSON.stringify(f.supervisor.snapshot())).not.toContain(
      "SECRET_SENTINEL",
    );
  });
  it("stop before spawn still sends init before stop", async () => {
    vi.useFakeTimers();
    const f = fixture();
    await f.supervisor.start();
    const c = f.children[0];
    const chunks: Buffer[] = [];
    c.stdin.on("data", (v: Buffer) => chunks.push(v));
    const stopping = f.supervisor.stop("app_exit");
    c.emit("spawn");
    await vi.advanceTimersByTimeAsync(0);
    const frames = new FrameDecoder("mainToSupervisor").feed(
      Buffer.concat(chunks),
    );
    expect(frames.map((x) => x.type)).toEqual(["init", "stop"]);
    const s = f.supervisor.snapshot();
    c.stdout.write(
      new FrameEncoder("supervisorToMain", s.runtimeId!, s.generation).encode(
        "stopped",
        { reason: "app_exit", forced: false, activeJobProcesses: 0 },
      ),
    );
    c.emit("close");
    await stopping;
  });
});
