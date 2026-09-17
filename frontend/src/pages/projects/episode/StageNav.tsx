import React from "react";
import type { StageId } from "../../../features/projects/episode-workflow";

export const episodeStages: { id: StageId; label: string }[] = [
  { id: "source", label: "小说与剧本生成" },
  { id: "script", label: "剧本确认与素材拆解" },
  { id: "assets", label: "素材图片" },
  { id: "storyboard", label: "分镜制作" },
];

// Older drafts still have a separate video review stage.
export function visibleEpisodeStage(id: StageId): StageId {
  return id === "video" ? "storyboard" : id;
}

export function StageNav({
  active,
  onSelect,
}: {
  active: StageId;
  onSelect: (id: StageId) => void;
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
        </button>
      ))}
    </nav>
  );
}
