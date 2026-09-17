import type {
  AssetItem,
  Candidate,
  MediaRef,
  ShotItem,
} from "./episode-workflow";

export const DEMO_MODELS = {
  script: ["A", "B"].map((x) => ({
    value: `demo-script-${x}`,
    label: `演示·剧本模型 ${x}`,
  })),
  analysis: ["A", "B"].map((x) => ({
    value: `demo-analysis-${x}`,
    label: `演示·素材分析模型 ${x}`,
  })),
  assetImage: ["A", "B"].map((x) => ({
    value: `demo-image-${x}`,
    label: `演示·文生图模型 ${x}`,
  })),
  storyboardText: ["A", "B"].map((x) => ({
    value: `demo-storyboard-${x}`,
    label: `演示·分镜模型 ${x}`,
  })),
  storyboardImage: ["A", "B"].map((x) => ({
    value: `demo-frame-${x}`,
    label: `演示·分镜图模型 ${x}`,
  })),
  video: ["A", "B"].map((x) => ({
    value: `demo-video-${x}`,
    label: `演示·图生视频模型 ${x}`,
  })),
} as const;

const stableId = (value: string) => {
  let hash = 5381;
  for (const character of value) hash = (hash * 33) ^ character.codePointAt(0)!;
  return (hash >>> 0).toString(36);
};

export function sampleScript(novel: string): Candidate<string> | null {
  const excerpt = novel.trim().slice(0, 48);
  if (!excerpt) return null;

  return {
    id: `demo-script-${stableId(excerpt)}`,
    source: "demo",
    value: `演示剧本草稿（请编辑并确认）\n\n来源片段：「${excerpt}」\n\n场次 1：人物在场景中遇到一个需要自行补全的转折。\n动作：请依据原文补写动作与对白。`,
  };
}

export function sampleAssets(): AssetItem[] {
  return [
    ["character", "角色 A", "演示占位角色；请按原文更正名称、外观与关系。"],
    ["scene", "场景 A", "演示占位场景；请按原文更正地点、时间与氛围。"],
    ["prop", "道具 A", "演示占位道具；请按原文更正用途与细节。"],
  ].map(([kind, name, description], index) => ({
    id: `demo-asset-${index + 1}`,
    kind: kind as AssetItem["kind"],
    name,
    description,
    linkedResourceId: null,
    imageCandidates: [],
    selectedImageId: null,
    review: "review" as const,
  }));
}

export function sampleShots(script: string): ShotItem[] {
  const basis = script.trim() || "empty-script";
  const fixtureId = stableId(basis);
  return [
    ["建立场景", "展示演示场景与人物位置。", "人物进入画面。", ""],
    [
      "转折动作",
      "展示需要人工校对的动作转折。",
      "人物停下并观察。",
      "请按剧本补写对白。",
    ],
    ["收束镜头", "展示演示结尾构图。", "人物离开画面。", ""],
  ].map(([title, description, action, dialogue], index) => ({
    id: `demo-shot-${fixtureId}-${index + 1}`,
    title: `演示·${title}`,
    description,
    action,
    dialogue,
    plannedMs: 3000,
    assetIds: [],
    review: "review" as const,
    firstFrames: [],
    selectedFirstId: null,
    endFrames: [],
    selectedEndId: null,
    videos: [],
    selectedVideoId: null,
    frameReview: "not_started" as const,
    videoReview: "not_started" as const,
  }));
}

export function sampleImage(seed: string): MediaRef {
  return { kind: "demo-image", id: `demo-image-${stableId(seed)}` };
}

export function sampleMotion(shotId: string): MediaRef {
  return { kind: "demo-motion", id: `demo-motion-${stableId(shotId)}` };
}
