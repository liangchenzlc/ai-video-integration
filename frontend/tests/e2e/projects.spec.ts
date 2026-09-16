import {
  _electron as electron,
  test,
  expect,
  type ElectronApplication,
} from "@playwright/test";
import { mkdir, readFile, rename } from "node:fs/promises";
import { resolve } from "node:path";
import { randomUUID } from "node:crypto";

test("create a real project, preserve it on close, move and reopen without renderer paths", async () => {
  const workspace = resolve("../.cache/t02-desktop", randomUUID());
  const directory = resolve(workspace, "新建 中文项目");
  const moved = resolve(workspace, "移动 后的项目");
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
  let app: ElectronApplication | undefined;
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
  try {
    app = await launch();
    expect(await app.evaluate(({ app }) => app.getPath("userData"))).toBe(
      resolve(workspace, "appdata"),
    );
    const page = await app.firstWindow();
    const rendererErrors: string[] = [];
    page.on("pageerror", (error) => {
      rendererErrors.push(error.message);
    });
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
    await page.getByLabel("项目名称").fill("完整保存的故事");
    await page.getByRole("button", { name: "选择空目录" }).click();
    await expect(
      page.getByText("新建 中文项目", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "创建项目", exact: true }).click();
    await expect(page.getByRole("region", { name: "当前项目" })).toContainText(
      "完整保存的故事",
    );
    const current = await page.evaluate(() =>
      window.desktop.projects.current(),
    );
    expect(current.ok).toBe(true);
    expect(JSON.stringify(current)).not.toContain(workspace);
    const invalid = await page.evaluate(() =>
      window.desktop.projects.open({
        directoryGrantId: "C:\\arbitrary",
        requestedMode: "write",
      } as never),
    );
    expect(invalid.ok).toBe(false);
    await page
      .getByLabel("故事原文", { exact: true })
      .fill("第一行：雨夜\n第二行：未写完的故事");
    await expect(page.getByTestId("draft-save-status")).toContainText("已保存");
    expect(rendererErrors).toEqual([]);
    await page
      .getByLabel("故事原文", { exact: true })
      .fill("关闭前最后一次输入\n尾行");
    await page.getByRole("button", { name: "关闭项目", exact: true }).click();
    await expect(page.getByRole("region", { name: "当前项目" })).toHaveCount(0);
    await app.close();
    app = undefined;
    const db = await readFile(resolve(directory, "project.sqlite3"));
    expect(db.subarray(0, 15).toString()).toBe("SQLite format 3");
    await rename(directory, moved);
    app = await launch();
    const reopened = await app.firstWindow();
    await expect(reopened.getByTestId("runtime-status")).toHaveText(
      "本地服务已连接",
    );
    await app.evaluate(({ dialog }, folder) => {
      dialog.showOpenDialog = async () => ({
        canceled: false,
        filePaths: [folder],
      });
    }, moved);
    await reopened
      .getByRole("button", { name: "打开项目", exact: true })
      .click();
    await expect(
      reopened.getByRole("region", { name: "当前项目" }),
    ).toContainText("完整保存的故事");
    const after = await reopened.evaluate(() =>
      window.desktop.projects.current(),
    );
    expect(after.ok && after.data?.projectId).toBe(
      current.ok && current.data?.projectId,
    );
    await expect(reopened.getByLabel("故事原文", { exact: true })).toHaveValue(
      "关闭前最后一次输入\n尾行",
    );
    await reopened.getByLabel("故事原文", { exact: true }).fill("");
    // Native close happens before the debounce; the exit handshake must persist the clear.
    const closed = app.waitForEvent("close");
    await app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].close(),
    );
    await closed;
    app = await launch();
    const empty = await app.firstWindow();
    await expect(empty.getByTestId("runtime-status")).toHaveText(
      "本地服务已连接",
    );
    await empty
      .getByRole("button", { name: "完整保存的故事", exact: true })
      .click();
    await expect(empty.getByLabel("故事原文", { exact: true })).toHaveValue("");
    const session = await empty.evaluate(() =>
      window.desktop.projects.current(),
    );
    expect(session.ok && session.data?.project.revision).toBe(
      current.ok && current.data ? current.data.project.revision + 3 : -1,
    );
    await empty.screenshot({
      path: resolve(workspace, "project-home.png"),
      fullPage: true,
    });
  } finally {
    await app?.close();
  }
});
