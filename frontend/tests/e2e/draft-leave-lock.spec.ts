import { _electron as electron, test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { randomUUID } from "node:crypto";

test("project transitions and native leave keep drafts locked until editing resumes", async () => {
  const workspace = resolve("../.cache/t02-leave-lock", randomUUID());
  const directory = resolve(workspace, "project");
  await mkdir(directory, { recursive: true });
  await mkdir(resolve(workspace, "appdata"), { recursive: true });
  const env = Object.fromEntries(
    Object.entries(process.env).filter(
      (x): x is [string, string] => x[1] !== undefined,
    ),
  );
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.ELECTRON_RENDERER_URL;
  env.APPDATA = resolve(workspace, "appdata");
  const app = await electron.launch({
    executablePath: resolve("node_modules/electron/dist/electron.exe"),
    args: [resolve("."), `--user-data-dir=${resolve(workspace, "appdata")}`],
    env,
  });
  try {
    const page = await app.firstWindow();
    await expect(page.getByTestId("runtime-status")).toHaveText(
      "本地服务已连接",
    );
    await app.evaluate(({ dialog }, folder) => {
      dialog.showOpenDialog = async () => ({
        canceled: false,
        filePaths: [folder],
      });
    }, directory);
    await page.getByRole("button", { name: "新建项目", exact: true }).click();
    await page.getByLabel("项目名称").fill("leave lock");
    await page.getByRole("button", { name: "选择空目录" }).click();
    await page.getByRole("button", { name: "创建项目", exact: true }).click();
    const source = page.getByLabel("故事原文", { exact: true });
    await source.fill("保存后仍应保留的原文");
    await app.evaluate(({ dialog }) => {
      dialog.showOpenDialog = () =>
        new Promise((resolve) => {
          Object.assign(globalThis, {
            finishDraftDirectoryDialog: () =>
              resolve({ canceled: true, filePaths: [] }),
          });
        });
    });
    await page.getByRole("button", { name: "打开项目", exact: true }).click();
    await expect(source).not.toBeEditable();
    await expect
      .poll(() =>
        app.evaluate(() => "finishDraftDirectoryDialog" in globalThis),
      )
      .toBe(true);
    await app.evaluate(() =>
      (
        globalThis as unknown as { finishDraftDirectoryDialog(): void }
      ).finishDraftDirectoryDialog(),
    );
    await expect(source).toBeEditable();

    const requestId = randomUUID();
    await app.evaluate(({ BrowserWindow }, id) => {
      BrowserWindow.getAllWindows()[0].webContents.send("draft:flush-request", {
        requestId: id,
      });
    }, requestId);
    await expect(source).not.toBeEditable();
    await expect(page.getByTestId("draft-save-status")).toContainText("已保存");
    await expect(source).not.toBeEditable();
    await app.evaluate(({ BrowserWindow }, id) => {
      BrowserWindow.getAllWindows()[0].webContents.send("draft:resume", {
        requestId: id,
      });
    }, requestId);
    await expect(source).toBeEditable();
    await expect(source).toHaveValue("保存后仍应保留的原文");

    await app.evaluate(({ dialog }) => {
      dialog.showMessageBox = async () => {
        Object.assign(globalThis, { draftExitCancelled: true });
        return { response: 0, checkboxChecked: false };
      };
    });
    await page.evaluate(() => {
      const unsubscribe = window.desktop.onBeforeLeave(async () => false);
      Object.assign(window, { unsubscribeDraftFailure: unsubscribe });
    });
    await app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].close(),
    );
    await expect
      .poll(() => app.evaluate(() => "draftExitCancelled" in globalThis))
      .toBe(true);
    await expect(source).toBeEditable();
    await page.evaluate(() =>
      (
        window as unknown as { unsubscribeDraftFailure(): void }
      ).unsubscribeDraftFailure(),
    );
    await expect(source).toHaveValue("保存后仍应保留的原文");
  } finally {
    await app.close();
  }
});
