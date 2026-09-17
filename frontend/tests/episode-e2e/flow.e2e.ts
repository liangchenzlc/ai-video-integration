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

test("episode demo survives two nine-grid batches and stales only the edited shot video", async () => {
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
    await page.getByRole("button", { name: /进入第 1 集/ }).click();
    await page
      .getByLabel("本集小说")
      .fill("雨夜里，主人公寻找光源，遇到同行者，最终共同穿过街道。");
    await page.getByRole("button", { name: "演示生成剧本" }).click();
    await page.getByRole("button", { name: "选用此候选" }).click();
    await page.getByRole("button", { name: "确认剧本" }).click();
    await page.getByRole("button", { name: "演示分析素材" }).click();
    const assets = page.locator(".episode-asset-card");
    await expect(assets).toHaveCount(3);
    for (let index = 0; index < 3; index++) {
      const asset = assets.nth(index);
      await asset.getByRole("button", { name: "生成演示图片" }).click();
      await asset.locator(".episode-image-candidates button").last().click();
      await asset.getByRole("button", { name: "确认采用" }).click();
    }
    await page.getByRole("button", { name: "生成演示分镜脚本" }).click();
    for (let index = 3; index < 10; index++)
      await page.getByRole("button", { name: "添加镜头" }).click();
    await expect(page.locator(".episode-storyboard-shot")).toHaveCount(10);
    for (let index = 0; index < 10; index++) {
      const shot = page.locator(".episode-storyboard-shot").nth(index);
      if (index >= 3) {
        await shot.getByLabel("构图说明").fill(`镜头 ${index + 1} 街道构图`);
        await shot.getByLabel("动作", { exact: true }).fill("人物向前行走");
      }
      await shot.getByRole("button", { name: "确认本镜文字" }).click();
    }
    await page.getByRole("button", { name: "九宫格分镜" }).click();
    await page.getByRole("button", { name: "生成演示九宫格" }).click();
    await expect(page.locator(".episode-grid-batch")).toHaveCount(2);
    await expect(page.locator(".episode-grid-cell")).toHaveCount(10);
    for (let index = 0; index < 10; index++) {
      const cell = page.locator(".episode-grid-cell").nth(index);
      await cell.getByRole("button", { name: "生成演示单格" }).click();
      await cell.getByRole("button", { name: "确认单格" }).click();
      await cell.getByRole("button", { name: "采用为首帧" }).click();
    }
    await page.getByRole("button", { name: "确认分镜阶段" }).click();
    const videos = page.locator(".episode-video-shot");
    await videos.nth(0).getByRole("button", { name: "生成演示视频" }).click();
    await videos.nth(0).getByRole("button", { name: "确认本镜视频" }).click();
    await videos.nth(1).getByRole("button", { name: "生成演示视频" }).click();
    await videos.nth(1).getByRole("button", { name: "确认本镜视频" }).click();
    await page.reload();
    await expect(page.getByTestId("runtime-status")).toHaveText(
      "本地服务已连接",
    );
    await page.getByRole("button", { name: "打开项目 演示分集" }).click();
    await page.getByRole("button", { name: /进入第 1 集/ }).click();
    await expect(page.locator(".episode-grid-batch")).toHaveCount(2);
    await expect(videos.nth(0)).toContainText("已确认");
    await expect(videos.nth(1)).toContainText("已确认");
    await page
      .locator(".episode-storyboard-shot")
      .nth(0)
      .getByLabel("镜头标题")
      .fill("修改后的镜头");
    await expect(videos.nth(0)).toContainText("需复核");
    await expect(videos.nth(1)).toContainText("已确认");
  } finally {
    await app?.close();
  }
});
