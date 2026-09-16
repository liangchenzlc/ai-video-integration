import { _electron as electron, expect, test } from "@playwright/test";
import { mkdir, readFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";

async function launchDesktop(workspace: string) {
  await mkdir(resolve(workspace, "appdata"), { recursive: true });
  const env = Object.fromEntries(
    Object.entries(process.env).filter(
      (entry): entry is [string, string] => entry[1] !== undefined,
    ),
  );
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.ELECTRON_RENDERER_URL;
  env.APPDATA = resolve(workspace, "appdata");
  return electron.launch({
    executablePath:
      process.env.T01_DESKTOP_EXE ||
      resolve("node_modules/electron/dist/electron.exe"),
    args: [
      ...(process.env.T01_DESKTOP_EXE ? [] : [resolve(".")]),
      `--user-data-dir=${resolve(workspace, "appdata")}`,
    ],
    env,
  });
}

test("settings saves a base diagnostic ZIP without a project", async () => {
  test.setTimeout(120_000);
  const workspace = resolve("../.cache/t13-desktop", randomUUID());
  const target = resolve(workspace, "diagnostic.zip");
  await mkdir(workspace, { recursive: true });
  const app = await launchDesktop(workspace);
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(page.getByTestId("runtime-status")).toHaveText(
      "本地服务已连接",
    );
    await app.evaluate(({ dialog }, file) => {
      dialog.showSaveDialog = async () => ({ canceled: false, filePath: file });
    }, target);
    await page
      .getByRole("navigation", { name: "主导航" })
      .getByRole("button", { name: "设置" })
      .click();
    const panel = page.getByRole("region", { name: "本地诊断包" });
    await expect(panel.getByLabel("包含当前项目状态")).toBeDisabled();
    await panel.getByRole("button", { name: "预览文件清单" }).click();
    await expect(panel).toContainText("runtime.json");
    await panel.getByRole("button", { name: "选择本机保存位置" }).click();
    await expect(panel).toContainText("diagnostic.zip");
    await panel.getByRole("button", { name: "生成并保存诊断包" }).click();
    await expect(panel).toContainText("已完成", { timeout: 20000 });
    const archive = await readFile(target);
    expect(archive.subarray(0, 2).toString()).toBe("PK");
    expect(archive.includes(Buffer.from("runtime.json"))).toBe(true);
    expect(archive.includes(Buffer.from("content.json"))).toBe(false);
    await panel.evaluate((element) =>
      element.scrollIntoView({ block: "start" }),
    );
    await page.screenshot({
      path: resolve(workspace, "diagnostic.png"),
      fullPage: false,
    });
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});

test("timeline candidate runs eight real local checks and records a gap issue", async () => {
  test.setTimeout(120_000);
  const workspace = resolve("../.cache/t13-desktop", randomUUID());
  const directory = resolve(workspace, "剪辑项目");
  await mkdir(directory, { recursive: true });
  const app = await launchDesktop(workspace);
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
    await page.getByLabel("项目名称").fill("剪辑结构检查");
    await page.getByRole("button", { name: "选择空目录" }).click();
    await page.getByRole("button", { name: "创建项目", exact: true }).click();
    await page
      .getByRole("navigation", { name: "主导航" })
      .getByRole("button", { name: "声音与剪辑" })
      .click();
    const workbench = page.getByRole("region", { name: "声音、剪辑与成片" });
    await workbench
      .getByRole("button", { name: "时间线", exact: true })
      .click();
    await workbench.getByRole("button", { name: "新建时间线草稿" }).click();
    await expect(workbench.getByLabel("项目时长（毫秒）")).toBeVisible();
    await workbench.getByLabel("项目时长（毫秒）").fill("10000");
    await workbench
      .getByRole("button", { name: "添加轨道", exact: true })
      .click();
    await workbench
      .getByRole("button", { name: "保存草稿", exact: true })
      .click();
    await expect(workbench).toContainText("草稿已保存");
    await workbench.getByRole("button", { name: "版本对照与采用" }).click();
    const versions = page.getByRole("region", { name: "版本对照与采用" });
    await expect(
      versions.getByRole("heading", { name: "时间线版本" }),
    ).toBeVisible();
    await versions.getByRole("button", { name: "保存为新候选" }).click();
    await expect(versions).toContainText("候选已保存");
    await expect(versions).toContainText("1 条轨道 · 0 个片段 · 总长 10 秒");
    await versions.getByRole("button", { name: "预览采用影响" }).click();
    await versions.getByRole("button", { name: "采用并标记待审核" }).click();
    await versions
      .getByRole("button", { name: "运行成片八项本地检查" })
      .click();
    const report = versions.getByRole("region", { name: "本地检查报告" });
    for (const rule of [
      "内容结构",
      "引用关系",
      "素材可用性",
      "时间线边界",
      "对白时间",
      "声音来源",
      "声音交付",
      "要求承载",
    ]) {
      await expect(report).toContainText(rule);
    }
    await expect(report).toContainText("未通过");
    const issue = await page.evaluate(async () => {
      const session = await window.desktop.projects.current();
      if (!session.ok || !session.data) throw new Error("Missing project");
      return window.desktop.production.issues({
        projectId: session.data.projectId,
        limit: 50,
      });
    });
    expect(issue.ok).toBe(true);
    if (issue.ok)
      expect(
        issue.data.items.some(
          (row) =>
            row.ruleId === "timeline.bounds" && row.message === "TIMELINE_GAP",
        ),
      ).toBe(true);
    await versions.evaluate((element) =>
      element.scrollIntoView({ block: "start" }),
    );
    await page.screenshot({
      path: resolve(workspace, "timeline-check.png"),
      fullPage: false,
      animations: "disabled",
      timeout: 15000,
    });
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
