import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { StoryPlanPreview } from "../../src/app/StoryPlanPreview";

const hash = "a".repeat(64);
function preview(source: Record<string, string | number>) {
  return renderToStaticMarkup(
    createElement(StoryPlanPreview, {
      input: {
        kind: "story",
        payload: {
          sourceText: "甲😀乙丙",
          sourceHash: hash,
          brief: "保留表情与人物反应",
          requirements: [{ text: "保留反应", source }],
        },
      },
    }),
  );
}

test("a matching source uses Unicode code points for the quoted excerpt", () => {
  const html = preview({
    sourceHash: hash,
    startCodePoint: 1,
    endCodePoint: 3,
  });
  expect(html).toContain("原文摘录：😀乙</blockquote>");
  expect(html).not.toContain("原文引用已变化或尚未完整，请核对");
  expect(html).not.toContain(hash);
});

const invalidSources: Record<string, string | number>[] = [
  { sourceHash: "b".repeat(64), startCodePoint: 1, endCodePoint: 3 },
  { sourceHash: hash, startCodePoint: 1, endCodePoint: 5 },
  { sourceHash: hash, startCodePoint: -1, endCodePoint: 3 },
  { sourceHash: hash, startCodePoint: 1.5, endCodePoint: 3 },
  { sourceHash: hash, startCodePoint: 1, endCodePoint: 1 },
  { startCodePoint: 1, endCodePoint: 3 },
];
test.each(invalidSources)(
  "a changed or incomplete source reference cannot create a false quotation: %j",
  (source) => {
    const html = preview(source);
    expect(html).toContain("原文引用已变化或尚未完整，请核对");
    expect(html).not.toContain("原文摘录：");
    expect(html).not.toContain("<blockquote");
  },
);

test("an image task shows its structured asset identity instead of raw JSON", () => {
  const html = renderToStaticMarkup(
    createElement(StoryPlanPreview, {
      input: {
        kind: "asset",
        payload: {
          assetType: "character",
          name: "门灯旅人",
          identityAnchors: ["深色雨衣", "旧帆布包"],
          allowedChanges: [],
          states: [],
          references: [],
        },
      },
    }),
  );
  expect(html).toContain("门灯旅人");
  expect(html).toContain("角色");
  expect(html).toContain("深色雨衣");
  expect(html).not.toContain("assetType");
});
