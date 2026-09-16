import { _electron as electron, expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";

test("candidate browsing stays read-only; adopt, local check, confirm and latest undo persist", async () => {
  test.setTimeout(120_000);
  const workspace = resolve("../.cache/t05-desktop", randomUUID());
  const directory = resolve(workspace, "版本项目");
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
    page.on("pageerror", (error) => errors.push(error.message));
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
    await page.getByLabel("项目名称").fill("版本采用练习");
    await page.getByRole("button", { name: "选择空目录" }).click();
    await page.getByRole("button", { name: "创建项目", exact: true }).click();

    await page
      .getByLabel("故事原文", { exact: true })
      .fill("雨夜，旅人把唯一的灯留给陌生人。明早他发现门前多了一把伞。");
    await page
      .getByLabel("创作简报（可稍后补充）")
      .fill("温暖克制，保留灯与伞的因果。");
    await expect(page.getByTestId("draft-save-status")).toContainText("已保存");
    await page
      .getByRole("button", { name: "保存为新候选", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "版本对照与采用" }),
    ).toContainText("候选已保存");

    const beforeAdoption = await page.evaluate(async () => {
      const current = await window.desktop.projects.current();
      if (!current.ok || !current.data) throw new Error("Missing project");
      const drafts = await window.desktop.projects.drafts.list({
        projectId: current.data.projectId,
      });
      if (!drafts.ok) throw new Error("Missing draft");
      const story = drafts.data.find((item) => item.kind === "story");
      if (!story) throw new Error("Missing story draft");
      return window.desktop.versions.artifact({
        projectId: current.data.projectId,
        artifactId: story.artifactId,
      });
    });
    expect(
      beforeAdoption.ok && beforeAdoption.data.adoptedRevisionId,
    ).toBeNull();
    await page
      .getByRole("region", { name: "版本对照与采用" })
      .evaluate((element) => element.scrollIntoView({ block: "start" }));
    await page.screenshot({
      path: resolve(workspace, "versions-candidate.png"),
      fullPage: false,
    });

    await page
      .getByRole("button", { name: "预览采用影响", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "采用影响预览" }),
    ).toBeVisible();
    await page.screenshot({
      path: resolve(workspace, "versions-impact.png"),
      fullPage: false,
    });
    await page
      .getByRole("button", { name: "采用并标记待审核", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "版本对照与采用" }),
    ).toContainText("候选已采用，必要检查通过后才能确认");
    await app.evaluate(() => {
      const http = process.getBuiltinModule(
        "http",
      ) as typeof import("node:http");
      const original = http.request;
      Object.assign(globalThis, {
        localCheckPostCount: 0,
        dropNextCheckJobRead: true,
        delayNextDraftRead: false,
      });
      http.request = ((
        options: import("node:http").RequestOptions,
        callback: (response: import("node:http").IncomingMessage) => void,
      ) => {
        const globals = globalThis as unknown as {
          localCheckPostCount: number;
          dropNextCheckJobRead: boolean;
          delayNextDraftRead: boolean;
        };
        const path = options.path ?? "";
        const localCheck =
          options.method === "POST" && /\/local-checks$/.test(path);
        const checkJobRead =
          options.method === "GET" && /\/jobs\/[0-9a-f-]+$/.test(path);
        const draftRead =
          options.method === "GET" && /\/drafts\/[0-9a-f-]+$/.test(path);
        if (localCheck) globals.localCheckPostCount++;
        const request = original(options, (response) => {
          if (checkJobRead && globals.dropNextCheckJobRead) {
            globals.dropNextCheckJobRead = false;
            response.resume();
            request.destroy(new Error("check job read intentionally lost"));
          } else if (draftRead && globals.delayNextDraftRead) {
            globals.delayNextDraftRead = false;
            setTimeout(() => callback(response), 2000);
          } else callback(response);
        });
        return request;
      }) as typeof http.request;
    });
    await page
      .getByRole("button", { name: "运行本地结构检查", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "查询这次检查", exact: true }),
    ).toBeVisible();
    expect(
      await app.evaluate(
        () =>
          (globalThis as unknown as { localCheckPostCount: number })
            .localCheckPostCount,
      ),
    ).toBe(1);
    await page
      .getByRole("button", { name: "查询这次检查", exact: true })
      .click();
    const report = page.getByRole("region", { name: "本地检查报告" });
    await expect(report).toContainText("通过");
    await expect(report).toContainText(
      "不代表语义、审美、模型质量或人工审核结论",
    );
    await app.evaluate(() => {
      (
        globalThis as unknown as { delayNextDraftRead: boolean }
      ).delayNextDraftRead = true;
    });
    await page.getByRole("button", { name: "关闭项目", exact: true }).click();
    await page
      .getByRole("button", { name: "版本采用练习", exact: true })
      .click();
    await expect(
      page.getByText("正在读取草稿…", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "保存为新候选", exact: true }),
    ).toBeDisabled();
    await expect(page.getByTestId("draft-save-status")).toContainText("已保存");
    await expect(
      page.getByRole("button", { name: "保存为新候选", exact: true }),
    ).toBeEnabled();
    await expect(report).toContainText("通过");
    expect(
      await app.evaluate(
        () =>
          (globalThis as unknown as { localCheckPostCount: number })
            .localCheckPostCount,
      ),
    ).toBe(1);
    await page
      .getByRole("button", { name: "确认当前采用版本", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "版本对照与采用" }),
    ).toContainText("当前采用版本已确认");
    await page
      .getByRole("region", { name: "版本对照与采用" })
      .evaluate((element) => element.scrollIntoView({ block: "start" }));
    await page.screenshot({
      path: resolve(workspace, "versions-confirmed.png"),
      fullPage: false,
    });

    const baseline = await page.evaluate(async () => {
      const current = await window.desktop.projects.current();
      if (!current.ok || !current.data) throw new Error("Missing project");
      const drafts = await window.desktop.projects.drafts.list({
        projectId: current.data.projectId,
      });
      if (!drafts.ok) throw new Error("Missing draft");
      const story = drafts.data.find((item) => item.kind === "story");
      if (!story) throw new Error("Missing story draft");
      const artifact = await window.desktop.versions.artifact({
        projectId: current.data.projectId,
        artifactId: story.artifactId,
      });
      if (!artifact.ok) throw new Error("Missing artifact");
      return artifact.data;
    });
    expect(baseline.adoptedRevisionId).toBeTruthy();
    expect(baseline.confirmedRevisionId).toBe(baseline.adoptedRevisionId);

    await page
      .getByLabel("故事原文", { exact: true })
      .fill("雨夜，旅人把唯一的灯留给陌生人。清晨，门前多了一把红伞。");
    await expect(page.getByTestId("draft-save-status")).toContainText("已保存");
    await page
      .getByRole("button", { name: "保存为新候选", exact: true })
      .click();
    await page
      .getByRole("button", { name: "预览采用影响", exact: true })
      .click();
    await page
      .getByRole("button", { name: "采用并标记待审核", exact: true })
      .click();
    await page.getByRole("button", { name: "关闭项目", exact: true }).click();
    await page
      .getByRole("button", { name: "版本采用练习", exact: true })
      .click();
    await page
      .getByRole("button", { name: "撤销最近一次采用", exact: true })
      .evaluate((element) => element.scrollIntoView({ block: "center" }));
    await page.screenshot({
      path: resolve(workspace, "versions-reopened-undo.png"),
      fullPage: false,
    });
    await page
      .getByRole("button", { name: "撤销最近一次采用", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "版本对照与采用" }),
    ).toContainText("最近一次采用已撤销");
    await page.getByRole("button", { name: "关闭项目", exact: true }).click();
    await page
      .getByRole("button", { name: "版本采用练习", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "版本对照与采用" }),
    ).toContainText("已确认当前采用");
    await page
      .getByRole("region", { name: "版本对照与采用" })
      .evaluate((element) => element.scrollIntoView({ block: "start" }));
    await page.screenshot({
      path: resolve(workspace, "versions-restored.png"),
      fullPage: false,
    });
    const reopened = await page.evaluate(async () => {
      const current = await window.desktop.projects.current();
      if (!current.ok || !current.data) throw new Error("Missing project");
      const drafts = await window.desktop.projects.drafts.list({
        projectId: current.data.projectId,
      });
      if (!drafts.ok) throw new Error("Missing draft");
      const story = drafts.data.find((item) => item.kind === "story");
      if (!story) throw new Error("Missing story draft");
      return window.desktop.versions.artifact({
        projectId: current.data.projectId,
        artifactId: story.artifactId,
      });
    });
    expect(reopened.ok && reopened.data.adoptedRevisionId).toBe(
      baseline.adoptedRevisionId,
    );
    expect(reopened.ok && reopened.data.confirmedRevisionId).toBe(
      baseline.confirmedRevisionId,
    );
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
