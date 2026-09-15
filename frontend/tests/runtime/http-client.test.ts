import { createServer, type ServerResponse } from "node:http";
import { afterEach, expect, it } from "vitest";
import {
  runtimeHttp,
  capabilityIds,
  type Endpoint,
} from "../../electron/main/runtime/http-client";

const servers: ReturnType<typeof createServer>[] = [];
afterEach(async () => {
  for (const s of servers.splice(0)) {
    s.closeAllConnections();
    await new Promise<void>((resolve) => s.close(() => resolve()));
  }
});
const base = {
  token: "SECRET_SENTINEL",
  runtimeId: "11111111-1111-4111-8111-111111111111",
  generation: 1,
  backendVersion: "0.1.0",
};
async function serve(
  handler: (res: ServerResponse, requestId: string, path: string) => void,
): Promise<Endpoint> {
  const server = createServer((req, res) => {
    expect(req.headers.authorization).toBe("Bearer SECRET_SENTINEL");
    expect(req.headers.origin).toBeUndefined();
    expect(req.headers.cookie).toBeUndefined();
    const id = req.headers["x-request-id"] as string;
    res.setHeader("X-Request-Id", id);
    res.setHeader("Content-Type", "application/json");
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-Content-Type-Options", "nosniff");
    handler(res, id, req.url!);
  });
  servers.push(server);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  return { ...base, port: (server.address() as { port: number }).port };
}
function data() {
  return {
    status: "ready",
    runtimeId: base.runtimeId,
    generation: 1,
    apiVersion: 1,
    controlVersion: 1,
    backendVersion: "0.1.0",
    uptimeMs: 0,
  };
}
it("validates real TCP health and fixed capabilities", async () => {
  const e = await serve((res, requestId, path) =>
    res.end(
      JSON.stringify({
        requestId,
        data: path.endsWith("health")
          ? data()
          : {
              runtimeId: base.runtimeId,
              generation: 1,
              capabilities: capabilityIds.map((id, i) => ({
                id,
                enabled: i === 0,
                reasonCode: i === 0 ? "AVAILABLE" : "NOT_IMPLEMENTED",
              })),
            },
      }),
    ),
  );
  expect(
    (await runtimeHttp.health(e, new AbortController().signal)).status,
  ).toBe("ready");
  expect(
    (await runtimeHttp.capabilities(e, new AbortController().signal))
      .capabilities,
  ).toHaveLength(12);
});
it.each([
  "duplicate",
  "oversize",
  "identity",
  "headers",
  "redirect",
  "invalid-utf8",
  "unknown-field",
])("rejects %s without reflecting content", async (kind) => {
  const e = await serve((res, requestId) => {
    if (kind === "headers") res.setHeader("Cache-Control", "public");
    if (kind === "redirect") {
      res.statusCode = 302;
      res.setHeader("Location", "https://example.com");
    }
    const value = { requestId, data: data() };
    if (kind === "identity") value.data.generation = 2;
    if (kind === "unknown-field")
      Object.assign(value.data, { secret: "SECRET_SENTINEL" });
    if (kind === "duplicate")
      res.end(
        JSON.stringify(value).replace(
          '"generation":1',
          '"generation":1,"generation":1',
        ),
      );
    else if (kind === "oversize") res.end("SECRET_SENTINEL".repeat(6000));
    else if (kind === "invalid-utf8") res.end(Buffer.from([255]));
    else res.end(JSON.stringify(value));
  });
  await expect(
    runtimeHttp.health(e, new AbortController().signal),
  ).rejects.toMatchObject({ code: "PROTOCOL_INVALID" });
});
it("classifies incompatible HTTP versions", async () => {
  const e = await serve((res, requestId) =>
    res.end(JSON.stringify({ requestId, data: { ...data(), apiVersion: 2 } })),
  );
  await expect(
    runtimeHttp.health(e, new AbortController().signal),
  ).rejects.toMatchObject({ code: "VERSION_MISMATCH" });
});
it("bounds total read time even when server stalls", async () => {
  const e = await serve(() => {});
  await expect(
    runtimeHttp.health(e, new AbortController().signal),
  ).rejects.toMatchObject({ code: "BACKEND_UNAVAILABLE" });
});
