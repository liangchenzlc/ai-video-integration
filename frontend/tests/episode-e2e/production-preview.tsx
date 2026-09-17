import React from "react";
import { ConfigProvider } from "antd";
import { createRoot } from "react-dom/client";
import type { ProjectSession } from "../../electron/shared/projects";
import { EpisodePage } from "../../src/pages/projects/EpisodePage";
import {
  emptyWorkflow,
  saveWorkflow,
  readWorkflow,
} from "../../src/features/projects/episode-workflow";
import {
  sampleAssets,
  sampleImage,
} from "../../src/features/projects/episode-demo";
import "../../src/app/styles.css";
import "../../src/app/studio.css";

// Isolated renderer fixture: real page/state persistence, no desktop bridge or backend.
const projectId = "11111111-1111-4111-8111-111111111111";
const episodeId = "production-layout";
const query = new URLSearchParams(location.search);
if (!readWorkflow(projectId, episodeId, {}).scriptDraft) {
  const initial = emptyWorkflow({ aspect: "16:9", style: "写实" });
  initial.scriptDraft =
    "雨夜，林小雨带着旧铜手提灯走进旧城雨巷，在旧公寓门前停下。";
  initial.approvedScript = {
    text: initial.scriptDraft,
    aspect: initial.aspect,
    style: initial.style,
  };
  initial.reviews.source =
    initial.reviews.script =
    initial.reviews.assets =
      "confirmed";
  initial.assets = sampleAssets().map((asset) => ({
    ...asset,
    review: "confirmed",
    selectedImageId: "chosen",
    imageCandidates: [
      { id: "chosen", source: "demo", value: sampleImage(asset.id) },
    ],
  }));
  saveWorkflow(projectId, episodeId, initial);
}
const session: ProjectSession = {
  projectId,
  projectSessionId: "22222222-2222-4222-8222-222222222222",
  mode: query.has("readonly") ? "read" : "write",
  project: {
    id: projectId,
    name: "分镜布局测试",
    revision: 0,
    eventSequence: 0,
    formatVersion: 1,
    aspect: "16:9",
    resolution: "1080p",
    fps: { numerator: 24, denominator: 1 },
    targetMs: 6000,
    budgetMicroCny: 0,
    executionMode: "synthetic",
    savedAt: null,
    readOnly: query.has("readonly"),
  },
};
createRoot(document.getElementById("root")!).render(
  <ConfigProvider
    autoInsertSpaceInButton={false}
    theme={{
      token: {
        colorPrimary: "#1677ff",
        colorBgLayout: "#f5f8fc",
        colorBorder: "#d9e3ef",
        colorText: "#20334d",
        colorTextPlaceholder: "#586f8a",
        fontFamily: '"Microsoft YaHei UI", "Segoe UI", sans-serif',
      },
      components: {
        Button: {
          colorPrimary: "#0958d9",
          colorPrimaryHover: "#084ab4",
          colorPrimaryActive: "#003eb3",
        },
      },
    }}
  >
    <EpisodePage
      session={session}
      episode={{
        id: episodeId,
        title: "雨巷来客",
        synopsis: "分镜表格布局测试",
      }}
      number={1}
      ready={false}
      onBack={() => {}}
    />
  </ConfigProvider>,
);
