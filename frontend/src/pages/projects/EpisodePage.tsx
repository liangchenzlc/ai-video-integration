import { useEffect, useRef, useState, type ComponentProps } from "react";
import { Button } from "antd";
import type { ProjectSession } from "../../../electron/shared/projects";
import type { Episode } from "../../features/projects/project-detail-model";
import {
  readWorkflow,
  saveWorkflow,
  nearestPendingStage,
  type EpisodeWorkflow,
  type StageId,
} from "../../features/projects/episode-workflow";
import { activeStepIndex } from "./episode-scroll";
import { episodeStages, StageNav } from "./episode/StageNav";
import { SourceStage } from "./episode/SourceStage";
import { ScriptStage } from "./episode/ScriptStage";
import { AssetsStage } from "./episode/AssetsStage";
import { StoryboardStage } from "./episode/StoryboardStage";
import { VideoStage } from "./episode/VideoStage";
import {
  listUsableMedia,
  type ListedMedia,
} from "../../features/projects/episode-media";

export function EpisodePage(props: ComponentProps<typeof EpisodeWorkspace>) {
  return (
    <EpisodeWorkspace
      key={`${props.session.projectSessionId}:${props.session.projectId}:${props.episode.id}:${props.session.mode}`}
      {...props}
    />
  );
}

function EpisodeWorkspace({
  session,
  episode,
  number,
  ready,
  onBack,
}: {
  session: ProjectSession;
  episode: Episode;
  number: number;
  ready: boolean;
  onBack: () => void;
}) {
  const defaults = { aspect: session.project.aspect };
  const [value, setValue] = useState(() =>
    readWorkflow(session.projectId, episode.id, defaults),
  );
  const [step, setStep] = useState<StageId>(() => nearestPendingStage(value));
  const latest = useRef(value);
  latest.current = value;
  const [images, setImages] = useState<readonly ListedMedia[]>([]);
  const [saveMessage, setSaveMessage] = useState("尚未修改");
  const [saveError, setSaveError] = useState("");
  const readOnly = session.mode === "read";

  useEffect(() => {
    const restored = readWorkflow(session.projectId, episode.id, defaults);
    latest.current = restored;
    setValue(restored);
    setStep(nearestPendingStage(restored));
    const frame = requestAnimationFrame(() =>
      document
        .getElementById(`episode-stage-${nearestPendingStage(restored)}`)
        ?.scrollIntoView({ behavior: "auto", block: "start" }),
    );
    setSaveMessage("尚未修改");
    setSaveError("");
    return () => cancelAnimationFrame(frame);
  }, [session.projectId, episode.id, session.project.aspect]);

  useEffect(() => {
    let active = true;
    if (!ready) {
      setImages([]);
      return;
    }
    void listUsableMedia(session.projectId, "image/").then((items) => {
      if (active) setImages(items);
    });
    return () => {
      active = false;
    };
  }, [session.projectId, ready, value.assets, value.shots]);

  useEffect(() => {
    const sections = episodeStages.map(({ id }) =>
      document.getElementById(`episode-stage-${id}`),
    );
    let frame = 0;
    const updateStep = () => {
      frame = 0;
      const tops = sections.map(
        (section) =>
          section?.getBoundingClientRect().top ?? Number.POSITIVE_INFINITY,
      );
      const atBottom =
        window.scrollY > 0 &&
        window.scrollY + window.innerHeight >=
          document.documentElement.scrollHeight - 2;
      const headerBottom =
        document.querySelector(".episode-top")?.getBoundingClientRect()
          .bottom ?? 0;
      const navBottom = window.matchMedia("(max-width: 680px)").matches
        ? (document.querySelector(".episode-sidebar")?.getBoundingClientRect()
            .bottom ?? headerBottom)
        : headerBottom;
      setStep(
        episodeStages[
          activeStepIndex(
            tops,
            Math.max(headerBottom, navBottom) + 24,
            atBottom,
          )
        ].id,
      );
    };
    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(updateStep);
    };
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    const content = document.querySelector(".episode-content");
    const observer = new ResizeObserver(schedule);
    if (content) observer.observe(content);
    schedule();
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      observer.disconnect();
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [session.projectId, episode.id]);

  function goToStep(next: StageId) {
    document.getElementById(`episode-stage-${next}`)?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
      block: "start",
    });
  }

  function update(
    change: EpisodeWorkflow | ((current: EpisodeWorkflow) => EpisodeWorkflow),
  ) {
    if (readOnly) return;
    const next = typeof change === "function" ? change(latest.current) : change;
    latest.current = next;
    setValue(next);
    const result = saveWorkflow(session.projectId, episode.id, next);
    if (result.ok) {
      setSaveError("");
      setSaveMessage("已保存");
    } else {
      setSaveMessage("未保存");
      setSaveError(result.error);
    }
  }

  return (
    <div className="episode-page">
      <header className="episode-top">
        <Button type="link" className="detail-back" onClick={onBack}>
          ← 返回项目详情
        </Button>
        <div>
          <span>
            {session.project.name} · 第 {number} 集
          </span>
          <h1>{episode.title}</h1>
        </div>
        <span className="episode-top-status">本集制作</span>
      </header>
      <div className="episode-demo-banner" role="note">
        <span>交互演示：不会调用 AI，也不会产生模型费用。</span>
        <span
          className={saveError ? "episode-save-error" : "episode-save-status"}
          role={saveError ? "alert" : "status"}
        >
          {saveError || saveMessage}
        </span>
      </div>
      {readOnly && (
        <p className="episode-readonly-notice">
          项目以只读方式打开，可查看本集内容，无法修改。
        </p>
      )}
      {!ready && (
        <p className="episode-readonly-notice">
          本地服务尚未就绪；媒体相关操作不可用。
        </p>
      )}
      <div className="episode-layout">
        <aside className="episode-sidebar">
          <p>制作流程</p>
          <StageNav
            active={step}
            reviews={value.reviews}
            value={value}
            onSelect={goToStep}
          />
        </aside>
        <div className="episode-content">
          <section
            id="episode-stage-source"
            data-testid="episode-stage-source"
            className="episode-stage"
            aria-label="小说与剧本生成"
          >
            <SourceStage value={value} readOnly={readOnly} onChange={update} />
          </section>
          <section
            id="episode-stage-script"
            data-testid="episode-stage-script"
            className="episode-stage"
            aria-label="剧本确认与素材拆解"
          >
            <ScriptStage
              value={value}
              readOnly={readOnly}
              onChange={update}
              projectAspect={session.project.aspect}
            />
          </section>
          <section
            id="episode-stage-assets"
            data-testid="episode-stage-assets"
            className="episode-stage"
            aria-label="素材图片"
          >
            <AssetsStage
              value={value}
              readOnly={readOnly}
              ready={ready}
              projectId={session.projectId}
              onChange={update}
              onApply={update}
            />
          </section>
          <section
            id="episode-stage-storyboard"
            data-testid="episode-stage-storyboard"
            className="episode-stage"
            aria-label="分镜脚本与分镜图"
          >
            <StoryboardStage
              value={value}
              readOnly={readOnly}
              onChange={update}
              projectId={session.projectId}
              mediaItems={images}
            />
          </section>
          <section
            id="episode-stage-video"
            data-testid="episode-stage-video"
            className="episode-stage"
            aria-label="分镜视频"
          >
            <VideoStage
              value={value}
              readOnly={readOnly}
              ready={ready}
              projectId={session.projectId}
              onChange={update}
              onApply={update}
            />
          </section>
        </div>
      </div>
    </div>
  );
}
