import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

test("production table edits and persists image/video prompts independently", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1440, height: 1600 });
  await page.goto("/tests/episode-e2e/production-preview.html");
  const stage = page.getByTestId("episode-stage-storyboard");
  const shots = stage.locator(".storyboard-item");
  await expect(
    page.getByRole("navigation", { name: "分集制作流程" }).getByRole("button"),
  ).toHaveCount(4);
  await expect(page.getByTestId("episode-stage-video")).toHaveCount(0);
  await stage
    .getByRole("button", { name: "生成分镜脚本", exact: true })
    .click();
  await expect(shots).toHaveCount(2);
  await expect(stage.locator(".storyboard-item[open]")).toHaveCount(0);
  const screenshots = resolve("../.cache/episode-density-review");
  await mkdir(screenshots, { recursive: true });
  for (const label of ["演示生成剧本", "一键生成文本框架", "生成分镜脚本"]) {
    await expect(
      page.getByRole("button", { name: label, exact: true }),
    ).toHaveClass(/ant-btn-primary/);
  }
  const density = await page.evaluate(() => {
    const layout = document
      .querySelector(".episode-layout")!
      .getBoundingClientRect();
    const sidebar = document
      .querySelector(".episode-sidebar")!
      .getBoundingClientRect();
    const content = getComputedStyle(
      document.querySelector(".episode-content")!,
    );
    return {
      heightDifference: Math.abs(layout.height - sidebar.height),
      inset: content.paddingLeft,
      gap: content.rowGap,
      bottomInset: content.paddingBottom,
    };
  });
  expect(density).toEqual({
    heightDifference: 0,
    inset: "24px",
    gap: "24px",
    bottomInset: "32px",
  });
  await page
    .getByRole("navigation", { name: "分集制作流程" })
    .getByRole("button", { name: /小说与剧本生成/ })
    .click();
  await page.screenshot({ path: resolve(screenshots, "page-desktop.png") });
  await stage.screenshot({ path: resolve(screenshots, "collapsed.png") });
  await shots.first().locator(":scope > summary").click();
  await expect(shots.nth(1).getByLabel("视频提示词")).not.toBeVisible();
  await expect(
    shots.first().locator(".storyboard-production-table").getByRole("row"),
  ).toHaveCount(2);
  await expect(
    shots.first().locator(".storyboard-materials-table").getByRole("cell"),
  ).toHaveCount(3);
  await expect(shots.first().locator(".storyboard-asset-group h4")).toHaveText([
    "角色",
    "场景",
    "道具",
  ]);
  await expect(
    shots.first().getByRole("button", { name: "生成分镜图", exact: true }),
  ).toBeDisabled();
  await expect(
    shots.first().getByRole("button", { name: "生成视频", exact: true }),
  ).toBeDisabled();
  await expect(
    shots.first().locator(".storyboard-image-placeholder"),
  ).toBeEmpty();
  await expect(
    shots.first().locator(".storyboard-video-placeholder"),
  ).toBeEmpty();
  const cells = await shots
    .first()
    .locator(".storyboard-production-table td")
    .evaluateAll((elements) =>
      elements.map((element) => {
        const rect = element.getBoundingClientRect();
        return { x: rect.x, y: rect.y };
      }),
    );
  expect(cells[0]!.x).toBeLessThan(cells[1]!.x);
  expect(cells[0]!.y).toBe(cells[1]!.y);
  expect(cells[2]!.y).toBeGreaterThan(cells[0]!.y);
  expect(cells[2]!.y).toBe(cells[3]!.y);
  const groups = await shots
    .first()
    .locator(".storyboard-asset-group")
    .evaluateAll((elements) =>
      elements.map((element) => element.getBoundingClientRect().x),
    );
  expect(groups[0]).toBeLessThan(groups[1]!);
  expect(groups[1]).toBeLessThan(groups[2]!);
  const materialLayout = await shots
    .first()
    .locator(".storyboard-materials")
    .evaluate((section) => {
      const heading = section.querySelector("h3");
      const table = section.querySelector("table")!.getBoundingClientRect();
      const cells = Array.from(section.querySelectorAll("td"));
      return {
        hasHeading: heading !== null,
        startsAtTop:
          Math.abs(table.top - section.getBoundingClientRect().top) < 1,
        dividers: cells
          .slice(1)
          .every((cell) => getComputedStyle(cell).borderLeftWidth === "1px"),
      };
    });
  expect(materialLayout).toEqual({
    hasHeading: false,
    startsAtTop: true,
    dividers: true,
  });
  await stage.screenshot({ path: resolve(screenshots, "desktop.png") });
  await page.setViewportSize({ width: 900, height: 1200 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await stage.screenshot({ path: resolve(screenshots, "tablet.png") });
  await shots
    .first()
    .getByLabel("图片提示词")
    .fill("近景，暖色门灯，细密雨丝。");
  await shots.first().getByLabel("视频提示词").fill("人物缓慢前行，镜头轻推。");
  await shots
    .first()
    .getByRole("button", { name: "取消关联林小雨", exact: true })
    .click();
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
    .locator(".storyboard-asset-picker > summary")
    .filter({ hasText: "添加关联角色" })
    .click();
  await page.setViewportSize({ width: 390, height: 2400 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  const mobileCells = await shots
    .first()
    .locator(".storyboard-production-table td")
    .evaluateAll((elements) =>
      elements.map((element) => element.getBoundingClientRect().y),
    );
  expect(
    mobileCells.every((y, index) => index === 0 || y > mobileCells[index - 1]!),
  ).toBe(true);
  await stage.screenshot({ path: resolve(screenshots, "mobile.png") });
  await page.reload();
  await expect(stage.locator(".storyboard-item[open]")).toHaveCount(0);
  await shots.first().locator(":scope > summary").focus();
  await page.keyboard.press("Enter");
  await expect(shots.first().getByLabel("图片提示词")).toHaveValue(
    "近景，暖色门灯，细密雨丝。",
  );
  await expect(shots.first().getByLabel("视频提示词")).toHaveValue(
    "人物缓慢前行，镜头轻推。",
  );
  await shots.nth(1).locator(":scope > summary").click();
  await expect(shots.nth(1).getByLabel("视频提示词")).not.toHaveValue(
    "人物缓慢前行，镜头轻推。",
  );
  await expect(stage.locator(".storyboard-item[open]")).toHaveCount(2);
  await page.goto("/tests/episode-e2e/production-preview.html?readonly");
  await shots.first().locator(":scope > summary").click();
  await expect(shots.first().getByLabel("视频提示词")).toHaveAttribute(
    "readonly",
    "",
  );
  await expect(shots.first().getByLabel("图片提示词")).toHaveAttribute(
    "readonly",
    "",
  );
  await expect(
    shots.first().getByRole("button", { name: /取消关联/ }),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("primary actions preserve script generation and asset dialog saving", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/tests/episode-e2e/production-preview.html");
  const nav = page.getByRole("navigation", { name: "分集制作流程" });
  await expect(
    page.getByText("查看上次保存的剧本版本", { exact: true }),
  ).toHaveCount(0);
  await nav.getByRole("button", { name: /小说与剧本生成/ }).click();
  await expect(
    nav.getByRole("button", { name: /小说与剧本生成/ }),
  ).toHaveAttribute("aria-current", "step");
  await page
    .getByLabel("本集小说", { exact: true })
    .fill("雨夜，林小雨走过旧城雨巷，提灯照向公寓的木门。");
  await page.getByRole("button", { name: "演示生成剧本", exact: true }).click();
  const choose = page.getByRole("button", { name: "选用此候选", exact: true });
  await expect(choose).toHaveClass(/ant-btn-primary/);
  page.once("dialog", (dialog) => dialog.accept());
  await choose.click();
  await page
    .getByRole("button", { name: "一键生成文本框架", exact: true })
    .click();
  await expect(
    page.getByText("当前剧本版本已保存", { exact: true }),
  ).toBeVisible();
  await nav.getByRole("button", { name: /素材图片/ }).click();
  const assets = page.getByTestId("episode-stage-assets");
  await expect(nav.getByRole("button", { name: /素材图片/ })).toHaveAttribute(
    "aria-current",
    "step",
  );
  await assets
    .getByRole("button", { name: "编辑", exact: true })
    .first()
    .click();
  const dialog = page.getByRole("dialog", { name: "编辑角色", exact: true });
  await expect(
    dialog.getByRole("button", { name: "保存", exact: true }),
  ).toHaveClass(/ant-btn-primary/);
  await dialog.getByLabel("名称", { exact: true }).fill("林小雨（雨衣）");
  await dialog
    .getByRole("textbox", { name: /^提示词描述/ })
    .fill("穿深蓝雨衣，手提旧铜灯。");
  const screenshots = resolve("../.cache/episode-density-review");
  await mkdir(screenshots, { recursive: true });
  await dialog.screenshot({ path: resolve(screenshots, "asset-dialog.png") });
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(
    assets.getByRole("heading", { name: "林小雨（雨衣）", exact: true }),
  ).toBeVisible();
  await assets.getByRole("button", { name: "新增人物", exact: true }).click();
  const create = page.getByRole("dialog", { name: "新增人物", exact: true });
  await expect(
    create.getByRole("button", { name: "保存", exact: true }),
  ).toBeDisabled();
  await create.getByRole("button", { name: "取消", exact: true }).click();
  await page.reload();
  await expect(
    assets.getByRole("heading", { name: "林小雨（雨衣）", exact: true }),
  ).toBeVisible();
  await nav.getByRole("button", { name: /分镜制作/ }).click();
  await expect(nav.getByRole("button", { name: /分镜制作/ })).toHaveAttribute(
    "aria-current",
    "step",
  );
  const sticky = await page.locator(".episode-sidebar-inner").boundingBox();
  expect(sticky!.y).toBe(76);
  await page.mouse.move(900, 500);
  await page.mouse.wheel(0, -600);
  await expect(
    nav.getByRole("button", { name: /分镜制作/ }),
  ).not.toHaveAttribute("aria-current", "step");
  await page.setViewportSize({ width: 1440, height: 1600 });
  await nav.getByRole("button", { name: /素材图片/ }).click();
  await expect(nav.getByRole("button", { name: /素材图片/ })).toHaveAttribute(
    "aria-current",
    "step",
  );
});
