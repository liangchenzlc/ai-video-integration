import { randomUUID } from "node:crypto";
import { request as httpRequest, type IncomingMessage } from "node:http";
import type { RuntimeSupervisor } from "../runtime/supervisor";
import type { ProjectSession } from "../../shared/projects";

const uuid =
  "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
const mediaUrl = new RegExp(`^avi-media://local/(${uuid})/(${uuid})$`);
const maxBytes = 2 * 1024 ** 3;
const chunkBytes = 65536;
const idleMs = 15000;
const mimeTypes = new Set([
  "image/png",
  "image/jpeg",
  "audio/wav",
  "audio/mpeg",
  "audio/mp4",
  "video/mp4",
]);
const safeHeaders = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
};
function empty(status: number): Response {
  return new Response(null, { status, headers: safeHeaders });
}
type ByteRange = { first: number | null; last: number | null };
function parseRange(value: string): ByteRange | null {
  const match = /^bytes=(\d{0,10})-(\d{0,10})$/.exec(value);
  if (!match || (!match[1] && !match[2])) return null;
  const first = match[1] ? Number(match[1]) : null;
  const last = match[2] ? Number(match[2]) : null;
  if (first === null ? last === 0 : last !== null && last < first) return null;
  return { first, last };
}
function selected(range: ByteRange, size: number): [number, number] | null {
  const start = range.first ?? Math.max(0, size - range.last!);
  const end =
    range.first === null
      ? size - 1
      : Math.min(range.last ?? size - 1, size - 1);
  return start <= end ? [start, end] : null;
}
function checkedHeaders(
  res: IncomingMessage,
  requestId: string,
  range: ByteRange | null,
): Headers {
  const headers: Record<string, string> = {};
  for (let index = 0; index < res.rawHeaders.length; index += 2) {
    const key = res.rawHeaders[index].toLowerCase();
    if (Object.hasOwn(headers, key)) throw new Error();
    headers[key] = res.rawHeaders[index + 1];
  }
  const length = headers["content-length"];
  if (
    headers["x-request-id"] !== requestId ||
    headers["cache-control"] !== "no-store" ||
    headers["x-content-type-options"] !== "nosniff" ||
    Object.hasOwn(headers, "content-encoding") ||
    Object.hasOwn(headers, "transfer-encoding") ||
    Object.hasOwn(headers, "location") ||
    !/^(0|[1-9]\d{0,9})$/.test(length ?? "") ||
    Number(length) > maxBytes ||
    headers["accept-ranges"] !== "bytes"
  )
    throw new Error();
  const status = res.statusCode!;
  const contentRange = headers["content-range"];
  if (status === 416) {
    const match = /^bytes \*\/([1-9]\d{0,9})$/.exec(contentRange ?? "");
    if (
      !range ||
      !match ||
      Number(match[1]) > maxBytes ||
      selected(range, Number(match[1])) ||
      length !== "0"
    )
      throw new Error();
  } else {
    if (!mimeTypes.has(headers["content-type"]) || Number(length) === 0)
      throw new Error();
    if (status === 200) {
      if (range || contentRange !== undefined) throw new Error();
    } else if (status === 206) {
      const match =
        /^bytes (0|[1-9]\d{0,9})-(0|[1-9]\d{0,9})\/([1-9]\d{0,9})$/.exec(
          contentRange ?? "",
        );
      if (!range || !match || Number(match[3]) > maxBytes) throw new Error();
      const expected = selected(range, Number(match[3]));
      if (
        !expected ||
        Number(match[1]) !== expected[0] ||
        Number(match[2]) !== expected[1] ||
        Number(length) !== expected[1] - expected[0] + 1
      )
        throw new Error();
    } else throw new Error();
  }
  // Never reflect arbitrary backend headers, paths, URLs, or credentials.
  const output = new Headers(safeHeaders);
  output.set("Content-Length", length);
  output.set("Accept-Ranges", "bytes");
  if (status !== 416) output.set("Content-Type", headers["content-type"]);
  if (contentRange) output.set("Content-Range", contentRange);
  return output;
}

export async function serveMedia(
  request: Request,
  supervisor: RuntimeSupervisor,
  getSession: () => ProjectSession | null,
  windowId: number,
): Promise<Response> {
  const match = mediaUrl.exec(request.url);
  if (!match || !Number.isSafeInteger(windowId) || windowId <= 0)
    return empty(400);
  if (request.method !== "GET" && request.method !== "HEAD") return empty(405);
  const rawRange = request.headers.get("range");
  const range = rawRange === null ? null : parseRange(rawRange);
  if (rawRange !== null && !range) return empty(400);
  const session = getSession();
  if (!session || session.projectId !== match[1]) return empty(403);
  const sessionId = session.projectSessionId;
  const current = () => {
    const value = getSession();
    return (
      value?.projectId === match[1] && value.projectSessionId === sessionId
    );
  };
  let cancelConnection = () => {};
  try {
    return await supervisor.withConnection(
      (endpoint, runtimeSignal) =>
        new Promise<Response>((resolve) => {
          if (request.signal.aborted || runtimeSignal.aborted) {
            resolve(empty(503));
            return;
          }
          if (!current()) {
            resolve(empty(403));
            return;
          }
          const requestId = randomUUID();
          let incoming: IncomingMessage | undefined;
          let controller:
            ReadableStreamDefaultController<Uint8Array> | undefined;
          let done = false;
          let replied = false;
          let bytes = 0;
          let expected = 0;
          let timer: ReturnType<typeof setTimeout> | undefined;
          const cleanup = () => {
            clearTimeout(timer);
            request.signal.removeEventListener("abort", aborted);
            runtimeSignal.removeEventListener("abort", aborted);
          };
          const fail = (status = 502) => {
            if (done) return;
            done = true;
            cleanup();
            incoming?.destroy();
            req.destroy();
            if (replied) controller?.error(new Error("Media unavailable"));
            else {
              replied = true;
              resolve(empty(status));
            }
          };
          const aborted = () => fail(503);
          const armTimeout = () => {
            clearTimeout(timer);
            timer = setTimeout(() => fail(504), idleMs);
            timer.unref();
          };
          const pump = () => {
            if (done || !incoming || !controller) return;
            if (!current()) {
              fail(403);
              return;
            }
            clearTimeout(timer);
            while (
              (controller.desiredSize ?? 0) > 0 &&
              incoming.readableLength > 0
            ) {
              if (!current()) {
                fail(403);
                return;
              }
              const chunk: Buffer | null = incoming.read(
                Math.min(chunkBytes, incoming.readableLength),
              );
              if (!chunk) break;
              bytes += chunk.length;
              if (bytes > expected) {
                fail();
                return;
              }
              controller.enqueue(
                new Uint8Array(chunk.buffer, chunk.byteOffset, chunk.length),
              );
            }
            // read(0) lets a paused IncomingMessage publish EOF after its last chunk.
            if (incoming.readableLength === 0) incoming.read(0);
            // Consumer backpressure is not a network stall. Only time actual reads.
            if ((controller.desiredSize ?? 0) > 0) armTimeout();
          };
          const req = httpRequest(
            {
              hostname: "127.0.0.1",
              port: endpoint.port,
              path: `/api/v1/projects/${match[1]}/media/${match[2]}`,
              method: request.method,
              agent: false,
              maxHeaderSize: 8192,
              headers: {
                Authorization: `Bearer ${endpoint.token}`,
                "X-Request-Id": requestId,
                "X-Window-Id": String(windowId),
                "X-Project-Session": sessionId,
                ...(rawRange === null ? {} : { Range: rawRange }),
              },
            },
            (res) => {
              incoming = res;
              res.on("error", () => fail());
              res.on("aborted", () => fail());
              if (done) {
                res.destroy();
                return;
              }
              if (!current()) {
                fail(403);
                return;
              }
              if (request.signal.aborted || runtimeSignal.aborted) {
                fail(503);
                return;
              }
              const status = res.statusCode ?? 502;
              if (![200, 206, 416].includes(status)) {
                fail(
                  [400, 401, 403, 404, 409, 422, 500, 503].includes(status)
                    ? status
                    : 502,
                );
                return;
              }
              let headers: Headers;
              try {
                headers = checkedHeaders(res, requestId, range);
              } catch {
                fail();
                return;
              }
              expected = Number(headers.get("content-length"));
              clearTimeout(timer);
              if (request.method === "HEAD" || status === 416) {
                done = true;
                replied = true;
                cleanup();
                res.destroy();
                req.destroy();
                resolve(new Response(null, { status, headers }));
                return;
              }
              const body = new ReadableStream<Uint8Array>(
                {
                  start(value) {
                    controller = value;
                  },
                  pull() {
                    pump();
                  },
                  cancel() {
                    if (done) return;
                    done = true;
                    cleanup();
                    res.destroy();
                    req.destroy();
                  },
                },
                {
                  highWaterMark: chunkBytes,
                  size: (chunk) => chunk.byteLength,
                },
              );
              res.on("readable", pump);
              res.on("end", () => {
                if (done) return;
                if (!current() || bytes !== expected || !res.complete) {
                  fail();
                  return;
                }
                done = true;
                cleanup();
                controller!.close();
              });
              replied = true;
              resolve(new Response(body, { status, headers }));
              pump();
            },
          );
          cancelConnection = aborted;
          request.signal.addEventListener("abort", aborted, { once: true });
          runtimeSignal.addEventListener("abort", aborted, { once: true });
          req.on("error", () => fail(503));
          armTimeout();
          req.end();
        }),
    );
  } catch {
    cancelConnection();
    return empty(503);
  }
}
