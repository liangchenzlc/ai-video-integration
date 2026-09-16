import { expect, test, vi } from "vitest";
const mocks = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("electron", () => ({ ipcRenderer: { invoke: mocks.invoke } }));
import { tasksBridge } from "../../electron/preload/tasks";
test("task activity rejects local paths and remaps unsafe backend errors", async () => {
  mocks.invoke.mockResolvedValue({
    ok: true,
    data: [
      {
        projectId: "00000000-0000-4000-8000-000000000001",
        projectName: "safe",
        taskId: "00000000-0000-4000-8000-000000000002",
        state: "result_unknown",
        path: "private-sentinel",
      },
    ],
  });
  const result = await tasksBridge.activity({});
  expect(result.ok).toBe(false);
  expect(JSON.stringify(result)).not.toContain("private-sentinel");
  mocks.invoke.mockResolvedValue({
    ok: false,
    error: { code: "BUDGET_EXCEEDED", message: "private-sentinel" },
  });
  const failure = await tasksBridge.activity({});
  expect(failure).toMatchObject({
    ok: false,
    error: { code: "BUDGET_EXCEEDED" },
  });
  expect(JSON.stringify(failure)).not.toContain("private-sentinel");
});
