import { _electron as electron, test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { randomUUID } from "node:crypto";

test("synthetic plan is previewed before one real persistent start; lost response queries its original operation", async () => {
  test.setTimeout(120_000);
  const workspace = resolve("../.cache/t04-desktop", randomUUID());
  const directory = resolve(workspace, "练习项目");
  const ffmpeg = resolve(
    "../.local/research-20260915/ffmpeg/ffmpeg-9.0.1-essentials_build/bin/ffmpeg.exe",
  );
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
    await page.getByLabel("项目总预算（元）", { exact: true }).fill("20");
    await page.getByLabel("故事预算（元）", { exact: true }).fill("10");
    await page.getByLabel("图像预算（元）", { exact: true }).fill("10");
    await page.getByRole("button", { name: "保存预算", exact: true }).click();
    await expect(page.getByRole("region", { name: "费用汇总" })).toContainText(
      "¥ 20",
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
      Object.assign(globalThis, {
        taskStartCount: 0,
        imageDraftSaveCount: 0,
        dropNextImageDraftSave: false,
      });
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
        const globals = globalThis as unknown as {
          imageDraftSaveCount: number;
          dropNextImageDraftSave: boolean;
        };
        const imageDraftSave =
          options.method === "PUT" &&
          /\/drafts\/[0-9a-f-]+$/.test(options.path ?? "");
        if (imageDraftSave) globals.imageDraftSaveCount++;
        const request = original(options, (response) => {
          if (start && !dropped && response.statusCode === 202) {
            dropped = true;
            response.resume();
            request.destroy(new Error("receipt intentionally lost"));
          } else if (
            imageDraftSave &&
            globals.dropNextImageDraftSave &&
            response.statusCode === 200
          ) {
            globals.dropNextImageDraftSave = false;
            response.resume();
            request.destroy(
              new Error("image draft receipt intentionally lost"),
            );
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
    const textCandidates = page.getByRole("region", { name: "任务候选结果" });
    await expect(textCandidates).toContainText("故事候选");
    await expect(textCandidates).toContainText("本地固定合成");
    await textCandidates
      .getByRole("button", { name: "在版本面板中对照", exact: true })
      .click();
    const versionPanel = page.getByRole("region", { name: "版本对照与采用" });
    await expect(versionPanel).toContainText("浏览不会改变作品");
    await versionPanel
      .getByRole("button", { name: "预览采用影响", exact: true })
      .click();
    await versionPanel
      .getByRole("button", { name: "采用并标记待审核", exact: true })
      .click();
    await expect(versionPanel).toContainText("候选已采用");

    await app.evaluate(() => {
      (
        globalThis as unknown as { dropNextImageDraftSave: boolean }
      ).dropNextImageDraftSave = true;
    });
    await page.getByLabel("结果类型").selectOption("image");
    await page.getByLabel("素材名称").fill("门灯旅人");
    await page.getByLabel("身份锚点（每行一项）").fill("深色雨衣\n旧帆布包");
    await page
      .getByRole("button", { name: "生成本地计划", exact: true })
      .click();
    await expect(page.getByText(/保存图像输入的响应尚待确认/)).toBeVisible();
    await page.getByRole("button", { name: "查询原操作", exact: true }).click();
    await page
      .getByRole("button", { name: "生成本地计划", exact: true })
      .click();
    expect(
      await app.evaluate(
        () =>
          (globalThis as unknown as { imageDraftSaveCount: number })
            .imageDraftSaveCount,
      ),
    ).toBe(1);
    await expect(preview).toContainText("门灯旅人");
    await page
      .getByLabel("我已核对输入、外发内容与最高费用，并接受本次披露")
      .check();
    await page
      .getByRole("button", { name: "确认并启动任务", exact: true })
      .click();
    const imageDetail = page.getByRole("region", { name: "原任务详情" });
    await expect(imageDetail).toBeVisible();
    await expect(
      imageDetail.getByRole("button", { name: "恢复原结果下载", exact: true }),
    ).toBeVisible();
    await app.evaluate(({ dialog }, file) => {
      dialog.showOpenDialog = async () => ({
        canceled: false,
        filePaths: [file],
      });
    }, ffmpeg);
    await page
      .getByRole("region", { name: "项目素材", exact: true })
      .getByRole("button", { name: "选择 FFmpeg", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "项目素材", exact: true }),
    ).toContainText("FFmpeg 已配置");
    await imageDetail
      .getByRole("button", { name: "恢复原结果下载", exact: true })
      .click();
    await expect
      .poll(async () => {
        await imageDetail
          .getByRole("button", { name: "查询原任务", exact: true })
          .click();
        return imageDetail.textContent();
      })
      .toContain("已完成");
    const imageCandidates = page.getByRole("region", { name: "任务候选结果" });
    await expect(imageCandidates).toContainText("角色图像候选：门灯旅人");
    await expect(imageCandidates.getByRole("img")).toBeVisible();
    await imageCandidates.evaluate((element) =>
      element.scrollIntoView({ block: "start" }),
    );
    await page.screenshot({
      path: resolve(workspace, "tasks-image-candidate.png"),
      fullPage: false,
    });
    await imageCandidates
      .getByRole("button", { name: "在版本面板中对照", exact: true })
      .click();
    await expect(versionPanel).toContainText("图像版本");
    await versionPanel
      .getByRole("button", { name: "预览采用影响", exact: true })
      .click();
    await versionPanel
      .getByRole("button", { name: "采用并标记待审核", exact: true })
      .click();
    await expect(versionPanel).toContainText("候选已采用");
    expect(
      await app.evaluate(
        () =>
          (globalThis as unknown as { taskStartCount: number }).taskStartCount,
      ),
    ).toBe(2);
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
    expect(after.tasks).toHaveLength(2);
    expect(after.task.ok && after.task.data.callIds).toHaveLength(1);
    const imageTask = after.tasks.find((item) => item.stage === "image");
    expect(imageTask).toBeTruthy();
    await page.getByRole("button", { name: "关闭项目", exact: true }).click();
    await page
      .getByRole("button", { name: "任务恢复练习", exact: true })
      .click();
    await expect(page.getByRole("region", { name: "持久任务" })).toContainText(
      imageTask!.id,
    );
    await page.getByRole("button", { name: new RegExp(imageTask!.id) }).click();
    await expect(
      page.getByRole("region", { name: "任务候选结果" }),
    ).toContainText("门灯旅人");
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
