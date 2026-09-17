import { randomBytes, randomUUID } from "node:crypto";
import type { ChildProcessWithoutNullStreams } from "node:child_process";
import { FrameDecoder, FrameEncoder, type Frame } from "./control-codec";
import { PipeWriter } from "./pipe-writer";
import { runtimeHttp, type Endpoint, type RuntimeHttp } from "./http-client";
import {
  RuntimeError,
  type RuntimeSnapshot,
  type CapabilitiesData,
} from "../../shared/runtime";

type Reason = "app_exit" | "user_restart";
type Timer = ReturnType<typeof setTimeout>;
interface Context {
  child: ChildProcessWithoutNullStreams;
  id: string;
  generation: number;
  encoder: FrameEncoder;
  decoder: FrameDecoder;
  writer: PipeWriter;
  token: string;
  endpoint?: Endpoint;
  apiPid?: number;
  booted: boolean;
  gotReady: boolean;
  initSent: boolean;
  verified: boolean;
  closed: boolean;
  cleaned: boolean;
  stopped: boolean;
  stopping: boolean;
  stopReason?: Reason;
  failure?: string;
  failures: number;
  stderrBytes: number;
  abort: AbortController;
  startTimer?: Timer;
  healthTimer?: Timer;
  stopTimer?: Timer;
  stopPromise?: Promise<void>;
  resolveStop?: () => void;
  rejectStop?: (e: RuntimeError) => void;
}
export interface SupervisorOptions {
  launch: () => ChildProcessWithoutNullStreams;
  appDataDir: string;
  version: string;
  mode: "development" | "production";
  http?: RuntimeHttp;
}
export class RuntimeSupervisor {
  #state: RuntimeSnapshot;
  #context?: Context;
  #listeners = new Set<(value: RuntimeSnapshot) => void>();
  #closing = false;
  #restart?: { generation: number; accepted: RuntimeSnapshot };
  #http: RuntimeHttp;
  constructor(private readonly options: SupervisorOptions) {
    this.#http = options.http ?? runtimeHttp;
    this.#state = {
      state: "stopped",
      runtimeId: null,
      generation: 0,
      revision: 0,
      frontendVersion: options.version,
      backendVersion: null,
      errorCode: null,
      recoverableAction: "none",
      canRestart: false,
    };
  }
  snapshot(): RuntimeSnapshot {
    return { ...this.#state };
  }
  async withConnection<T>(
    work: (endpoint: Endpoint, signal: AbortSignal) => Promise<T>,
  ): Promise<T> {
    const c = this.#context;
    if (
      !c?.endpoint ||
      !c.verified ||
      this.#state.state !== "ready" ||
      this.#closing
    )
      throw new RuntimeError("BACKEND_UNAVAILABLE");
    const result = await work(c.endpoint, c.abort.signal);
    if (!this.#current(c) || c.stopping || this.#state.state !== "ready")
      throw new RuntimeError("STALE_RUNTIME");
    return result;
  }
  subscribe(listener: (value: RuntimeSnapshot) => void): () => void {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  }
  #publish(
    state: RuntimeSnapshot["state"],
    errorCode: string | null = null,
    cleaned = false,
  ): void {
    this.#state = {
      ...this.#state,
      state,
      errorCode,
      revision: this.#state.revision + 1,
      recoverableAction:
        state === "incompatible"
          ? "repair_installation"
          : errorCode === "STOP_TIMEOUT"
            ? "none"
            : state === "failed" || state === "disconnected"
              ? "restart_backend"
              : "none",
      canRestart:
        !this.#closing &&
        errorCode !== "STOP_TIMEOUT" &&
        (state === "ready" ||
          state === "disconnected" ||
          (state === "failed" && cleaned)),
    };
    for (const listener of this.#listeners) {
      try {
        listener(this.snapshot());
      } catch {
        /* A view cannot stop process cleanup. */
      }
    }
  }
  #current(c: Context): boolean {
    return (
      this.#context === c &&
      this.#state.runtimeId === c.id &&
      this.#state.generation === c.generation
    );
  }
  async start(): Promise<RuntimeSnapshot> {
    if (
      this.#closing ||
      this.#state.state !== "stopped" ||
      this.#state.generation >= 2147483647
    )
      throw new RuntimeError("RUNTIME_BUSY");
    const id = randomUUID(),
      generation = this.#state.generation + 1;
    this.#state = {
      ...this.#state,
      runtimeId: id,
      generation,
      backendVersion: null,
    };
    this.#publish("starting");
    try {
      const child = this.options.launch();
      const c: Context = {
        child,
        id,
        generation,
        encoder: new FrameEncoder("mainToSupervisor", id, generation),
        decoder: new FrameDecoder("supervisorToMain", id, generation),
        writer: undefined as unknown as PipeWriter,
        token: randomBytes(32).toString("base64url"),
        booted: false,
        gotReady: false,
        initSent: false,
        verified: false,
        closed: false,
        cleaned: false,
        stopped: false,
        stopping: false,
        failures: 0,
        stderrBytes: 0,
        abort: new AbortController(),
      };
      this.#context = c;
      c.writer = new PipeWriter(child.stdin, () =>
        this.#fail(c, "PROTOCOL_INVALID", true),
      );
      c.startTimer = setTimeout(() => this.#fail(c, "START_TIMEOUT"), 30000);
      child.on("error", () => this.#fail(c, "SPAWN_FAILED"));
      child.on("close", () => this.#closed(c));
      child.stdout.on("data", (chunk: Buffer) => {
        if (!this.#current(c) || c.closed) return;
        try {
          for (const frame of c.decoder.feed(chunk)) this.#frame(c, frame);
        } catch (error) {
          this.#fail(
            c,
            error instanceof Error &&
              "code" in error &&
              error.code === "VERSION_MISMATCH"
              ? "VERSION_MISMATCH"
              : "PROTOCOL_INVALID",
            true,
          );
        }
      });
      child.stdout.on("error", () => this.#fail(c, "PROTOCOL_INVALID", true));
      child.stdout.on("end", () => {
        if (!this.#current(c) || c.closed) return;
        try {
          c.decoder.eof();
        } catch {
          this.#fail(c, "PROTOCOL_INVALID", true);
        }
        if (!c.stopping && !c.failure)
          this.#fail(c, "BACKEND_UNAVAILABLE", true);
      });
      child.stderr.on("data", (chunk: Buffer) => {
        c.stderrBytes += chunk.length;
        if (c.stderrBytes > 65536) this.#fail(c, "PROTOCOL_INVALID", true);
      });
      child.stderr.on("error", () => this.#fail(c, "PROTOCOL_INVALID", true));
      child.once("spawn", () => {
        if (!this.#current(c)) return;
        c.initSent = true;
        this.#send(c, "init", {
          tokenB64Url: c.token,
          appDataDir: this.options.appDataDir,
          mode: this.options.mode,
          expectedApiVersion: 1,
          expectedBackendVersion: this.options.version,
        });
        if (c.stopping) {
          c.token = "";
          this.#send(c, "stop", { reason: c.stopReason });
        }
      });
    } catch {
      this.#context = undefined;
      this.#publish("failed", "SPAWN_FAILED", true);
    }
    return this.snapshot();
  }
  #send(
    c: Context,
    type: Frame["type"],
    payload: Record<string, unknown>,
  ): void {
    try {
      c.writer.enqueue(c.encoder.encode(type, payload));
    } catch {
      this.#fail(c, "PROTOCOL_INVALID", true);
    }
  }
  #frame(c: Context, frame: Frame): void {
    if (frame.type === "booted") {
      if (c.booted || frame.payload.supervisorPid !== c.child.pid)
        throw new RuntimeError("PROTOCOL_INVALID");
      c.booted = true;
      c.apiPid = frame.payload.apiPid;
    } else if (frame.type === "ready") {
      if (!c.booted || c.gotReady || frame.payload.apiPid !== c.apiPid)
        throw new RuntimeError("PROTOCOL_INVALID");
      c.gotReady = true;
      if (c.stopping || this.#closing) return;
      if (frame.payload.backendVersion !== this.options.version) {
        this.#fail(c, "VERSION_MISMATCH");
        return;
      }
      c.endpoint = {
        port: frame.payload.port,
        token: c.token,
        runtimeId: c.id,
        generation: c.generation,
        backendVersion: this.options.version,
      };
      void this.#health(c);
    } else if (frame.type === "stop_ack") {
      if (!c.stopping || frame.payload.forSeq !== 2)
        throw new RuntimeError("PROTOCOL_INVALID");
    } else if (frame.type === "stopped") {
      if (!c.stopping || c.stopped || frame.payload.reason !== c.stopReason)
        throw new RuntimeError("PROTOCOL_INVALID");
      c.stopped = true;
    } else if (frame.type === "error") {
      // Only the fixed code crosses into state, never child-supplied message text.
      c.failure ??= frame.payload.code;
      this.#fail(c, frame.payload.code);
    } else throw new RuntimeError("PROTOCOL_INVALID");
  }
  async #health(c: Context): Promise<void> {
    if (
      !this.#current(c) ||
      c.stopping ||
      c.closed ||
      this.#closing ||
      !c.endpoint
    )
      return;
    try {
      const health = await this.#http.health(c.endpoint, c.abort.signal);
      if (!this.#current(c) || c.stopping || c.closed || this.#closing) return;
      c.failures = 0;
      c.verified = true;
      clearTimeout(c.startTimer);
      this.#state.backendVersion = health.backendVersion;
      if (this.#state.state !== "ready") this.#publish("ready");
    } catch (error) {
      if (!this.#current(c) || c.stopping || c.closed || this.#closing) return;
      const code =
        error instanceof RuntimeError ? error.code : "BACKEND_UNAVAILABLE";
      if (code === "VERSION_MISMATCH" || code === "PROTOCOL_INVALID") {
        this.#fail(c, code);
        return;
      }
      if (code === "AUTH_INVALID" || code === "AUTH_REQUIRED") {
        clearTimeout(c.startTimer);
        this.#publish("disconnected", code);
        return;
      }
      c.failures++;
      if (
        this.#state.state !== "starting" &&
        c.failures >= 3 &&
        this.#state.state !== "disconnected"
      )
        this.#publish("disconnected", code);
    }
    c.healthTimer = setTimeout(
      () => {
        void this.#health(c);
      },
      this.#state.state === "starting" ? 500 : 5000,
    );
  }
  async getCapabilities(): Promise<CapabilitiesData> {
    const c = this.#context;
    if (!c?.endpoint || this.#state.state !== "ready")
      throw new RuntimeError("BACKEND_UNAVAILABLE");
    const result = await this.#http.capabilities(c.endpoint, c.abort.signal);
    if (
      !this.#current(c) ||
      c.stopping ||
      c.closed ||
      this.#state.state !== "ready"
    )
      throw new RuntimeError("STALE_RUNTIME");
    return result;
  }
  #cancelWork(c: Context): void {
    clearTimeout(c.startTimer);
    clearTimeout(c.healthTimer);
    c.abort.abort();
    c.endpoint = undefined;
    if (c.initSent || c.closed) c.token = "";
  }
  #fail(c: Context, code: string, pipeBroken = false): void {
    if (!this.#current(c) || c.closed || c.failure === "STOP_TIMEOUT") return;
    c.failure ??= code;
    if (!c.stopping) {
      void this.#stopContext(c, "user_restart").catch(() => {});
    }
    if (pipeBroken) c.writer.close(); // EOF asks the owner to terminate its Job immediately.
  }
  #closed(c: Context): void {
    if (!this.#current(c) || c.closed) return;
    c.closed = true;
    clearTimeout(c.stopTimer);
    this.#cancelWork(c);
    c.writer.close();
    // Explicit stops require stopped+close. Crash recovery relies on the sole,
    // non-inheritable Job handle closing with this exact process (T01-A tested).
    c.cleaned =
      (!c.stopping || c.stopped || Boolean(c.failure)) &&
      c.failure !== "STOP_TIMEOUT";
    if (c.stopping && !c.stopped && !c.failure) c.failure = "STOP_TIMEOUT";
    if (c.failure)
      this.#publish(
        c.failure === "VERSION_MISMATCH"
          ? "incompatible"
          : c.verified &&
              ["API_EXITED", "BACKEND_UNAVAILABLE"].includes(c.failure)
            ? "disconnected"
            : "failed",
        c.failure,
        c.cleaned,
      );
    else if (c.stopped) this.#publish("stopped");
    else this.#publish("disconnected", "BACKEND_UNAVAILABLE");
    if (c.cleaned) c.resolveStop?.();
    else c.rejectStop?.(new RuntimeError("STOP_TIMEOUT"));
  }
  #stopContext(c: Context, reason: Reason): Promise<void> {
    if (c.stopPromise) return c.stopPromise;
    if (c.closed)
      return c.cleaned
        ? Promise.resolve()
        : Promise.reject(new RuntimeError("STOP_TIMEOUT"));
    c.stopping = true;
    c.stopReason = reason;
    this.#cancelWork(c);
    this.#publish("stopping");
    c.stopPromise = new Promise<void>((resolve, reject) => {
      c.resolveStop = resolve;
      c.rejectStop = reject;
    });
    c.stopTimer = setTimeout(() => {
      if (!this.#current(c) || c.closed) return;
      c.failure = "STOP_TIMEOUT";
      c.writer.close();
      c.child.kill();
      this.#publish("failed", "STOP_TIMEOUT");
      c.rejectStop?.(new RuntimeError("STOP_TIMEOUT"));
    }, 8000);
    // A close immediately after start still sends init first on the spawn event.
    if (c.initSent) this.#send(c, "stop", { reason });
    return c.stopPromise;
  }
  async stop(reason: Reason): Promise<void> {
    if (reason === "app_exit") this.#closing = true;
    const c = this.#context;
    if (!c) {
      this.#publish("stopped");
      return;
    }
    return this.#stopContext(c, reason);
  }
  async restart(expectedGeneration: number): Promise<RuntimeSnapshot> {
    if (this.#closing) throw new RuntimeError("RUNTIME_BUSY");
    if (this.#restart) {
      if (this.#restart.generation === expectedGeneration)
        return { ...this.#restart.accepted };
      throw new RuntimeError("RUNTIME_BUSY");
    }
    if (expectedGeneration !== this.#state.generation)
      throw new RuntimeError("STALE_RUNTIME");
    if (!this.#state.canRestart) throw new RuntimeError("RUNTIME_BUSY");
    const stopping = this.stop("user_restart");
    const accepted = this.snapshot();
    this.#restart = { generation: expectedGeneration, accepted };
    void stopping
      .then(async () => {
        if (this.#closing) return;
        this.#publish("stopped");
        await this.start();
      })
      .catch(() => {})
      .finally(() => {
        this.#restart = undefined;
      });
    return accepted;
  }
}
