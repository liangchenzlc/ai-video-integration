import {
  _electron as electron,
  test,
  expect,
  type ElectronApplication,
} from "@playwright/test";
import { mkdir, rename } from "node:fs/promises";
import { resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";

test("native media tools, import, protected draft, preview, move and reopen", async () => {
  test.setTimeout(90000);
  const workspace = resolve("../.cache/t02-media-desktop", randomUUID());
  const directory = resolve(workspace, "原始项目");
  const moved = resolve(workspace, "移动后的项目");
  const userData = resolve(workspace, "appdata");
  const ffmpeg = resolve(
    "../.local/research-20260915/ffmpeg/ffmpeg-9.0.1-essentials_build/bin/ffmpeg.exe",
  );
  const source = resolve(workspace, "参考图片.png");
  await mkdir(directory, { recursive: true });
  await mkdir(userData, { recursive: true });
  execFileSync(
    ffmpeg,
    [
      "-v",
      "error",
      "-f",
      "lavfi",
      "-i",
      "color=c=blue:s=64x48",
      "-frames:v",
      "1",
      source,
    ],
    { timeout: 20000, windowsHide: true },
  );
  const env = Object.fromEntries(
    Object.entries(process.env).filter(
      (entry): entry is [string, string] => entry[1] !== undefined,
    ),
  );
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.ELECTRON_RENDERER_URL;
  env.APPDATA = userData;
  let app: ElectronApplication | undefined;
  const launch = () =>
    electron.launch({
      executablePath: resolve("node_modules/electron/dist/electron.exe"),
      args: [resolve("."), `--user-data-dir=${userData}`],
      env,
    });
  async function choose(path: string) {
    await app!.evaluate(({ dialog }, file) => {
      dialog.showOpenDialog = async () => ({
        canceled: false,
        filePaths: [file],
      });
    }, path);
  }
  try {
    app = await launch();
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(page.getByTestId("runtime-status")).toHaveText(
      "本地服务已连接",
    );
    await choose(directory);
    await page.getByRole("button", { name: "新建项目", exact: true }).click();
    await page.getByLabel("项目名称").fill("媒体闭环");
    await page.getByRole("button", { name: "选择空目录" }).click();
    await page.getByRole("button", { name: "创建项目", exact: true }).click();
    const library = page.getByRole("region", { name: "项目素材", exact: true });
    await expect(library).toContainText("尚未配置 FFmpeg");
    const draft = page.getByLabel("故事原文", { exact: true });
    await draft.fill("工具未配置也能保存。");
    await expect(page.getByTestId("draft-save-status")).toContainText("已保存");
    await choose(ffmpeg);
    await library
      .getByRole("button", { name: "选择 FFmpeg", exact: true })
      .click();
    await expect(library).toContainText("FFmpeg 已配置");
    // A held native dialog must lock editor and project transitions.
    await app.evaluate(({ dialog }) => {
      dialog.showOpenDialog = () =>
        new Promise((finish) => {
          Object.assign(globalThis, {
            finishMediaDialog: (file: string) =>
              finish({ canceled: false, filePaths: [file] }),
          });
        });
    });
    await library.getByRole("button", { name: "选择素材文件" }).click();
    await expect(draft).not.toBeEditable();
    await expect(
      page.getByRole("button", { name: "关闭项目", exact: true }),
    ).toBeDisabled();
    await expect
      .poll(() => app!.evaluate(() => "finishMediaDialog" in globalThis))
      .toBe(true);
    // Native leave must own a separate lock even when the held action refuses
    // to flush. Discard proceeds into stopping without a draft:resume message.
    const leaveRequestId = randomUUID();
    await app.evaluate(({ BrowserWindow, ipcMain }, requestId) => {
      ipcMain.once("draft:flush-result", (_event, result: unknown) => {
        Object.assign(globalThis, { mediaLeaveResult: result });
      });
      BrowserWindow.getAllWindows()[0].webContents.send("draft:flush-request", {
        requestId,
      });
    }, leaveRequestId);
    await expect
      .poll(() =>
        app!.evaluate(
          () =>
            (globalThis as unknown as { mediaLeaveResult?: unknown })
              .mediaLeaveResult,
        ),
      )
      .toEqual({ requestId: leaveRequestId, saved: false });
    await app.evaluate(
      (_electron, file) =>
        (
          globalThis as unknown as { finishMediaDialog(file: string): void }
        ).finishMediaDialog(file),
      source,
    );
    await expect(library).toContainText("参考图片.png");
    // The chooser has settled and released busy, but discard/stopping must keep
    // the editor locked until explicit cancel/resume, not until action.finally.
    // This existing control reflects action-busy only, proving finally ran.
    await expect(
      page.getByRole("button", { name: "关闭项目", exact: true }),
    ).toBeEnabled();
    await expect(draft).not.toBeEditable();
    await expect(
      library.getByRole("button", { name: "导入素材", exact: true }),
    ).toBeDisabled();
    await app.evaluate(({ BrowserWindow }, requestId) => {
      BrowserWindow.getAllWindows()[0].webContents.send("draft:resume", {
        requestId,
      });
    }, leaveRequestId);
    await expect(draft).toBeEditable();
    await library.getByLabel("素材用途").selectOption("reference");
    // Drop the first request, then accept its exact retry but lose that reply.
    await app.evaluate(({ ipcMain }) => {
      const handlers = (
        ipcMain as unknown as {
          _invokeHandlers: Map<
            string,
            (...args: unknown[]) => Promise<unknown>
          >;
        }
      )._invokeHandlers;
      const originalImport = handlers.get("media:import")!;
      const originalQuery = handlers.get("drafts:operation")!;
      const captured = {
        imports: [] as string[],
        commands: [] as unknown[],
        queries: [] as string[],
      };
      Object.assign(globalThis, { mediaRecoveryCalls: captured });
      ipcMain.removeHandler("media:import");
      ipcMain.handle("media:import", async (...args: unknown[]) => {
        const input = args[1] as { command: { clientOperationId: string } };
        captured.imports.push(input.command.clientOperationId);
        captured.commands.push(input);
        if (captured.imports.length > 1) await originalImport(...args);
        return {
          ok: false,
          error: {
            code: "BACKEND_UNAVAILABLE",
            message: "Connection interrupted",
          },
        };
      });
      ipcMain.removeHandler("drafts:operation");
      ipcMain.handle("drafts:operation", async (...args: unknown[]) => {
        captured.queries.push((args[1] as { operationId: string }).operationId);
        if (captured.queries.length === 2)
          return {
            ok: false,
            error: {
              code: "BACKEND_UNAVAILABLE",
              message: "Connection interrupted",
            },
          };
        return originalQuery(...args);
      });
    });
    await library
      .getByRole("button", { name: "导入素材", exact: true })
      .click();
    await expect(
      library.getByRole("button", { name: "查询原媒体操作" }),
    ).toBeVisible();
    await expect(
      library.getByRole("button", { name: "重试原媒体操作" }),
    ).toBeEnabled();
    await expect(
      library.getByRole("button", { name: "导入素材", exact: true }),
    ).toBeDisabled();
    await expect(library).toContainText("参考图片.png");
    // Remounting the project keeps the uncertain receipt and does not resend.
    await page.getByRole("button", { name: "关闭项目", exact: true }).click();
    await page.getByRole("button", { name: "媒体闭环", exact: true }).click();
    await expect(
      library.getByRole("button", { name: "查询原媒体操作" }),
    ).toBeVisible();
    await library.getByRole("button", { name: "重试原媒体操作" }).click();
    await expect(
      library.getByRole("button", { name: "查询原媒体操作" }),
    ).toBeEnabled();
    await library.getByRole("button", { name: "查询原媒体操作" }).click();
    await expect(
      library.getByRole("button", { name: "查询原媒体操作" }),
    ).toHaveCount(0);
    const recovery = await app.evaluate(
      () =>
        (
          globalThis as unknown as {
            mediaRecoveryCalls: {
              imports: string[];
              commands: unknown[];
              queries: string[];
            };
          }
        ).mediaRecoveryCalls,
    );
    expect(recovery.imports).toHaveLength(2);
    expect(recovery.imports[1]).toBe(recovery.imports[0]);
    expect(recovery.commands[1]).toEqual(recovery.commands[0]);
    expect(recovery.queries).toEqual([
      recovery.imports[0],
      recovery.imports[0],
      recovery.imports[0],
    ]);
    await expect(library).toContainText("已完成");
    await expect(draft).toBeEditable();
    await library.getByRole("button", { name: "预览素材" }).click();
    const preview = library.getByRole("img");
    await expect(preview).toBeVisible();
    await expect
      .poll(() =>
        preview.evaluate(
          (element) => (element as HTMLImageElement).naturalWidth,
        ),
      )
      .toBe(64);
    expect(await preview.getAttribute("src")).toMatch(
      /^avi-media:\/\/local\/[0-9a-f-]+\/[0-9a-f-]+$/,
    );
    const data = await page.evaluate(async () => {
      const current = await window.desktop.projects.current();
      if (!current.ok || !current.data) throw new Error("No project");
      const id = current.data.projectId;
      return {
        current,
        settings: await window.desktop.projects.media.settings(),
        jobs: await window.desktop.projects.media.jobs({ projectId: id }),
        media: await window.desktop.projects.media.list({ projectId: id }),
      };
    });
    expect(JSON.stringify(data)).not.toContain(workspace);
    expect(JSON.stringify(data)).not.toContain(ffmpeg);
    expect(data.jobs.ok && data.jobs.data).toHaveLength(1);
    expect(data.media.ok && data.media.data.items).toHaveLength(1);
    expect(errors).toEqual([]);
    await page.screenshot({
      path: resolve(workspace, "media-desktop.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "关闭项目", exact: true }).click();
    await expect(library).toHaveCount(0);
    await app.close();
    app = undefined;
    await rename(directory, moved);
    app = await launch();
    const reopened = await app.firstWindow();
    await expect(reopened.getByTestId("runtime-status")).toHaveText(
      "本地服务已连接",
    );
    await choose(moved);
    await reopened
      .getByRole("button", { name: "打开项目", exact: true })
      .click();
    await expect(reopened.getByLabel("故事原文", { exact: true })).toHaveValue(
      "工具未配置也能保存。",
    );
    const restored = reopened.getByRole("region", {
      name: "项目素材",
      exact: true,
    });
    await expect(restored).toContainText("已完成");
    await restored.getByRole("button", { name: "预览素材" }).click();
    await expect
      .poll(() =>
        restored
          .getByRole("img")
          .evaluate((element) => (element as HTMLImageElement).naturalWidth),
      )
      .toBe(64);
  } finally {
    await app?.close();
  }
});
