import {
  createServer,
  type IncomingMessage,
  type ServerResponse,
} from "node:http";
import { afterEach, expect, it, vi } from "vitest";
import { serveMedia } from "../../electron/main/projects/media-stream";
import type { RuntimeSupervisor } from "../../electron/main/runtime/supervisor";
import type { Endpoint } from "../../electron/main/runtime/http-client";
import type { ProjectSession } from "../../electron/shared/projects";

const projectId = "11111111-1111-4111-8111-111111111111";
const mediaId = "22222222-2222-4222-8222-222222222222";
const sessionId = "33333333-3333-4333-8333-333333333333";
const url = `avi-media://local/${projectId}/${mediaId}`;
const session: ProjectSession = {
  projectId,
  projectSessionId: sessionId,
  mode: "write",
  project: {
    id: projectId,
    name: "test",
    revision: 0,
    eventSequence: 0,
    formatVersion: 1,
    aspect: "16:9",
    resolution: "720p",
    fps: { numerator: 24, denominator: 1 },
    targetMs: 1000,
    budgetMicroCny: 0,
    executionMode: null,
    savedAt: null,
    readOnly: false,
  },
};
const servers: ReturnType<typeof createServer>[] = [];
afterEach(async () => {
  vi.useRealTimers();
  for (const server of servers.splice(0)) {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
async function fixture(
  handler: (req: IncomingMessage, res: ServerResponse) => void,
) {
  const runtime = new AbortController();
  const server = createServer((req, res) => {
    res.setHeader("X-Request-Id", req.headers["x-request-id"]!);
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Content-Type", "video/mp4");
    res.setHeader("Content-Length", "10");
    res.setHeader("Accept-Ranges", "bytes");
    handler(req, res);
  });
  servers.push(server);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const endpoint: Endpoint = {
    port: (server.address() as { port: number }).port,
    token: "SECRET_TOKEN",
    runtimeId: projectId,
    generation: 1,
    backendVersion: "0.1.0",
  };
  const supervisor = {
    withConnection: <T>(
      work: (e: Endpoint, signal: AbortSignal) => Promise<T>,
    ) => work(endpoint, runtime.signal),
  } as RuntimeSupervisor;
  return { supervisor, runtime };
}

it("streams exact bytes with private session credentials and safe headers", async () => {
  const { supervisor } = await fixture((req, res) => {
    expect(req.url).toBe(`/api/v1/projects/${projectId}/media/${mediaId}`);
    expect(req.headers.authorization).toBe("Bearer SECRET_TOKEN");
    expect(req.headers["x-project-session"]).toBe(sessionId);
    expect(req.headers["x-window-id"]).toBe("7");
    expect(req.headers.cookie).toBeUndefined();
    expect(req.headers.origin).toBeUndefined();
    expect(req.headers["x-request-id"]).toMatch(/^[a-f0-9-]{36}$/);
    res.setHeader("X-Backend-Path", "C:/PRIVATE");
    res.end("0123456789");
  });
  const response = await serveMedia(
    new Request(url, { headers: { Cookie: "private" } }),
    supervisor,
    () => session,
    7,
  );
  expect(response.status).toBe(200);
  expect(await response.text()).toBe("0123456789");
  expect(response.headers.get("content-length")).toBe("10");
  expect(response.headers.get("cache-control")).toBe("no-store");
  expect(response.headers.get("x-backend-path")).toBeNull();
  expect(JSON.stringify([...response.headers])).not.toMatch(
    /SECRET|PRIVATE|127\.0\.0\.1/,
  );
});

it.each([
  ["bytes=2-5", "bytes 2-5/10", "2345"],
  ["bytes=7-", "bytes 7-9/10", "789"],
  ["bytes=-3", "bytes 7-9/10", "789"],
  ["bytes=7-99", "bytes 7-9/10", "789"],
])("validates single range %s", async (range, contentRange, body) => {
  const { supervisor } = await fixture((req, res) => {
    expect(req.headers.range).toBe(range);
    res.statusCode = 206;
    res.setHeader("Content-Range", contentRange);
    res.setHeader("Content-Length", String(body.length));
    res.end(body);
  });
  const response = await serveMedia(
    new Request(url, { headers: { Range: range } }),
    supervisor,
    () => session,
    7,
  );
  expect(response.status).toBe(206);
  expect(response.headers.get("content-range")).toBe(contentRange);
  expect(await response.text()).toBe(body);
});

it("serves HEAD metadata without consuming a media body", async () => {
  const { supervisor } = await fixture((req, res) => {
    expect(req.method).toBe("HEAD");
    res.end();
  });
  const response = await serveMedia(
    new Request(url, { method: "HEAD" }),
    supervisor,
    () => session,
    7,
  );
  expect(response.status).toBe(200);
  expect(response.headers.get("content-length")).toBe("10");
  expect(response.body).toBeNull();
});

it("validates an unsatisfiable 416 without forwarding backend text", async () => {
  const { supervisor } = await fixture((_req, res) => {
    res.statusCode = 416;
    res.removeHeader("Content-Type");
    res.setHeader("Content-Length", "0");
    res.setHeader("Content-Range", "bytes */10");
    res.end();
  });
  const response = await serveMedia(
    new Request(url, { headers: { Range: "bytes=10-" } }),
    supervisor,
    () => session,
    7,
  );
  expect(response.status).toBe(416);
  expect(response.headers.get("content-range")).toBe("bytes */10");
  expect(await response.text()).toBe("");
});

it.each([
  `${url}?x=1`,
  `${url}#fragment`,
  `${url}/`,
  url.replace("local/", "evil/"),
  url.replace("local/", "local:80/"),
  url.replace(mediaId, "%32" + mediaId.slice(1)),
  url.replace(mediaId, "../../secret"),
  url.replace(mediaId, "not-a-uuid"),
])("rejects invalid media URL %s before connecting", async (input) => {
  let calls = 0;
  const { supervisor } = await fixture((_req, res) => {
    calls++;
    res.end("0123456789");
  });
  expect(
    (await serveMedia(new Request(input), supervisor, () => session, 7)).status,
  ).toBe(400);
  expect(calls).toBe(0);
});

it("rejects wrong projects, methods, and malformed ranges before connecting", async () => {
  let calls = 0;
  const { supervisor } = await fixture((_req, res) => {
    calls++;
    res.end("0123456789");
  });
  expect(
    (await serveMedia(new Request(url), supervisor, () => null, 7)).status,
  ).toBe(403);
  expect(
    (
      await serveMedia(
        new Request(url),
        supervisor,
        () => ({ ...session, projectId: mediaId }),
        7,
      )
    ).status,
  ).toBe(403);
  expect(
    (
      await serveMedia(
        new Request(url, { method: "POST" }),
        supervisor,
        () => session,
        7,
      )
    ).status,
  ).toBe(405);
  for (const range of [
    "bytes=0-1,3-4",
    "bytes=-",
    "bytes=3-1",
    "bytes=-0",
    "bytes=999999999999999-",
    "items=0-1",
  ]) {
    expect(
      (
        await serveMedia(
          new Request(url, { headers: { Range: range } }),
          supervisor,
          () => session,
          7,
        )
      ).status,
    ).toBe(400);
  }
  expect(calls).toBe(0);
});

it.each([
  "mime",
  "length",
  "oversize",
  "duplicate",
  "cache",
  "nosniff",
  "request-id",
  "encoding",
  "redirect",
  "range",
  "missing-range",
  "unexpected-range",
])("rejects invalid backend %s", async (kind) => {
  const { supervisor } = await fixture((_req, res) => {
    if (kind === "mime") res.setHeader("Content-Type", "text/html");
    if (kind === "length") res.removeHeader("Content-Length");
    if (kind === "oversize") res.setHeader("Content-Length", "2147483649");
    if (kind === "duplicate")
      res.setHeader("Content-Type", ["video/mp4", "video/mp4"]);
    if (kind === "cache") res.setHeader("Cache-Control", "public");
    if (kind === "nosniff") res.removeHeader("X-Content-Type-Options");
    if (kind === "request-id") res.setHeader("X-Request-Id", projectId);
    if (kind === "encoding") res.setHeader("Content-Encoding", "gzip");
    if (kind === "redirect") {
      res.statusCode = 302;
      res.setHeader("Location", "http://SECRET/PRIVATE");
    }
    if (kind === "range") {
      res.statusCode = 206;
      res.setHeader("Content-Range", "bytes 0-9/10");
    }
    if (kind === "missing-range") res.statusCode = 206;
    if (kind === "unexpected-range")
      res.setHeader("Content-Range", "bytes 0-9/10");
    res.end("0123456789");
  });
  const response = await serveMedia(
    new Request(url),
    supervisor,
    () => session,
    7,
  );
  expect(response.status).toBe(502);
  expect(await response.text()).toBe("");
  expect(response.headers.get("location")).toBeNull();
});

it("sanitizes backend API errors without reading their body", async () => {
  const { supervisor } = await fixture((_req, res) => {
    res.statusCode = 404;
    res.end("SECRETpath");
  });
  const response = await serveMedia(
    new Request(url),
    supervisor,
    () => session,
    7,
  );
  expect(response.status).toBe(404);
  expect(await response.text()).toBe("");
});

it.each(["body", "request", "runtime", "session"])(
  "closes backend stream on %s cancellation",
  async (kind) => {
    let close!: () => void;
    const closed = new Promise<void>((resolve) => {
      close = resolve;
    });
    let backend!: ServerResponse;
    const { supervisor, runtime } = await fixture((_req, res) => {
      backend = res;
      res.on("close", close);
      res.write("01");
    });
    let current: ProjectSession | null = session;
    const abort = new AbortController();
    const response = await serveMedia(
      new Request(url, { signal: abort.signal }),
      supervisor,
      () => current,
      7,
    );
    const reader = response.body!.getReader();
    expect(new TextDecoder().decode((await reader.read()).value)).toBe("01");
    if (kind === "body") await reader.cancel();
    else {
      if (kind === "request") abort.abort();
      if (kind === "runtime") runtime.abort();
      if (kind === "session") {
        current = { ...session, projectSessionId: mediaId };
        backend.write("23");
      }
      await expect(reader.read()).rejects.toThrow("Media unavailable");
    }
    await closed;
  },
);

it("rejects a stale session before backend headers", async () => {
  let current: ProjectSession | null = session;
  const { supervisor } = await fixture((_req, res) => {
    current = null;
    res.end("0123456789");
  });
  expect(
    (await serveMedia(new Request(url), supervisor, () => current, 7)).status,
  ).toBe(403);
});

it("errors the response stream when the backend truncates declared bytes", async () => {
  const { supervisor } = await fixture((_req, res) => {
    res.write("01");
    setTimeout(() => res.destroy(), 10);
  });
  const response = await serveMedia(
    new Request(url),
    supervisor,
    () => session,
    7,
  );
  await expect(response.text()).rejects.toThrow("Media unavailable");
});

it("returns headers and first bytes before a large response finishes, with bounded chunks", async () => {
  let finish!: () => void;
  const { supervisor } = await fixture((_req, res) => {
    res.setHeader("Content-Length", "1048576");
    res.write(Buffer.alloc(65536, 7));
    finish = () => res.end(Buffer.alloc(1048576 - 65536, 8));
  });
  const response = await serveMedia(
    new Request(url),
    supervisor,
    () => session,
    7,
  );
  const reader = response.body!.getReader();
  const first = await reader.read();
  expect(first.value!.length).toBeGreaterThan(0);
  expect(first.value![0]).toBe(7);
  let bytes = first.value!.length;
  finish();
  for (;;) {
    const chunk = await reader.read();
    if (chunk.done) break;
    expect(chunk.value.byteLength).toBeLessThanOrEqual(65536);
    bytes += chunk.value.byteLength;
  }
  expect(bytes).toBe(1048576);
});

it.each([
  "ignored",
  "wrong-offset",
  "wrong-total",
  "wrong-length",
  "satisfiable-416",
])("rejects backend range inconsistency %s", async (kind) => {
  const { supervisor } = await fixture((_req, res) => {
    res.statusCode = 206;
    res.setHeader("Content-Range", "bytes 2-5/10");
    res.setHeader("Content-Length", "4");
    if (kind === "ignored") {
      res.statusCode = 200;
      res.removeHeader("Content-Range");
    }
    if (kind === "wrong-offset") res.setHeader("Content-Range", "bytes 0-3/10");
    if (kind === "wrong-total")
      res.setHeader("Content-Range", "bytes 2-5/2147483649");
    if (kind === "wrong-length") res.setHeader("Content-Length", "3");
    if (kind === "satisfiable-416") {
      res.statusCode = 416;
      res.setHeader("Content-Length", "0");
      res.setHeader("Content-Range", "bytes */10");
      res.end();
      return;
    }
    res.end("2345");
  });
  const response = await serveMedia(
    new Request(url, { headers: { Range: "bytes=2-5" } }),
    supervisor,
    () => session,
    7,
  );
  expect(response.status).toBe(502);
  expect(await response.text()).toBe("");
});

it("cancels before headers without waiting for the backend", async () => {
  let ready!: () => void;
  const started = new Promise<void>((resolve) => {
    ready = resolve;
  });
  let closed!: () => void;
  const disconnected = new Promise<void>((resolve) => {
    closed = resolve;
  });
  const { supervisor } = await fixture((_req, res) => {
    res.on("close", closed);
    ready();
  });
  const abort = new AbortController();
  const pending = serveMedia(
    new Request(url, { signal: abort.signal }),
    supervisor,
    () => session,
    7,
  );
  await started;
  abort.abort();
  expect((await pending).status).toBe(503);
  await disconnected;
});

it.each(["headers", "body"])(
  "closes a backend stalled at %s after the idle deadline",
  async (phase) => {
    let ready!: () => void;
    const started = new Promise<void>((resolve) => {
      ready = resolve;
    });
    const { supervisor } = await fixture((_req, res) => {
      if (phase === "body") res.write("01");
      ready();
    });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const pending = serveMedia(new Request(url), supervisor, () => session, 7);
    await started;
    if (phase === "headers") {
      await vi.advanceTimersByTimeAsync(15001);
      expect((await pending).status).toBe(504);
    } else {
      const response = await pending;
      const rejected = expect(response.text()).rejects.toThrow(
        "Media unavailable",
      );
      await vi.advanceTimersByTimeAsync(15001);
      await rejected;
    }
  },
);
