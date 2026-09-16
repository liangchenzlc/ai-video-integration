import { createServer } from "node:http";
import { randomUUID } from "node:crypto";
import { afterEach, expect, test } from "vitest";
import { z } from "zod";
import { businessRequest } from "../../electron/main/projects/client";
import { taskRoutes } from "../../electron/shared/tasks";
import { versionRoutes } from "../../electron/shared/versions";
import { storyboardRoutes } from "../../electron/shared/storyboard";

const servers: ReturnType<typeof createServer>[] = [];
afterEach(async () => {
  await Promise.all(
    servers.splice(0).map((s) => new Promise<void>((r) => s.close(() => r()))),
  );
});

test("project request preserves the operation ID and verifies the response envelope", async () => {
  const operationId = randomUUID();
  let received = "";
  const server = createServer((req, res) => {
    expect(req.headers["x-window-id"]).toBe("8");
    expect(req.headers.authorization).toBe("Bearer TEST_SECRET");
    req.on("data", (chunk) => {
      received += String(chunk);
    });
    req.on("end", () => {
      res.writeHead(201, {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "X-Request-Id": req.headers["x-request-id"],
      });
      res.end(
        JSON.stringify({
          requestId: req.headers["x-request-id"],
          data: { id: operationId },
        }),
      );
    });
  });
  servers.push(server);
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("No test port");
  const endpoint = {
    port: address.port,
    token: "TEST_SECRET",
    runtimeId: randomUUID(),
    generation: 1,
    backendVersion: "0.1.0",
  };
  const result = await businessRequest(endpoint, new AbortController().signal, {
    method: "POST",
    path: "/api/v1/projects",
    windowId: 8,
    body: { clientOperationId: operationId },
    schema: z.strictObject({ id: z.string().uuid() }),
  });
  expect(result.id).toBe(operationId);
  expect(JSON.parse(received).clientOperationId).toBe(operationId);
});

test("business client rejects non-project paths before making a request", async () => {
  await expect(
    businessRequest(
      {
        port: 1,
        token: "TEST_SECRET",
        runtimeId: randomUUID(),
        generation: 1,
        backendVersion: "0.1.0",
      },
      new AbortController().signal,
      {
        method: "GET",
        path: "https://example.com",
        windowId: 1,
        schema: z.unknown(),
      },
    ),
  ).rejects.toMatchObject({ code: "REQUEST_INVALID" });
});

test("task transport admits every fixed route and rejects path injection without another request", async () => {
  const received: string[] = [];
  const server = createServer((req, res) => {
    received.push(`${req.method} ${req.url}`);
    res.writeHead(200, {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "X-Request-Id": req.headers["x-request-id"],
    });
    res.end(
      JSON.stringify({
        requestId: req.headers["x-request-id"],
        data: { accepted: true },
      }),
    );
  });
  servers.push(server);
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("No test port");
  const endpoint = {
    port: address.port,
    token: "TEST_SECRET",
    runtimeId: randomUUID(),
    generation: 1,
    backendVersion: "0.1.0",
  };
  const id = randomUUID();
  for (const route of Object.values(taskRoutes)) {
    const path = route.path({
      projectId: id,
      planId: id,
      taskId: id,
      callId: id,
      expenseId: id,
      cursor: id,
      limit: 50,
    });
    const result = await businessRequest(
      endpoint,
      new AbortController().signal,
      {
        method: route.method,
        path,
        windowId: 1,
        sessionId: id,
        schema: z.strictObject({ accepted: z.literal(true) }),
      },
    );
    expect(result.accepted).toBe(true);
  }
  expect(received).toHaveLength(16);
  for (const path of [
    `/api/v1/projects/${id}/tasks?url=https://example.com`,
    `/api/v1/projects/${id}/calls/../tasks`,
    `/api/v1/task-activity?projectId=${id}`,
    `/api/v1/projects/${id}/cost-entries?limit=50&cursor=../private`,
  ]) {
    await expect(
      businessRequest(endpoint, new AbortController().signal, {
        method: "GET",
        path,
        windowId: 1,
        schema: z.unknown(),
      }),
    ).rejects.toMatchObject({ code: "REQUEST_INVALID" });
  }
  expect(received).toHaveLength(16);
});

test("version transport admits only the fixed artifact, adoption and check routes", async () => {
  const received: string[] = [];
  const server = createServer((req, res) => {
    received.push(`${req.method} ${req.url}`);
    res.writeHead(200, {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "X-Request-Id": req.headers["x-request-id"],
    });
    res.end(
      JSON.stringify({
        requestId: req.headers["x-request-id"],
        data: { accepted: true },
      }),
    );
  });
  servers.push(server);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("No test port");
  const endpoint = {
    port: address.port,
    token: "TEST_SECRET",
    runtimeId: randomUUID(),
    generation: 1,
    backendVersion: "0.1.0",
  };
  const id = randomUUID();
  for (const route of [
    ...Object.values(versionRoutes),
    ...Object.values(storyboardRoutes),
  ]) {
    const buildPath = route.path as (value: Record<string, unknown>) => string;
    const result = await businessRequest(
      endpoint,
      new AbortController().signal,
      {
        method: route.method,
        path: buildPath({
          projectId: id,
          artifactId: id,
          adoptionId: id,
          checkId: id,
          shotId: id,
          phase: "image",
          cursor: id,
          limit: 50,
        }),
        windowId: 1,
        sessionId: id,
        body: route.method !== "GET" ? {} : undefined,
        schema: z.strictObject({ accepted: z.literal(true) }),
      },
    );
    expect(result.accepted).toBe(true);
  }
  expect(received).toHaveLength(14);
  for (const path of [
    `/api/v1/projects/${id}/artifacts/${id}/revisions?limit=50&cursor=../private`,
    `/api/v1/projects/${id}/artifacts/${id}/../check-reports/${id}`,
    `/api/v1/projects/${id}/check-reports/${id}?include=private`,
    `/api/v1/projects/${id}/adoptions/${id}/undo/extra`,
    `/api/v1/projects/${id}/storyboard/shots/${id}/prompt?phase=image&url=private`,
  ]) {
    await expect(
      businessRequest(endpoint, new AbortController().signal, {
        method: "GET",
        path,
        windowId: 1,
        sessionId: id,
        schema: z.unknown(),
      }),
    ).rejects.toMatchObject({ code: "REQUEST_INVALID" });
  }
  expect(received).toHaveLength(14);
});
