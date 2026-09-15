import { request } from "node:http";
import { randomUUID } from "node:crypto";
import { TextDecoder } from "node:util";
import { z } from "zod";
import { uniqueKeysAndUnicode } from "./control-codec";
import {
  RuntimeError,
  type HealthData,
  type CapabilitiesData,
} from "../../shared/runtime";

const uuid = z
  .string()
  .regex(
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  );
const generation = z.number().int().min(1).max(2147483647);
const identity = { runtimeId: uuid, generation };
const health = z.strictObject({
  ...identity,
  status: z.literal("ready"),
  apiVersion: z.number().int(),
  controlVersion: z.number().int(),
  backendVersion: z.string().regex(/^\d+\.\d+\.\d+$/),
  uptimeMs: z.number().int().min(0).max(Number.MAX_SAFE_INTEGER),
});
export const capabilityIds = [
  "runtime",
  "projects",
  "credentials",
  "story",
  "visualAssets",
  "storyboard",
  "video",
  "audio",
  "timeline",
  "checks",
  "exports",
  "costs",
] as const;
const capabilities = z.strictObject({
  ...identity,
  capabilities: z
    .array(
      z.strictObject({
        id: z.enum(capabilityIds),
        enabled: z.boolean(),
        reasonCode: z.enum(["AVAILABLE", "NOT_IMPLEMENTED"]),
      }),
    )
    .length(12),
});
const errors: Record<string, [number, string]> = {
  REQUEST_INVALID: [400, "none"],
  AUTH_REQUIRED: [401, "restart_backend"],
  AUTH_INVALID: [401, "restart_backend"],
  HOST_REJECTED: [403, "none"],
  ORIGIN_REJECTED: [403, "none"],
  NOT_FOUND: [404, "none"],
  METHOD_NOT_ALLOWED: [405, "none"],
  INTERNAL_ERROR: [500, "restart_backend"],
  BACKEND_NOT_READY: [503, "retry_connection"],
};
const errorSchema = z.strictObject({
  requestId: uuid,
  error: z.strictObject({
    code: z.string(),
    message: z.string().min(1).max(256),
    affectedIds: z.array(uuid).length(0),
    recoverableAction: z.string(),
  }),
});
export interface Endpoint {
  port: number;
  token: string;
  runtimeId: string;
  generation: number;
  backendVersion: string;
}
export interface RuntimeHttp {
  health(endpoint: Endpoint, signal: AbortSignal): Promise<HealthData>;
  capabilities(
    endpoint: Endpoint,
    signal: AbortSignal,
  ): Promise<CapabilitiesData>;
}

async function get(
  endpoint: Endpoint,
  kind: "health" | "capabilities",
  signal: AbortSignal,
): Promise<HealthData | CapabilitiesData> {
  const requestId = randomUUID();
  const raw = await new Promise<{
    body: Buffer;
    status: number;
    headers: Record<string, string>;
  }>((resolve, reject) => {
    let done = false;
    const fail = (code: string) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      req.destroy();
      reject(new RuntimeError(code));
    };
    const req = request(
      {
        hostname: "127.0.0.1",
        port: endpoint.port,
        method: "GET",
        path: `/api/v1/${kind}`,
        agent: false,
        signal,
        maxHeaderSize: 8192,
        headers: {
          Authorization: `Bearer ${endpoint.token}`,
          "X-Request-Id": requestId,
          Accept: "application/json",
        },
      },
      (res) => {
        const headers: Record<string, string> = {};
        for (let i = 0; i < res.rawHeaders.length; i += 2) {
          const key = res.rawHeaders[i].toLowerCase();
          if (Object.hasOwn(headers, key)) {
            fail("PROTOCOL_INVALID");
            return;
          }
          headers[key] = res.rawHeaders[i + 1];
        }
        if (
          !/^application\/json(?:;\s*charset=utf-8)?$/i.test(
            headers["content-type"] ?? "",
          ) ||
          headers["cache-control"] !== "no-store" ||
          headers["x-content-type-options"] !== "nosniff" ||
          headers["x-request-id"] !== requestId ||
          headers["content-encoding"] ||
          (headers["content-length"] &&
            (!/^\d+$/.test(headers["content-length"]) ||
              Number(headers["content-length"]) > 65536))
        ) {
          fail("PROTOCOL_INVALID");
          return;
        }
        const chunks: Buffer[] = [];
        let bytes = 0;
        res.on("data", (chunk: Buffer) => {
          bytes += chunk.length;
          if (bytes > 65536) fail("PROTOCOL_INVALID");
          else chunks.push(chunk);
        });
        res.on("error", () => fail("BACKEND_UNAVAILABLE"));
        res.on("end", () => {
          if (done) return;
          done = true;
          clearTimeout(timer);
          resolve({
            body: Buffer.concat(chunks),
            status: res.statusCode ?? 0,
            headers,
          });
        });
      },
    );
    const timer = setTimeout(() => fail("BACKEND_UNAVAILABLE"), 1500);
    req.on("error", () => fail("BACKEND_UNAVAILABLE"));
    req.end();
  });
  try {
    const source = new TextDecoder("utf-8", {
      fatal: true,
      ignoreBOM: true,
    }).decode(raw.body);
    const value: unknown = JSON.parse(source);
    uniqueKeysAndUnicode(source);
    if (raw.status !== 200) {
      const parsed = errorSchema.parse(value);
      const expected = errors[parsed.error.code];
      if (
        parsed.requestId !== requestId ||
        !expected ||
        (raw.status !== expected[0] &&
          !(raw.status === 422 && parsed.error.code === "REQUEST_INVALID")) ||
        parsed.error.recoverableAction !== expected[1]
      )
        throw new RuntimeError("PROTOCOL_INVALID");
      throw new RuntimeError(parsed.error.code);
    }
    const parsed = z
      .strictObject({
        requestId: uuid,
        data: kind === "health" ? health : capabilities,
      })
      .parse(value);
    if (
      parsed.requestId !== requestId ||
      parsed.data.runtimeId !== endpoint.runtimeId ||
      parsed.data.generation !== endpoint.generation
    )
      throw new RuntimeError("PROTOCOL_INVALID");
    if ("status" in parsed.data) {
      if (
        parsed.data.apiVersion !== 1 ||
        parsed.data.controlVersion !== 1 ||
        parsed.data.backendVersion !== endpoint.backendVersion
      )
        throw new RuntimeError("VERSION_MISMATCH");
      return parsed.data as HealthData;
    }
    if (
      parsed.data.capabilities.some(
        (c, i) =>
          c.id !== capabilityIds[i] ||
          c.enabled !== (i === 0) ||
          c.reasonCode !== (i === 0 ? "AVAILABLE" : "NOT_IMPLEMENTED"),
      )
    )
      throw new RuntimeError("PROTOCOL_INVALID");
    return parsed.data;
  } catch (error) {
    throw error instanceof RuntimeError
      ? error
      : new RuntimeError("PROTOCOL_INVALID");
  }
}
export const runtimeHttp: RuntimeHttp = {
  health: (e, s) => get(e, "health", s) as Promise<HealthData>,
  capabilities: (e, s) =>
    get(e, "capabilities", s) as Promise<CapabilitiesData>,
};
