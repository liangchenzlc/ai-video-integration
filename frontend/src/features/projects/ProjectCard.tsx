import type { RecentProject } from "../../../electron/shared/projects";
import { Card } from "antd";

export function ProjectCard({
  project,
  onOpen,
  disabled,
}: {
  project: RecentProject;
  onOpen: (id: string) => void;
  disabled: boolean;
}) {
  const date = new Date(project.lastOpenedAt);
  return (
    <Card className="studio-project-card" hoverable>
      <button
        className="project-card-open"
        type="button"
        disabled={disabled}
        onClick={() => onOpen(project.projectId)}
        aria-label={`打开项目 ${project.name}`}
      >
        <span className="project-card-art" aria-hidden="true">
          <span className="project-card-frame" />
        </span>
        <span className="project-card-body">
          <strong>{project.name}</strong>
          <span>本地短剧项目</span>
          <small>
            最近打开{" "}
            {Number.isNaN(date.getTime())
              ? "未知"
              : date.toLocaleDateString("zh-CN")}
          </small>
        </span>
      </button>
    </Card>
  );
}
