import {
  _electron as electron,
  test,
  expect,
  type ElectronApplication,
} from "@playwright/test";
import { mkdir, readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { randomUUID } from "node:crypto";

test("settings safely saves credentials, reopens storage, deletes and drops session-only secrets on restart", async () => {
  const workspace = resolve("../.cache/t03-desktop", randomUUID());
  await mkdir(resolve(workspace, "appdata"), { recursive: true });
  const env = Object.fromEntries(
    Object.entries(process.env).filter(
      (entry): entry is [string, string] => entry[1] !== undefined,
    ),
  );
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.ELECTRON_RENDERER_URL;
  env.APPDATA = resolve(workspace, "appdata");
  const launch = () =>
    electron.launch({
      executablePath:
        process.env.T01_DESKTOP_EXE ||
        resolve("node_modules/electron/dist/electron.exe"),
      args: [
        ...(process.env.T01_DESKTOP_EXE ? [] : [resolve(".")]),
        `--user-data-dir=${resolve(workspace, "appdata")}`,
      ],
      env,
    });
  let app: ElectronApplication | undefined;
  try {
    app = await launch();
    let page = await app.firstWindow();
    await expect(page.getByTestId("runtime-status")).toHaveText(
      "本地服务已连接",
    );
    await page.getByRole("button", { name: "设置", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "制作准备情况" }),
    ).toBeVisible();
    for (const name of [
      "文字 / 图像",
      "声音",
      "视频 / 口型",
      "音乐 / 音效",
      "媒体工具",
    ])
      await expect(
        page.getByRole("heading", { name, exact: true }),
      ).toBeVisible();
    const sentinel = "t03-private-sentinel-7294";
    await page.getByLabel("服务商标识").fill("desktop-api");
    await page.getByLabel("API Key", { exact: true }).fill(sentinel);
    await page.getByRole("button", { name: "保存凭据", exact: true }).click();
    await expect(page.getByLabel("API Key", { exact: true })).toHaveValue("");
    await expect(page.locator(".settings-saved").first()).toContainText(
      "desktop-api",
    );
    await expect(page.locator(".settings-saved").first()).toContainText("7294");
    expect(
      await page.evaluate(() => JSON.stringify(localStorage)),
    ).not.toContain(sentinel);
    expect(
      JSON.stringify(
        await page.evaluate(() => window.desktop.settings.details()),
      ),
    ).not.toContain(sentinel);
    await page.getByLabel("服务商标识").fill("desktop-oss");
    await page.getByLabel("凭据类型").selectOption("oss");
    await page
      .getByLabel("Access Key ID", { exact: true })
      .fill("oss-access-1234");
    await page
      .getByLabel("Access Key Secret", { exact: true })
      .fill("oss-secret-sentinel-9876");
    await page.getByRole("button", { name: "保存凭据", exact: true }).click();
    await expect(page.getByLabel("Access Key ID", { exact: true })).toHaveValue(
      "",
    );
    await expect(
      page.getByLabel("Access Key Secret", { exact: true }),
    ).toHaveValue("");
    await expect(page.locator(".settings-saved").first()).toContainText(
      "desktop-oss",
    );
    await page
      .getByLabel("OSS 凭据", { exact: true })
      .selectOption({ label: "desktop-oss · 尾号 9876" });
    await page.getByLabel("Region", { exact: true }).fill("cn-hangzhou");
    await page.getByLabel("Bucket", { exact: true }).fill("desktop-voice");
    await expect(page.getByLabel("保留期（小时）")).toHaveValue("48");
    await page.getByRole("button", { name: "保存存储配置" }).click();
    await expect(
      page.getByRole("button", { name: "修改存储配置" }),
    ).toBeVisible();
    await page.getByLabel("服务商标识").fill("desktop-session");
    await page.getByLabel("凭据类型").selectOption("api_key");
    await page.getByLabel("凭据保存方式").selectOption("session_only");
    await page
      .getByLabel("API Key", { exact: true })
      .fill("session-sentinel-3456");
    await page.getByRole("button", { name: "保存凭据", exact: true }).click();
    await expect(page.locator(".settings-saved").first()).toContainText(
      "desktop-session",
    );
    // Electron's compositor can stall on tall full-page capture; capture the
    // real desktop viewport at each settings section without resizing it.
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: resolve(workspace, "settings-desktop.png") });
    await page
      .getByRole("heading", { name: "服务凭据", exact: true })
      .scrollIntoViewIfNeeded();
    await page.screenshot({
      path: resolve(workspace, "settings-credentials.png"),
    });
    await page
      .getByRole("heading", { name: "生产音频存储", exact: true })
      .scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(workspace, "settings-storage.png") });
    await app.close();
    app = undefined;
    app = await launch();
    page = await app.firstWindow();
    await expect(page.getByTestId("runtime-status")).toHaveText(
      "本地服务已连接",
    );
    await page.getByRole("button", { name: "设置", exact: true }).click();
    await expect(page.locator(".settings-saved").first()).toContainText(
      "desktop-api",
    );
    await expect(page.locator(".settings-saved").first()).not.toContainText(
      "desktop-session",
    );
    await page.getByRole("button", { name: "修改存储配置" }).click();
    await expect(page.getByLabel("Region", { exact: true })).toHaveValue(
      "cn-hangzhou",
    );
    await expect(page.getByLabel("Bucket", { exact: true })).toHaveValue(
      "desktop-voice",
    );
    const apiRow = page
      .locator(".settings-saved li")
      .filter({ hasText: "desktop-api" });
    await apiRow.getByRole("button", { name: "删除凭据", exact: true }).click();
    await expect(apiRow).toBeVisible();
    await page
      .getByRole("button", { name: "确认删除凭据", exact: true })
      .click();
    await expect(apiRow).toHaveCount(0);
    await page
      .getByRole("button", { name: "继续本地准备", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "新建项目", exact: true }),
    ).toBeVisible();
    // Disk evidence is checked in the backend suite; renderer never receives a file path.
    expect(
      (await readFile(resolve(workspace, "settings-desktop.png"))).length,
    ).toBeGreaterThan(1000);
  } finally {
    await app?.close();
  }
});

test("an unknown credential save clears secrets and queries the original operation after navigation", async () => {
  const workspace = resolve("../.cache/t03-desktop", randomUUID());
  await mkdir(resolve(workspace, "appdata"), { recursive: true });
  const env = Object.fromEntries(
    Object.entries(process.env).filter(
      (entry): entry is [string, string] => entry[1] !== undefined,
    ),
  );
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.ELECTRON_RENDERER_URL;
  env.APPDATA = resolve(workspace, "appdata");
  const app = await electron.launch({
    executablePath:
      process.env.T01_DESKTOP_EXE ||
      resolve("node_modules/electron/dist/electron.exe"),
    args: [
      ...(process.env.T01_DESKTOP_EXE ? [] : [resolve(".")]),
      `--user-data-dir=${resolve(workspace, "appdata")}`,
    ],
    env,
  });
  try {
    const page = await app.firstWindow();
    await expect(page.getByTestId("runtime-status")).toHaveText(
      "本地服务已连接",
    );
    await app.evaluate(({ ipcMain }) => {
      const state = globalThis as typeof globalThis & {
        settingsTest?: { writes: number; operationId: string };
      };
      state.settingsTest = { writes: 0, operationId: "" };
      ipcMain.removeHandler("settings:set-credential");
      ipcMain.handle(
        "settings:set-credential",
        async (_event, input: { command: { clientOperationId: string } }) => {
          state.settingsTest!.writes += 1;
          state.settingsTest!.operationId = input.command.clientOperationId;
          await new Promise((resolve) => setTimeout(resolve, 500));
          return {
            ok: false,
            error: {
              code: "BACKEND_UNAVAILABLE",
              message: "secret-sentinel-must-not-echo",
            },
          };
        },
      );
      ipcMain.removeHandler("projects:operation");
      ipcMain.handle(
        "projects:operation",
        (_event, input: { operationId: string }) => {
          if (input.operationId !== state.settingsTest!.operationId)
            throw new Error("Wrong operation");
          return {
            ok: true,
            data: {
              operationId: input.operationId,
              state: "committed",
              receipt: {
                operationId: input.operationId,
                committedRevision: 1,
                resourceId: input.operationId,
                state: "committed",
              },
            },
          };
        },
      );
    });
    await page.getByRole("button", { name: "设置", exact: true }).click();
    await page.getByLabel("服务商标识").fill("unknown-save");
    await page
      .getByLabel("API Key", { exact: true })
      .fill("secret-sentinel-must-not-echo");
    await page.getByRole("button", { name: "保存凭据", exact: true }).click();
    await expect(page.getByLabel("API Key", { exact: true })).toHaveValue("");
    await expect(
      page.getByRole("button", { name: "查询原操作" }),
    ).toBeEnabled();
    await expect(
      page.getByRole("button", { name: "保存凭据", exact: true }),
    ).toBeDisabled();
    const pendingId = await page
      .locator(".settings-pending code")
      .textContent();
    expect(await page.locator("body").textContent()).not.toContain(
      "secret-sentinel-must-not-echo",
    );
    await page.getByRole("button", { name: "首页", exact: true }).click();
    await page.getByRole("button", { name: "设置", exact: true }).click();
    await expect(page.locator(".settings-pending code")).toHaveText(pendingId!);
    await page.getByRole("button", { name: "查询原操作" }).click();
    await expect(
      page.getByRole("region", { name: "待确认设置操作" }),
    ).toHaveCount(0);
    expect(
      await app.evaluate(
        () =>
          (
            globalThis as typeof globalThis & {
              settingsTest: { writes: number };
            }
          ).settingsTest.writes,
      ),
    ).toBe(1);
  } finally {
    await app.close();
  }
});
