import {
  _electron as electron,
  expect,
  test,
  type ElectronApplication,
} from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { randomUUID } from "node:crypto";
import type { DesktopBridge } from "../../electron/shared/runtime";

test("storyboard accordion preserves prompts and asset links across reloads", async () => {
  const root = resolve("../.cache/episode-flow", randomUUID());
  const directory = resolve(root, "project");
  const userData = resolve(root, "appdata");
  await mkdir(directory, { recursive: true });
  await mkdir(userData, { recursive: true });
  const env = Object.fromEntries(
    Object.entries(process.env).filter(
      (entry): entry is [string, string] => entry[1] !== undefined,
    ),
  );
  env.APPDATA = userData;
  env.AVI_E2E_OFFSCREEN_WINDOW = "1";
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.ELECTRON_RENDERER_URL;
  let app: ElectronApplication | undefined;
  try {
    app = await electron.launch({
      executablePath: resolve("node_modules/electron/dist/electron.exe"),
      args: [resolve("."), `--user-data-dir=${userData}`],
      env,
    });
    const page = await app.firstWindow();
    await expect
      .poll(
        async () => {
          const status = await page.evaluate(() =>
            (
              window as unknown as { desktop: DesktopBridge }
            ).desktop.getRuntimeState(),
          );
          if (!status.ok) return status.error.code;
          return status.data.state === "failed"
            ? `failed:${status.data.errorCode}`
            : status.data.state;
        },
        { timeout: 15_000 },
      )
      .toBe("ready");
    await app.evaluate(({ dialog }, folder) => {
      dialog.showOpenDialog = async () => ({
        canceled: false,
        filePaths: [folder],
      });
    }, directory);
    await page.getByRole("button", { name: "新建项目", exact: true }).click();
    await page.getByLabel("项目名称").fill("演示分集");
    await page.getByRole("button", { name: "选择空目录" }).click();
    await page.getByRole("button", { name: "创建项目", exact: true }).click();
    await page.getByRole("button", { name: "新增一集" }).click();
    await page.getByLabel("标题", { exact: true }).fill("雨夜借光");
    await page.getByRole("button", { name: "添加分集" }).click();
    await page.getByRole("button", { name: /进入第 2 集/ }).click();
    await page
      .getByLabel("本集小说")
      .fill("雨夜里，主人公寻找光源，遇到同行者，最终共同穿过街道。");
    await page.getByRole("button", { name: "演示生成剧本" }).click();
    await page.getByRole("button", { name: "选用此候选" }).click();
    await page.getByRole("button", { name: "一键生成文本框架" }).click();
    for (const kind of ["角色", "道具", "场景"]) {
      await page.getByRole("tab", { name: kind, exact: true }).click();
      const asset = page.locator(".episode-library-asset-card");
      await expect(asset).toHaveCount(1);
      await asset.getByRole("button", { name: "编辑", exact: true }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByRole("button", { name: "生成演示图片" }).click();
      await dialog.locator(".episode-image-candidates button").last().click();
      await dialog.getByRole("button", { name: "确认采用" }).click();
      await dialog.getByRole("button", { name: "关闭", exact: true }).click();
    }
    const stage = page.getByTestId("episode-stage-storyboard");
    await expect(
      page
        .getByRole("navigation", { name: "分集制作流程" })
        .getByRole("button"),
    ).toHaveCount(4);
    await expect(page.getByTestId("episode-stage-video")).toHaveCount(0);
    const shots = stage.locator(".storyboard-item");
    await stage
      .getByRole("button", { name: "生成分镜脚本", exact: true })
      .click();
    await expect(shots).toHaveCount(2);
    await expect(stage.locator(".storyboard-item[open]")).toHaveCount(0);
    await expect(shots.first().getByLabel("图片提示词")).not.toBeVisible();
    const screenshots = resolve("../.cache/storyboard-table-review");
    await mkdir(screenshots, { recursive: true });
    await app.evaluate(({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows()[0]!;
      window.setMinimumSize(0, 0);
      window.setContentSize(1440, 1600);
      window.webContents.setZoomFactor(1);
    });
    await page.setViewportSize({ width: 1440, height: 1600 });
    await stage.screenshot({ path: resolve(screenshots, "collapsed.png") });
    await shots.first().locator(":scope > summary").click();
    await expect(shots.first().getByLabel("图片提示词")).toBeVisible();
    await expect(shots.nth(1).getByLabel("图片提示词")).not.toBeVisible();
    await expect(shots.first().locator(".storyboard-linked-asset")).toHaveCount(
      3,
    );
    await expect(
      shots.first().locator(".storyboard-image-placeholder"),
    ).toBeEmpty();
    await expect(
      shots.first().locator(".storyboard-video-placeholder"),
    ).toBeEmpty();
    await expect(
      shots.first().getByRole("button", { name: "生成分镜图", exact: true }),
    ).toBeDisabled();
    await expect(
      shots.first().getByRole("button", { name: "生成视频", exact: true }),
    ).toBeDisabled();
    await expect(shots.first().getByRole("table")).toBeVisible();
    const columns = await shots
      .first()
      .locator(".storyboard-production-table tr")
      .first()
      .evaluate((element) =>
        Array.from(element.children).map(
          (child) => child.getBoundingClientRect().x,
        ),
      );
    expect(columns[0]).toBeLessThan(columns[1]!);
    const groups = await shots
      .first()
      .locator(".storyboard-asset-group")
      .evaluateAll((elements) =>
        elements.map((element) => element.getBoundingClientRect().x),
      );
    expect(groups[0]).toBeLessThan(groups[1]!);
    expect(groups[1]).toBeLessThan(groups[2]!);
    await stage.screenshot({ path: resolve(screenshots, "desktop.png") });
    await shots
      .first()
      .getByLabel("图片提示词")
      .fill("近景，暖色门灯，细密雨丝。手动修改后保存。");
    await shots
      .first()
      .getByLabel("视频提示词")
      .fill("人物缓慢前行，镜头轻推，保持环境一致。");
    await expect(stage.locator(".storyboard-item[open]")).toHaveCount(1);
    await shots
      .first()
      .getByRole("button", { name: "取消关联林小雨", exact: true })
      .click();
    await expect(shots.first().locator(".storyboard-linked-asset")).toHaveCount(
      2,
    );
    await shots
      .first()
      .locator(".storyboard-asset-picker > summary")
      .filter({ hasText: "添加关联角色" })
      .click();
    await shots
      .first()
      .getByRole("button", { name: /林小雨/ })
      .click();
    await expect(shots.first().locator(".storyboard-linked-asset")).toHaveCount(
      3,
    );
    await shots
      .first()
      .getByRole("button", { name: "取消关联旧铜手提灯", exact: true })
      .click();
    await expect(shots.first().locator(".storyboard-linked-asset")).toHaveCount(
      2,
    );
    await app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()[0]!.setContentSize(390, 2400);
    });
    await page.setViewportSize({ width: 390, height: 2400 });
    await stage.screenshot({ path: resolve(screenshots, "mobile.png") });
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      )
      .toBe(true);
    await stage.screenshot({ path: resolve(screenshots, "mobile.png") });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await shots.first().locator(":scope > summary").focus();
    await page.keyboard.press("Enter");
    await expect(stage.locator(".storyboard-item[open]")).toHaveCount(0);
    await page.keyboard.press("Enter");
    await expect(stage.locator(".storyboard-item[open]")).toHaveCount(1);
    await page.reload();
    await expect(page.getByTestId("runtime-status")).toHaveText(
      "本地服务已连接",
    );
    await page.getByRole("button", { name: "打开项目 演示分集" }).click();
    await page.getByRole("button", { name: /进入第 2 集/ }).click();
    await expect(shots).toHaveCount(2);
    await expect(stage.locator(".storyboard-item[open]")).toHaveCount(0);
    await shots.first().locator(":scope > summary").click();
    await expect(shots.first().getByLabel("图片提示词")).toHaveValue(
      "近景，暖色门灯，细密雨丝。手动修改后保存。",
    );
    await expect(shots.first().getByLabel("视频提示词")).toHaveValue(
      "人物缓慢前行，镜头轻推，保持环境一致。",
    );
    await expect(shots.first().locator(".storyboard-linked-asset")).toHaveCount(
      2,
    );
    await shots.nth(1).locator(":scope > summary").click();
    await expect(shots.nth(1).locator(".storyboard-linked-asset")).toHaveCount(
      3,
    );
    await expect(shots.nth(1).getByLabel("图片提示词")).not.toHaveValue(
      "近景，暖色门灯，细密雨丝。手动修改后保存。",
    );
    await expect(stage.locator(".storyboard-item[open]")).toHaveCount(2);
    page.once("dialog", (dialog) => void dialog.dismiss());
    await stage
      .getByRole("button", { name: "生成分镜脚本", exact: true })
      .click();
    await expect(shots.first().getByLabel("图片提示词")).toHaveValue(
      "近景，暖色门灯，细密雨丝。手动修改后保存。",
    );
    page.once("dialog", (dialog) => void dialog.accept());
    await stage
      .getByRole("button", { name: "生成分镜脚本", exact: true })
      .click();
    await expect(shots).toHaveCount(2);
    await expect(stage.locator(".storyboard-item[open]")).toHaveCount(0);
  } finally {
    await app?.close();
  }
});
