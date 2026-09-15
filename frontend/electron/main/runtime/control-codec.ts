import { win32 } from "node:path";
import { TextDecoder } from "node:util";
import { z } from "zod";

export const FRAME_LIMIT = 16 * 1024;
export const WRITE_LIMIT = 64 * 1024;
export const WRITE_TIMEOUT_MS = 2000;
export type Direction =
  | "mainToSupervisor"
  | "supervisorToApi"
  | "apiToSupervisor"
  | "supervisorToMain";

export class ProtocolError extends Error {
  constructor(readonly code = "PROTOCOL_INVALID") {
    super("控制协议无效。");
    this.name = "ProtocolError";
  }
}

const integer = z.number().refine(Number.isInteger);
const generation = integer.refine((v) => v >= 1 && v <= 2147483647);
const pid = integer.refine((v) => v >= 1);
const uuid = z
  .string()
  .refine(
    (v) =>
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
        v,
      ) && v.length === 36,
  );
const version = z
  .string()
  .refine((v) => /^[0-9]+\.[0-9]+\.[0-9]+$/.test(v) && !/[\r\n]/.test(v));
const reason = z.enum(["app_exit", "user_restart"]);
const base = {
  protocolVersion: z.literal(1),
  runtimeId: uuid,
  generation,
  seq: generation,
};
const shape = {
  init: z.strictObject({
    tokenB64Url: z
      .string()
      .refine(
        (v) =>
          /^[A-Za-z0-9_-]{43}$/.test(v) &&
          v.length === 43 &&
          Buffer.from(v, "base64url").length === 32 &&
          Buffer.from(v, "base64url").toString("base64url") === v,
      ),
    appDataDir: z
      .string()
      .refine(
        (v) =>
          [...v].length >= 1 &&
          [...v].length <= 1024 &&
          win32.isAbsolute(v) &&
          win32.parse(v).root.length > 1 &&
          !/[\u0000-\u001f]/.test(v),
      ),
    mode: z.enum(["development", "production"]),
    expectedApiVersion: z.literal(1),
    expectedBackendVersion: version,
  }),
  booted: z.strictObject({ supervisorPid: pid, apiPid: pid }),
  ready: z.strictObject({
    host: z.literal("127.0.0.1"),
    port: integer.refine((v) => v >= 1 && v <= 65535),
    apiPid: pid,
    apiVersion: z.literal(1),
    backendVersion: version,
  }),
  stop: z.strictObject({ reason }),
  stop_ack: z.strictObject({ forSeq: generation }),
  stopped: z.strictObject({
    reason,
    forced: z.boolean(),
    activeJobProcesses: z.literal(0),
  }),
  error: z.strictObject({
    code: z.enum([
      "INIT_TIMEOUT",
      "PROTOCOL_INVALID",
      "JOB_SETUP_FAILED",
      "API_SPAWN_FAILED",
      "API_EXITED",
      "START_TIMEOUT",
      "STOP_TIMEOUT",
      "BIND_FAILED",
      "BACKEND_ALREADY_RUNNING",
      "INTERNAL_ERROR",
    ]),
    message: z
      .string()
      .refine((v) => [...v].length >= 1 && [...v].length <= 256),
  }),
};
const frameSchema = z.discriminatedUnion("type", [
  z.strictObject({ ...base, type: z.literal("init"), payload: shape.init }),
  z.strictObject({ ...base, type: z.literal("booted"), payload: shape.booted }),
  z.strictObject({ ...base, type: z.literal("ready"), payload: shape.ready }),
  z.strictObject({ ...base, type: z.literal("stop"), payload: shape.stop }),
  z.strictObject({
    ...base,
    type: z.literal("stop_ack"),
    payload: shape.stop_ack,
  }),
  z.strictObject({
    ...base,
    type: z.literal("stopped"),
    payload: shape.stopped,
  }),
  z.strictObject({ ...base, type: z.literal("error"), payload: shape.error }),
]);
export type Frame = z.infer<typeof frameSchema>;
const allowed: Record<Direction, readonly Frame["type"][]> = {
  mainToSupervisor: ["init", "stop"],
  supervisorToApi: ["init", "stop"],
  apiToSupervisor: ["ready", "stop_ack", "error"],
  supervisorToMain: ["booted", "ready", "stop_ack", "stopped", "error"],
};

export function uniqueKeysAndUnicode(source: string): void {
  // Native JSON.parse checks syntax first. Scan its original tokens separately
  // because a reviver cannot see duplicate object keys after JSON.parse merges them.
  const stack: Array<{ keys: Set<string>; expectKey: boolean } | null> = [];
  for (let i = 0; i < source.length; i++) {
    const char = source[i];
    if (char === "{") stack.push({ keys: new Set(), expectKey: true });
    else if (char === "[") stack.push(null);
    else if (char === "}" || char === "]") stack.pop();
    else if (char === ",") {
      const top = stack.at(-1);
      if (top) top.expectKey = true;
    } else if (char === '"') {
      const start = i++;
      while (i < source.length && source[i] !== '"') {
        if (source[i] === "\\") i++;
        i++;
      }
      const value = JSON.parse(source.slice(start, i + 1)) as string;
      for (const point of value) {
        const code = point.codePointAt(0)!;
        if (code >= 0xd800 && code <= 0xdfff) throw new ProtocolError();
      }
      const top = stack.at(-1);
      if (top?.expectKey) {
        if (top.keys.has(value)) throw new ProtocolError();
        top.keys.add(value);
        top.expectKey = false;
      }
    }
    if (stack.length > 32) throw new ProtocolError();
  }
}

export function parseFrame(raw: Buffer): Frame {
  try {
    if (
      !raw.length ||
      raw.length + 1 > FRAME_LIMIT ||
      raw.includes(13) ||
      raw.includes(10) ||
      raw.subarray(0, 3).equals(Buffer.from([0xef, 0xbb, 0xbf]))
    )
      throw new ProtocolError();
    const source = new TextDecoder("utf-8", {
      fatal: true,
      ignoreBOM: true,
    }).decode(raw);
    const value: unknown = JSON.parse(source);
    uniqueKeysAndUnicode(source);
    if (
      value &&
      typeof value === "object" &&
      "protocolVersion" in value &&
      Number.isInteger(value.protocolVersion) &&
      value.protocolVersion !== 1
    )
      throw new ProtocolError("VERSION_MISMATCH");
    if (
      value &&
      typeof value === "object" &&
      "type" in value &&
      value.type === "ready" &&
      "payload" in value &&
      value.payload &&
      typeof value.payload === "object" &&
      "apiVersion" in value.payload &&
      Number.isInteger(value.payload.apiVersion) &&
      value.payload.apiVersion !== 1
    )
      throw new ProtocolError("VERSION_MISMATCH");
    return frameSchema.parse(value);
  } catch (error) {
    throw error instanceof ProtocolError ? error : new ProtocolError();
  }
}

export class FrameDecoder {
  #pending = Buffer.alloc(0);
  #seq = 1;
  #closed = false;
  #runtimeId: string | undefined;
  #generation: number | undefined;
  constructor(
    readonly direction: Direction,
    runtimeId?: string,
    generationValue?: number,
  ) {
    if (
      !allowed[direction] ||
      (runtimeId === undefined) !== (generationValue === undefined)
    )
      throw new Error("Invalid control channel configuration");
    if (
      (direction === "apiToSupervisor" || direction === "supervisorToMain") &&
      !runtimeId
    )
      throw new Error("Child output requires expected identity");
    this.#runtimeId = runtimeId;
    this.#generation = generationValue;
  }
  #accept(frame: Frame): void {
    if (
      !allowed[this.direction].includes(frame.type) ||
      frame.seq !== this.#seq
    )
      throw new ProtocolError();
    if (
      this.direction === "mainToSupervisor" ||
      this.direction === "supervisorToApi"
    ) {
      if ((frame.seq === 1) !== (frame.type === "init"))
        throw new ProtocolError();
    }
    if (!this.#runtimeId) {
      this.#runtimeId = frame.runtimeId;
      this.#generation = frame.generation;
    }
    if (
      frame.runtimeId !== this.#runtimeId ||
      frame.generation !== this.#generation
    )
      throw new ProtocolError();
    this.#seq++;
  }
  feed(chunk: Buffer): Frame[] {
    if (this.#closed) throw new ProtocolError();
    const frames: Frame[] = [];
    let offset = 0;
    try {
      while (offset < chunk.length) {
        const end = chunk.indexOf(10, offset);
        const stop = end < 0 ? chunk.length : end;
        if (this.#pending.length + stop - offset + 1 > FRAME_LIMIT)
          throw new ProtocolError();
        this.#pending = Buffer.concat([
          this.#pending,
          chunk.subarray(offset, stop),
        ]);
        if (end < 0) break;
        const frame = parseFrame(this.#pending);
        this.#pending = Buffer.alloc(0);
        this.#accept(frame);
        frames.push(frame);
        offset = end + 1;
      }
      return frames;
    } catch (error) {
      this.#pending = Buffer.alloc(0);
      this.#closed = true;
      throw error instanceof ProtocolError ? error : new ProtocolError();
    }
  }
  eof(): void {
    const failed = this.#closed || this.#pending.length > 0;
    this.#pending = Buffer.alloc(0);
    this.#closed = true;
    if (failed) throw new ProtocolError();
  }
}

export class FrameEncoder {
  #seq = 1;
  #checker: FrameDecoder;
  constructor(
    direction: Direction,
    private readonly runtimeId: string,
    private readonly generation: number,
  ) {
    this.#checker = new FrameDecoder(direction, runtimeId, generation);
  }
  encode(type: Frame["type"], payload: Record<string, unknown>): Buffer {
    try {
      const value: unknown = {
        protocolVersion: 1,
        runtimeId: this.runtimeId,
        generation: this.generation,
        seq: this.#seq,
        type,
        payload,
      };
      // Validate before JSON.stringify can silently drop undefined or turn NaN into null.
      frameSchema.parse(value);
      const raw = Buffer.from(JSON.stringify(value) + "\n", "utf8");
      this.#checker.feed(raw);
      this.#seq++;
      return raw;
    } catch {
      throw new ProtocolError();
    }
  }
}
