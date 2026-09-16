import { request } from "node:http";
import { randomUUID } from "node:crypto";
import { TextDecoder } from "node:util";
import { z } from "zod";
import type { Endpoint } from "../runtime/http-client";
import { uniqueKeysAndUnicode } from "../runtime/control-codec";
import { RuntimeError } from "../../shared/runtime";
import { projectUuid, projectMessages } from "../../shared/projects";

const uuidPattern =
  "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
const allowed: Record<string, RegExp> = {
  POST: new RegExp(
    `^/api/v1/(?:file-grants|projects|project-sessions|connection-checks|credentials/[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}/delete|projects/${uuidPattern}/(?:imports|media/${uuidPattern}/relocate|jobs/${uuidPattern}/cancel))$`,
  ),
  GET: new RegExp(
    `^/api/v1/(?:settings(?:/details)?|jobs/${uuidPattern}|recent-projects|projects/${uuidPattern}(?:/stage-models|/drafts(?:/${uuidPattern})?|/operations/${uuidPattern}|/jobs(?:/${uuidPattern})?|/media(?:/${uuidPattern}/metadata|\\?limit=[0-9]{1,3}(?:&cursor=${uuidPattern})?)?)?|operations/${uuidPattern}|private/recent-projects/${uuidPattern}/directory)$`,
  ),
  PUT: new RegExp(
    `^/api/v1/(?:projects/${uuidPattern}/(?:drafts/${uuidPattern}|stage-models)|settings/(?:media-tools|storage)|credentials/[a-zA-Z0-9][a-zA-Z0-9._-]{0,99})$`,
  ),
  DELETE: new RegExp(`^/api/v1/project-sessions/${uuidPattern}$`),
};
const taskAllowed: Record<string, RegExp> = {
  GET: new RegExp(
    `^/api/v1/(?:task-activity|projects/${uuidPattern}/(?:budget|task-plans/${uuidPattern}|tasks/${uuidPattern}(?:/candidates\\?limit=[0-9]{1,3}(?:&cursor=${uuidPattern})?)?|calls/${uuidPattern}|cost-summary|(?:tasks|cost-entries)(?:\\?limit=[0-9]{1,3}(?:&cursor=${uuidPattern})?)?))$`,
  ),
  POST: new RegExp(
    `^/api/v1/projects/${uuidPattern}/(?:task-plans|tasks|tasks/${uuidPattern}/continue|calls/${uuidPattern}/(?:recovery|settlements))$`,
  ),
  PUT: new RegExp(
    `^/api/v1/projects/${uuidPattern}/(?:budget|external-expenses/${uuidPattern})$`,
  ),
};
const versionAllowed: Record<string, RegExp> = {
  GET: new RegExp(
    `^/api/v1/projects/${uuidPattern}/(?:artifacts/${uuidPattern}(?:/revisions\\?limit=[0-9]{1,3}(?:&cursor=${uuidPattern})?)?|check-reports/${uuidPattern})$`,
  ),
  POST: new RegExp(
    `^/api/v1/projects/${uuidPattern}/(?:artifacts/${uuidPattern}/(?:revisions|adoption-preview|adoptions|confirmations)|adoptions/${uuidPattern}/undo|local-checks)$`,
  ),
};
const storyboardAllowed: Record<string, RegExp> = {
  GET: new RegExp(
    `^/api/v1/projects/${uuidPattern}/(?:storyboard|coverage|storyboard/shots/${uuidPattern}/prompt\\?phase=(?:image|video))$`,
  ),
  PUT: new RegExp(`^/api/v1/projects/${uuidPattern}/shot-order$`),
  POST: new RegExp(`^/api/v1/projects/${uuidPattern}/references/verification$`),
};
const productionAllowed: Record<string, RegExp> = {
  GET: new RegExp(
    `^/api/v1/projects/${uuidPattern}/(?:production\\?offset=[0-9]{1,9}|rights|exports/${uuidPattern}|render-plans/${uuidPattern}|issues\\?limit=[0-9]{1,3}(?:&cursor=${uuidPattern})?)$`,
  ),
  POST: new RegExp(
    `^/api/v1/(?:diagnostics(?:/preview)?|projects/${uuidPattern}/(?:timing-checks|video-readiness|mix/ducking|timeline/(?:edit-preview|replacement-preview)|render-plan-preview|animatics|exports|issues/${uuidPattern}/decisions))$`,
  ),
  PUT: new RegExp(`^/api/v1/projects/${uuidPattern}/rights/${uuidPattern}$`),
};
export async function businessRequest<T>(
  endpoint: Endpoint,
  signal: AbortSignal,
  options: {
    method: "GET" | "POST" | "PUT" | "DELETE";
    path: string;
    windowId: number;
    body?: unknown;
    sessionId?: string;
    schema: z.ZodType<T>;
  },
): Promise<T> {
  if (
    !(
      allowed[options.method].test(options.path) ||
      taskAllowed[options.method]?.test(options.path) ||
      versionAllowed[options.method]?.test(options.path) ||
      storyboardAllowed[options.method]?.test(options.path) ||
      productionAllowed[options.method]?.test(options.path)
    ) ||
    !Number.isSafeInteger(options.windowId) ||
    options.windowId < 1
  )
    throw new RuntimeError("REQUEST_INVALID");
  const body =
    options.body === undefined
      ? undefined
      : Buffer.from(JSON.stringify(options.body), "utf8");
  if (
    body &&
    (body.length > 1048576 || !["POST", "PUT"].includes(options.method))
  )
    throw new RuntimeError("REQUEST_INVALID");
  const requestId = randomUUID();
  return new Promise<T>((resolve, reject) => {
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
        path: options.path,
        method: options.method,
        agent: false,
        signal,
        maxHeaderSize: 8192,
        headers: {
          Authorization: `Bearer ${endpoint.token}`,
          "X-Request-Id": requestId,
          "X-Window-Id": String(options.windowId),
          Accept: "application/json",
          ...(options.sessionId
            ? { "X-Project-Session": options.sessionId }
            : {}),
          ...(body
            ? {
                "Content-Type": "application/json",
                "Content-Length": body.length,
              }
            : {}),
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
          headers["x-request-id"] !== requestId ||
          headers["cache-control"] !== "no-store" ||
          headers["x-content-type-options"] !== "nosniff" ||
          headers["content-encoding"] ||
          (headers["content-length"] &&
            (!/^\d+$/.test(headers["content-length"]) ||
              Number(headers["content-length"]) > 1048576))
        ) {
          fail("PROTOCOL_INVALID");
          return;
        }
        const chunks: Buffer[] = [];
        let size = 0;
        res.on("data", (chunk: Buffer) => {
          size += chunk.length;
          if (size > 1048576) fail("PROTOCOL_INVALID");
          else chunks.push(chunk);
        });
        res.on("error", () => fail("BACKEND_UNAVAILABLE"));
        res.on("end", () => {
          if (done) return;
          try {
            const source = new TextDecoder("utf-8", {
              fatal: true,
              ignoreBOM: true,
            }).decode(Buffer.concat(chunks));
            uniqueKeysAndUnicode(source);
            const value: unknown = JSON.parse(source);
            if (![200, 201, 202].includes(res.statusCode ?? 0)) {
              const error = z
                .strictObject({
                  requestId: projectUuid,
                  error: z.strictObject({
                    code: z.string(),
                    message: z.string().max(256),
                    affectedIds: z.array(projectUuid).max(100),
                    recoverableAction: z.string(),
                  }),
                })
                .parse(value);
              if (
                error.requestId !== requestId ||
                !Object.hasOwn(projectMessages, error.error.code)
              ) {
                fail("PROTOCOL_INVALID");
                return;
              }
              fail(error.error.code);
              return;
            }
            const parsed = z
              .strictObject({ requestId: projectUuid, data: options.schema })
              .parse(value);
            if (parsed.requestId !== requestId) {
              fail("PROTOCOL_INVALID");
              return;
            }
            done = true;
            clearTimeout(timer);
            resolve(parsed.data);
          } catch {
            fail("PROTOCOL_INVALID");
          }
        });
      },
    );
    const timer = setTimeout(() => fail("BACKEND_UNAVAILABLE"), 15000);
    req.on("error", () => fail("BACKEND_UNAVAILABLE"));
    req.end(body);
  });
}
