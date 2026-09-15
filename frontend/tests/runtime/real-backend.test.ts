import { resolve } from "node:path";
import { expect, it } from "vitest";
import { RuntimeSupervisor } from "../../electron/main/runtime/supervisor";
import { launchBackend } from "../../electron/main/runtime/launch";

it("Node supervisor connects, restarts and stops the actual Python backend", async () => {
  const root = resolve("..");
  const supervisor = new RuntimeSupervisor({
    launch: () => launchBackend(root, "", false),
    appDataDir: resolve(root, ".cache/桌面连接测试"),
    version: "0.1.0",
    mode: "development",
  });
  async function waitReady(generation: number) {
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        unsubscribe();
        reject(new Error("Ready deadline"));
      }, 12000);
      const unsubscribe = supervisor.subscribe((s) => {
        if (s.state === "ready" && s.generation === generation) {
          clearTimeout(timer);
          unsubscribe();
          resolve();
        }
        if (s.state === "failed") {
          clearTimeout(timer);
          unsubscribe();
          reject(new Error(s.errorCode!));
        }
      });
    });
  }
  try {
    await supervisor.start();
    await waitReady(1);
    expect((await supervisor.getCapabilities()).capabilities[0].enabled).toBe(
      true,
    );
    const before = supervisor.snapshot();
    await supervisor.restart(1);
    await waitReady(2);
    expect(supervisor.snapshot().runtimeId).not.toBe(before.runtimeId);
  } finally {
    await supervisor.stop("app_exit");
  }
  expect(supervisor.snapshot().state).toBe("stopped");
}, 30000);
