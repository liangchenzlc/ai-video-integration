import type { RecentProject } from "../../../electron/shared/projects";
import { ProjectCard } from "./ProjectCard";

export function ProjectList({
  recent,
  disabled,
  onOpen,
}: {
  recent: RecentProject[];
  disabled: boolean;
  onOpen: (id: string) => void;
}) {
  return (
    <section className="recent-projects" aria-label="最近项目">
      <h2>最近打开</h2>
      {recent.length ? (
        <div className="studio-project-grid">
          {recent.map((project) => (
            <ProjectCard
              key={project.projectId}
              project={project}
              disabled={disabled}
              onOpen={onOpen}
            />
          ))}
        </div>
      ) : (
        <div className="studio-empty">
          <h3>还没有最近项目</h3>
          <p>新建一个项目，或打开已有的项目目录。</p>
        </div>
      )}
      <p className="muted">目录移动后，请通过“打开项目”重新选择。</p>
    </section>
  );
}
