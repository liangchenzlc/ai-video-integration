import React from "react";
import type {
  EpisodeWorkflow,
  Review,
  StageId,
} from "../../../features/projects/episode-workflow";
import {
  stageStatus,
  pendingCount,
} from "../../../features/projects/episode-workflow";

export const episodeStages: { id: StageId; label: string }[] = [
  { id: "source", label: "小说与剧本生成" },
  { id: "script", label: "剧本确认与素材拆解" },
  { id: "assets", label: "素材图片" },
  { id: "storyboard", label: "分镜脚本与分镜图" },
  { id: "video", label: "分镜视频" },
];

const reviewLabels: Record<Review, string> = {
  not_started: "未开始",
  review: "待核对",
  confirmed: "已确认",
  stale: "需复核",
};

export function StageNav({
  active,
  reviews,
  onSelect,
  value,
}: {
  active: StageId;
  reviews: EpisodeWorkflow["reviews"];
  onSelect: (id: StageId) => void;
  value?: EpisodeWorkflow;
}) {
  return (
    <nav aria-label="分集制作流程">
      {episodeStages.map(({ id, label }, index) => (
        <button
          key={id}
          type="button"
          className={`episode-stage-link${active === id ? " active" : ""}`}
          aria-current={active === id ? "step" : undefined}
          onClick={() => onSelect(id)}
        >
          <span>{String(index + 1).padStart(2, "0")}</span>
          <span className="episode-stage-name">{label}</span>
          <small>
            {reviewLabels[value ? stageStatus(value, id) : reviews[id]]}
            {value &&
              pendingCount(value, id) > 0 &&
              ` · ${pendingCount(value, id)} 项待处理`}
          </small>
        </button>
      ))}
    </nav>
  );
}
