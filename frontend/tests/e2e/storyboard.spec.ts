import { _electron as electron, expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";

test("story, asset and shot drafts stay editable across navigation and expose coverage and versions", async () => {
  test.setTimeout(120_000);
  const workspace = resolve("../.cache/t07-desktop", randomUUID());
  const directory = resolve(workspace, "分镜项目");
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
    await page
      .getByRole("navigation", { name: "主导航" })
      .getByRole("button", { name: "故事" })
      .click();
    await expect(
      page.getByText("先创建或打开一个本地项目，再整理故事、视觉资产与分镜。"),
    ).toBeVisible();
    await app.evaluate(({ dialog }, folder) => {
      dialog.showOpenDialog = async () => ({
        canceled: false,
        filePaths: [folder],
      });
    }, directory);
    await page.getByRole("button", { name: "新建项目", exact: true }).click();
    await page.getByLabel("项目名称").fill("灯下分镜");
    await page.getByRole("button", { name: "选择空目录" }).click();
    await page.getByRole("button", { name: "创建项目", exact: true }).click();
    await page
      .getByLabel("故事原文", { exact: true })
      .fill("雨😀夜，旅人把灯递给陌生人。");
    await page
      .getByLabel("创作简报（可稍后补充）")
      .fill("保留递灯动作和雨夜情绪。");
    await page.getByRole("button", { name: "添加大纲" }).click();
    await page.getByLabel("大纲 1").fill("旅人在雨夜让出灯。");
    await page.getByRole("button", { name: "添加场景" }).click();
    await page.getByLabel("场景名称").fill("雨夜街口");
    await page.getByLabel("场景动作").fill("旅人举灯，陌生人靠近。");
    await page.getByRole("button", { name: "添加要求" }).click();
    await page.getByLabel("要求内容").fill("必须让观众看到递灯");
    await page.getByRole("button", { name: "立即保存" }).click();
    await expect(page.getByTestId("draft-save-status")).toContainText("已保存");
    await page.getByRole("button", { name: "保存为新候选" }).click();
    await expect(
      page.getByRole("region", { name: "版本对照与采用" }),
    ).toContainText("候选已保存");
    await page.getByRole("button", { name: "预览采用影响" }).click();
    await page.getByRole("button", { name: "采用并标记待审核" }).click();
    await page
      .getByRole("navigation", { name: "主导航" })
      .getByRole("button", { name: "视觉与分镜" })
      .click();
    const workbench = page.getByRole("region", { name: "视觉资产与分镜" });
    await expect(workbench).toBeVisible();
    await workbench.getByRole("button", { name: "新建资产" }).click();
    await workbench.getByLabel("资产名称").fill("旅人");
    await workbench.getByRole("button", { name: "添加身份锚点" }).click();
    await workbench.getByLabel("身份锚点 1").fill("蓝色旧雨衣");
    await workbench.getByRole("button", { name: "保存当前草稿" }).click();
    await expect(
      workbench.getByText("旅人", { exact: false }).first(),
    ).toBeVisible();
    await workbench.getByRole("button", { name: "新建镜头" }).click();
    await workbench
      .getByLabel("观看目的")
      .fill("观众看到灯从一只手交到另一只手。");
    await workbench.getByLabel("起点").fill("旅人持灯");
    await workbench.getByLabel("终点").fill("陌生人持灯");
    await workbench.getByLabel("摄影安排").fill("手部近景，不切开交接动作");
    await workbench.getByRole("button", { name: "添加事件" }).click();
    await workbench.getByLabel("发生了什么").fill("灯在观众面前完成交接");
    await workbench.getByRole("button", { name: "保存当前草稿" }).click();
    await expect(
      workbench.getByRole("button", { name: "镜头 1", exact: true }),
    ).toBeVisible();
    await workbench.evaluate((element) =>
      element.scrollIntoView({ block: "start" }),
    );
    await page.screenshot({
      path: resolve(workspace, "storyboard.png"),
      fullPage: false,
    });
    await workbench.getByRole("button", { name: "查看版本与对照" }).click();
    await expect(
      page.getByRole("region", { name: "版本对照与采用" }),
    ).toContainText("镜头");
    await page.getByRole("button", { name: "保存为新候选" }).click();
    await expect(
      page.getByRole("region", { name: "版本对照与采用" }),
    ).toContainText("候选已保存");
    await page
      .getByRole("navigation", { name: "主导航" })
      .getByRole("button", { name: "故事" })
      .click();
    await expect(page.getByLabel("故事原文", { exact: true })).toHaveValue(
      "雨😀夜，旅人把灯递给陌生人。",
    );
    const storyVersions = page.getByRole("region", { name: "版本对照与采用" });
    await expect(
      storyVersions.getByRole("heading", { name: "故事版本" }),
    ).toBeVisible();
    await page
      .getByLabel("创作简报（可稍后补充）")
      .fill("保留递灯动作和雨夜情绪。回到故事核对。");
    await page.getByRole("button", { name: "立即保存" }).click();
    await expect(page.getByTestId("draft-save-status")).toContainText("已保存");
    await storyVersions.getByRole("button", { name: "保存为新候选" }).click();
    await expect(storyVersions).toContainText(
      "保留递灯动作和雨夜情绪。回到故事核对。",
    );
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
