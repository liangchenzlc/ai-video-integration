import {
  _electron as electron,
  expect,
  test,
  type ElectronApplication,
} from "@playwright/test";
import { resolve } from "node:path";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { mkdir, writeFile } from "node:fs/promises";
import type { DesktopBridge } from "../../electron/shared/runtime";

declare global {
  interface Window {
    desktop: DesktopBridge;
  }
}
const root = resolve("..");
const packageExe = process.env.T01_DESKTOP_EXE;
if (!packageExe)
  test("development origin supports React refresh and reload with the same backend", async () => {
    const { createServer } = await import("vite");
    const { default: react } = await import("@vitejs/plugin-react");
    const server = await createServer({
      configFile: false,
      root: resolve("."),
      plugins: [react()],
      server: { host: "127.0.0.1", port: 5173, strictPort: true },
    });
    let app: ElectronApplication | undefined;
    try {
      await server.listen();
      const env = Object.fromEntries(
        Object.entries(process.env).filter(
          (entry): entry is [string, string] => entry[1] !== undefined,
        ),
      );
      delete env.ELECTRON_RUN_AS_NODE;
      env.ELECTRON_RENDERER_URL = "http://127.0.0.1:5173";
      app = await electron.launch({
        executablePath: resolve("node_modules/electron/dist/electron.exe"),
        args: [resolve(".")],
        env,
      });
      const page = await app.firstWindow();
      await expect(page.getByTestId("runtime-status")).toHaveText(
        "本地服务已连接",
      );
      const first = await page.evaluate(() => window.desktop.getRuntimeState());
      await page.reload();
      await expect(page.getByTestId("runtime-status")).toHaveText(
        "本地服务已连接",
      );
      expect(
        await page.evaluate(() => window.desktop.getRuntimeState()),
      ).toEqual(first);
    } finally {
      await app?.close();
      await server.close();
    }
  });
async function launch() {
  const env = Object.fromEntries(
    Object.entries(process.env).filter(
      (entry): entry is [string, string] => entry[1] !== undefined,
    ),
  );
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.ELECTRON_RENDERER_URL;
  if (packageExe) env.PATH = `${env.SystemRoot}\\System32`;
  return electron.launch({
    executablePath:
      packageExe || resolve("node_modules/electron/dist/electron.exe"),
    args: packageExe ? [] : [resolve(".")],
    env,
    timeout: 15000,
  });
}
async function observe(app: ElectronApplication) {
  const mainPid = await app.evaluate(() => process.pid);
  const child = spawn(
    resolve(root, "backend/.venv/Scripts/python.exe"),
    [resolve(root, "scripts/desktop_process_observer.py"), String(mainPid)],
    { windowsHide: true, stdio: "pipe" },
  );
  const lines = createInterface({ input: child.stdout });
  let diagnostic = "";
  child.stderr.on("data", (chunk: Buffer) => {
    diagnostic += chunk.toString();
  });
  const iterator = lines[Symbol.asyncIterator]();
  const first = await iterator.next();
  expect(first.done, diagnostic).toBe(false);
  const identity = JSON.parse(first.value!) as {
    ids: { main: number; supervisor: number; api: number };
  };
  return {
    ids: identity.ids,
    async command(kill?: string) {
      child.stdin.write(JSON.stringify({ kill }) + "\n");
      const line = await iterator.next();
      return JSON.parse(line.value!) as {
        alive: { main: boolean; supervisor: boolean; api: boolean };
      };
    },
    close() {
      child.stdin.end();
      lines.close();
    },
  };
}
test("desktop navigation, real bridge, sandbox, restart and graceful close", async () => {
  const started = Date.now();
  const app = await launch();
  const page = await app.firstWindow();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let watcher: Awaited<ReturnType<typeof observe>> | undefined;
  try {
    await expect(page.getByTestId("runtime-status")).toHaveText(
      "本地服务已连接",
    );
    const readyMs = Date.now() - started;
    watcher = await observe(app);
    expect(
      await page.evaluate(() => ({
        require: typeof (window as unknown as { require?: unknown }).require,
        process: typeof (window as unknown as { process?: unknown }).process,
        keys: Object.keys(window.desktop).sort(),
        settingsKeys: Object.keys(window.desktop.settings).sort(),
        versionKeys: Object.keys(window.desktop.versions).sort(),
      })),
    ).toEqual({
      require: "undefined",
      process: "undefined",
      keys: [
        "getCapabilities",
        "getRuntimeState",
        "onRuntimeStateChanged",
        "onBeforeLeave",
        "openHelpLink",
        "projects",
        "restartBackend",
        "settings",
        "tasks",
        "versions",
      ].sort(),
      settingsKeys: [
        "get",
        "details",
        "setCredential",
        "deleteCredential",
        "configureStorage",
        "configureStage",
        "stageModels",
        "checkConnection",
        "job",
      ].sort(),
      versionKeys: [
        "artifact",
        "list",
        "create",
        "preview",
        "adopt",
        "confirm",
        "undo",
        "runChecks",
        "report",
      ].sort(),
    });
    const prefs = await app.evaluate(({ BrowserWindow }) => {
      const wc = BrowserWindow.getAllWindows()[0].webContents as unknown as {
        getLastWebPreferences(): {
          sandbox: boolean;
          contextIsolation: boolean;
          nodeIntegration: boolean;
        };
      };
      const p = wc.getLastWebPreferences();
      return {
        sandbox: p.sandbox,
        isolation: p.contextIsolation,
        node: p.nodeIntegration,
      };
    });
    expect(prefs).toEqual({ sandbox: true, isolation: true, node: false });
    const capabilities = await page.evaluate(() =>
      window.desktop.getCapabilities(),
    );
    expect(
      capabilities.ok &&
        capabilities.data.capabilities
          .filter((x) => x.enabled)
          .map((x) => x.id),
    ).toEqual(["runtime", "projects"]);
    const state = await page.evaluate(() => window.desktop.getRuntimeState());
    expect(state.ok).toBe(true);
    // A second executable focuses this window and exits without another backend.
    const secondEnv = { ...process.env };
    delete secondEnv.ELECTRON_RUN_AS_NODE;
    delete secondEnv.ELECTRON_RENDERER_URL;
    const second = spawn(
      packageExe || resolve("node_modules/electron/dist/electron.exe"),
      packageExe ? [] : [resolve(".")],
      { env: secondEnv, windowsHide: true, stdio: "ignore" },
    );
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        second.kill();
        reject(new Error("Second instance deadline"));
      }, 8000);
      second.once("error", () => {
        clearTimeout(timer);
        reject(new Error("Second instance failed"));
      });
      second.once("close", (code) => {
        clearTimeout(timer);
        if (code === 0) resolve();
        else reject(new Error("Second instance exit"));
      });
    });
    expect(app.windows()).toHaveLength(1);
    expect(await page.evaluate(() => window.desktop.getRuntimeState())).toEqual(
      state,
    );
    expect(JSON.stringify(state)).not.toMatch(
      /token|127\.0\.0\.1|Authorization|port/i,
    );
    const invalid = await page.evaluate(() =>
      window.desktop.restartBackend({ expectedGeneration: "1" } as never),
    );
    expect(invalid.ok).toBe(false);
    for (const name of [
      "故事",
      "视觉与分镜",
      "镜头制作",
      "声音与剪辑",
      "检查与导出",
    ]) {
      await page
        .getByRole("navigation")
        .getByRole("button", { name, exact: true })
        .click();
      await expect(
        page.getByRole("heading", { name: "这个工作区尚未开放" }),
      ).toBeVisible();
    }
    await page
      .getByRole("navigation")
      .getByRole("button", { name: "项目工具", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "本地项目", exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(() => Object.keys(window.desktop.projects).sort()),
    ).toEqual(
      [
        "chooseDirectory",
        "close",
        "create",
        "current",
        "drafts",
        "media",
        "open",
        "openRecent",
        "operation",
        "recent",
      ].sort(),
    );
    await page.getByRole("button", { name: "设置", exact: true }).click();
    await expect(page.getByRole("heading", { name: "运行信息" })).toBeVisible();
    await page
      .getByRole("navigation")
      .getByRole("button", { name: "首页", exact: true })
      .click();
    await page.keyboard.press("Tab");
    expect(
      await page.evaluate(() => document.activeElement !== document.body),
    ).toBe(true);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    const remote = await page.evaluate(async () => {
      try {
        await fetch("https://example.com/");
        return true;
      } catch {
        return false;
      }
    });
    expect(remote).toBe(false);
    await page.evaluate(() => window.open("https://example.com/"));
    expect(app.windows()).toHaveLength(1);
    const generation = state.ok ? state.data.generation : 0;
    await page.evaluate(
      (g) =>
        Promise.all([
          window.desktop.restartBackend({ expectedGeneration: g }),
          window.desktop.restartBackend({ expectedGeneration: g }),
        ]),
      generation,
    );
    await expect
      .poll(async () => {
        const r = await page.evaluate(() => window.desktop.getRuntimeState());
        return r.ok ? [r.data.state, r.data.generation] : null;
      })
      .toEqual(["ready", generation + 1]);
    await expect
      .poll(async () => (await watcher!.command()).alive)
      .toMatchObject({ supervisor: false, api: false });
    watcher.close();
    watcher = await observe(app);
    await mkdir(resolve(root, ".cache/desktop-screenshots"), {
      recursive: true,
    });
    await page.screenshot({
      path: resolve(root, ".cache/desktop-screenshots/home.png"),
      fullPage: true,
    });
    await writeFile(
      resolve(root, ".cache/t01-desktop-metrics.json"),
      JSON.stringify(
        {
          packaged: Boolean(packageExe),
          readyMs,
          versions: await app.evaluate(() => ({
            electron: process.versions.electron,
            node: process.versions.node,
          })),
          memory: await app.evaluate(() => process.memoryUsage()),
          windows: 1,
          rendererErrors: errors,
        },
        null,
        2,
      ),
    );
    expect(errors).toEqual([]);
    // Electron cancels navigation before commit. Playwright's navigation tracker
    // remains pending; inspect the real WebContents and DOM after cancellation.
    await page.evaluate(() => {
      window.location.href = "https://example.com/";
    });
    expect(
      await app.evaluate(({ BrowserWindow }) =>
        BrowserWindow.getAllWindows()[0].webContents.getURL(),
      ),
    ).toBe("app://ui/");
    expect(
      await app.evaluate(({ BrowserWindow }) =>
        BrowserWindow.getAllWindows()[0].webContents.executeJavaScript(
          'document.querySelector("[data-testid=runtime-status]").textContent',
        ),
      ),
    ).toBe("本地服务已连接");
    await app.close();
    await expect
      .poll(async () => (await watcher!.command()).alive)
      .toEqual({ main: false, supervisor: false, api: false });
  } finally {
    watcher?.close();
    await app.close().catch(() => {});
  }
});
for (const role of ["api", "supervisor", "main"] as const)
  test(`${role} termination cleans owned backend; surviving desktop can recover`, async () => {
    const app = await launch();
    let watcher: Awaited<ReturnType<typeof observe>> | undefined;
    try {
      const page = await app.firstWindow();
      await expect(page.getByTestId("runtime-status")).toHaveText(
        "本地服务已连接",
      );
      watcher = await observe(app);
      await watcher.command(role);
      await expect
        .poll(async () => (await watcher!.command()).alive)
        .toMatchObject({ supervisor: false, api: false });
      if (role !== "main") {
        await expect(
          page.getByRole("button", { name: "重启本地服务" }),
        ).toBeEnabled();
        await page.getByRole("button", { name: "重启本地服务" }).click();
        await expect(page.getByTestId("runtime-status")).toHaveText(
          "本地服务已连接",
        );
      }
    } finally {
      watcher?.close();
      await app.close().catch(() => {});
    }
  });
