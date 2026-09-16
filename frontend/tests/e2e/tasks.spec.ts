import { _electron as electron, test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { randomUUID } from "node:crypto";

test("synthetic plan is previewed before one real persistent start; lost response queries its original operation", async () => {
  const workspace = resolve("../.cache/t04-desktop", randomUUID());
  const directory = resolve(workspace, "练习项目");
  await mkdir(directory, { recursive: true });
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
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
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
    await page.getByLabel("项目名称").fill("任务恢复练习");
    await page.getByRole("button", { name: "选择空目录" }).click();
    await page.getByRole("button", { name: "创建项目", exact: true }).click();
    await page
      .getByLabel("故事原文", { exact: true })
      .fill("雨夜，一位旅人替陌生人点亮了门灯。");
    await page
      .getByLabel("创作简报（可稍后补充）")
      .fill("温暖、克制，保持一个场景。");
    await expect(page.getByTestId("draft-save-status")).toContainText("已保存");
    await page.getByText("预算配置（元）", { exact: true }).click();
    await page.getByLabel("项目总预算（元）", { exact: true }).fill("10");
    await page.getByLabel("故事预算（元）", { exact: true }).fill("10");
    await page.getByRole("button", { name: "保存预算", exact: true }).click();
    await expect(page.getByRole("region", { name: "费用汇总" })).toContainText(
      "¥ 10",
    );
    await page
      .getByRole("button", { name: "生成本地计划", exact: true })
      .click();
    const preview = page.getByRole("region", { name: "冻结计划预览" });
    await expect(preview).toContainText("雨夜");
    await expect(preview).toContainText("本地练习，不向云端发送");
    await expect(
      page.getByRole("button", { name: "确认并启动任务", exact: true }),
    ).toBeDisabled();
    await preview.evaluate((element) =>
      element.scrollIntoView({ block: "start" }),
    );
    await page.screenshot({
      path: resolve(workspace, "tasks-plan.png"),
      fullPage: false,
    });
    const before = await page.evaluate(async () => {
      const current = await window.desktop.projects.current();
      if (!current.ok || !current.data) throw new Error("Missing project");
      return window.desktop.tasks.list({ projectId: current.data.projectId });
    });
    expect(before.ok && before.data.items).toEqual([]);
    // Drop the real HTTP response after start committed, leaving the backend intact.
    await app.evaluate(() => {
      const http = process.getBuiltinModule(
        "http",
      ) as typeof import("node:http");
      const original = http.request;
      let dropped = false;
      Object.assign(globalThis, { taskStartCount: 0 });
      http.request = ((
        options: import("node:http").RequestOptions,
        callback: (response: import("node:http").IncomingMessage) => void,
      ) => {
        const start =
          options.method === "POST" &&
          /^\/api\/v1\/projects\/[^/]+\/tasks$/.test(options.path ?? "");
        if (start)
          (globalThis as unknown as { taskStartCount: number })
            .taskStartCount++;
        const request = original(options, (response) => {
          if (start && !dropped && response.statusCode === 202) {
            dropped = true;
            response.resume();
            request.destroy(new Error("receipt intentionally lost"));
          } else callback(response);
        });
        return request;
      }) as typeof http.request;
    });
    await page
      .getByLabel("我已核对输入、外发内容与最高费用，并接受本次披露")
      .check();
    await page
      .getByRole("button", { name: "确认并启动任务", exact: true })
      .click();
    await expect(
      page.getByText("启动任务的响应尚待确认；若涉及生成，可能已计费。", {
        exact: true,
      }),
    ).toBeVisible();
    await page.getByRole("button", { name: "查询原操作", exact: true }).click();
    await expect(
      page.getByRole("region", { name: "原任务详情" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "查询原任务", exact: true }).click();
    await expect(
      page.getByRole("region", { name: "原任务详情" }),
    ).toContainText("已完成");
    await page
      .getByRole("region", { name: "原任务详情" })
      .evaluate((element) => element.scrollIntoView({ block: "start" }));
    await page.screenshot({
      path: resolve(workspace, "tasks-result.png"),
      fullPage: false,
    });
    await page
      .getByRole("region", { name: "费用汇总" })
      .evaluate((element) => element.scrollIntoView({ block: "start" }));
    await page.screenshot({
      path: resolve(workspace, "tasks-costs.png"),
      fullPage: false,
    });
    expect(
      await app.evaluate(
        () =>
          (globalThis as unknown as { taskStartCount: number }).taskStartCount,
      ),
    ).toBe(1);
    const after = await page.evaluate(async () => {
      const current = await window.desktop.projects.current();
      if (!current.ok || !current.data) throw new Error("Missing project");
      const tasks = await window.desktop.tasks.list({
        projectId: current.data.projectId,
      });
      if (!tasks.ok) throw new Error("Missing tasks");
      const task = await window.desktop.tasks.get({
        projectId: current.data.projectId,
        taskId: tasks.data.items[0].id,
      });
      const project = await window.desktop.projects.drafts.project({
        projectId: current.data.projectId,
      });
      return {
        mode: project.ok ? project.data.executionMode : null,
        tasks: tasks.data.items,
        task,
      };
    });
    expect(after.mode).toBe("synthetic");
    expect(after.tasks).toHaveLength(1);
    expect(after.task.ok && after.task.data.callIds).toHaveLength(1);
    await page.getByRole("button", { name: "关闭项目", exact: true }).click();
    await page
      .getByRole("button", { name: "任务恢复练习", exact: true })
      .click();
    await expect(page.getByRole("region", { name: "持久任务" })).toContainText(
      after.tasks[0].id,
    );
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
