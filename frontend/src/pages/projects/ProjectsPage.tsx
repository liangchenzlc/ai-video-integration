import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { flushSync } from "react-dom";
import { Button } from "antd";
import { Dialog } from "../../components/ui/Dialog";
import type {
  CreateProject,
  ProjectSession,
  RecentProject,
} from "../../../electron/shared/projects";
import { ProjectList } from "../../features/projects/ProjectList";
import { ProjectCreateForm } from "../../features/projects/ProjectCreateForm";
import { ProjectOverview } from "../../features/projects/ProjectOverview";
import { ProjectDetailHeader } from "../../features/projects/ProjectDetailHeader";
import {
  readEpisodes,
  type Episode,
} from "../../features/projects/project-detail-model";
import { EpisodePage } from "./EpisodePage";

export function ProjectsPage({
  ready,
  runtimeId,
  view,
  onEnter,
  onExit,
  onEpisode,
  onEpisodeBack,
}: {
  ready: boolean;
  runtimeId: string | null;
  view: "list" | "detail" | "episode";
  onEnter: () => void;
  onExit: () => void;
  onEpisode: () => void;
  onEpisodeBack: () => void;
}) {
  const [session, setSession] = useState<ProjectSession | null>(null);
  const [episode, setEpisode] = useState<Episode | null>(null);
  const [recent, setRecent] = useState<RecentProject[]>([]);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [aspect, setAspect] = useState<"16:9" | "9:16">("16:9");
  const [seconds, setSeconds] = useState("30");
  const [directory, setDirectory] = useState<{
    grantId: string;
    name: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const leavingRef = useRef(false);
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState<CreateProject | null>(null);
  const generation = useRef(runtimeId);
  generation.current = runtimeId;
  const locked = useRef(false);
  const sessionRef = useRef(session);
  sessionRef.current = session;
  useLayoutEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [view]);
  useEffect(
    () =>
      window.desktop.onBeforeLeave(
        async () => {
          leavingRef.current = true;
          flushSync(() => setLeaving(true));
          if (locked.current) {
            setMessage("请等待当前操作完成，再关闭窗口。");
            return false;
          }
          return true;
        },
        () => {
          leavingRef.current = false;
          flushSync(() => setLeaving(false));
        },
      ),
    [],
  );
  useEffect(() => {
    let active = true;
    setDirectory(null);
    if (ready) {
      void window.desktop.projects.recent().then((r) => {
        if (active && r.ok) setRecent(r.data);
      });
      void window.desktop.projects.current().then(async (r) => {
        if (!active || !r.ok) return;
        if (r.data) setSession(r.data);
        else if (sessionRef.current) {
          const recovered = await window.desktop.projects.openRecent({
            projectId: sessionRef.current.projectId,
          });
          if (active && recovered.ok) setSession(recovered.data);
          else if (active && !recovered.ok) setMessage(recovered.error.message);
        }
      });
    }
    return () => {
      active = false;
    };
  }, [ready, runtimeId]);
  async function action(work: () => Promise<void>) {
    if (locked.current || leavingRef.current || !ready) return;
    locked.current = true;
    flushSync(() => setBusy(true));
    setMessage("");
    try {
      await work();
    } catch {
      setMessage("操作未能完成，输入已保留，请恢复服务后查询原操作。");
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  async function refreshRecent() {
    const result = await window.desktop.projects.recent();
    if (result.ok) setRecent(result.data);
  }
  async function openRecent(projectId: string) {
    if (session?.projectId === projectId) {
      onEnter();
      return;
    }
    const started = generation.current;
    const opened = await window.desktop.projects.openRecent({ projectId });
    if (started !== generation.current) return;
    if (opened.ok) {
      setSession(opened.data);
      setEpisode(null);
      setCreating(false);
      await refreshRecent();
      onEnter();
    } else setMessage(opened.error.message);
  }
  async function choose() {
    const result = await window.desktop.projects.chooseDirectory({
      purpose: "createProject",
    });
    if (result.ok) {
      if (result.data) setDirectory(result.data);
    } else setMessage(result.error.message);
  }
  async function openDirectory() {
    const selected = await window.desktop.projects.chooseDirectory({
      purpose: "openProject",
    });
    if (!selected.ok) {
      setMessage(selected.error.message);
      return;
    }
    if (!selected.data) return;
    const result = await window.desktop.projects.open({
      directoryGrantId: selected.data.grantId,
      requestedMode: "write",
    });
    if (result.ok) {
      setSession(result.data);
      setEpisode(null);
      setCreating(false);
      await refreshRecent();
      onEnter();
    } else setMessage(result.error.message);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    await action(async () => {
      if (!directory && !pending) return;
      const command: CreateProject = pending ?? {
        clientOperationId: crypto.randomUUID(),
        expectedRevision: 0,
        payload: {
          directoryGrantId: directory!.grantId,
          name: name.trim(),
          aspect,
          resolution: "1080p",
          fps: { numerator: 24, denominator: 1 },
          targetMs: Math.round(Number(seconds) * 1000),
        },
      };
      setPending(command);
      const result = await window.desktop.projects.create(command);
      if (result.ok) {
        setPending(null);
        setDirectory(null);
        await refreshRecent();
        await openRecent(result.data.resourceId);
      } else {
        setMessage(result.error.message);
        if (
          [
            "GRANT_REJECTED",
            "REQUEST_INVALID",
            "VALIDATION_FAILED",
            "DIRECTORY_NOT_EMPTY",
            "UNSAFE_PROJECT_PATH",
          ].includes(result.error.code)
        )
          setPending(null);
      }
    });
  }
  async function query() {
    if (!pending) return;
    const result = await window.desktop.projects.operation({
      operationId: pending.clientOperationId,
    });
    if (result.ok) {
      setPending(null);
      await openRecent(result.data.receipt.resourceId);
    } else setMessage(result.error.message);
  }
  function returnToList() {
    setEpisode(null);
    onExit();
  }
  function returnToProject() {
    setEpisode(null);
    onEpisodeBack();
  }
  async function closeProject() {
    await action(async () => {
      const result = await window.desktop.projects.close();
      if (result.ok) {
        setSession(null);
        setEpisode(null);
        onExit();
      } else setMessage(result.error.message);
    });
  }
  return (
    <section
      className="projects-home"
      aria-labelledby={view === "list" ? "projects-title" : undefined}
    >
      {view === "detail" && session && (
        <ProjectDetailHeader
          session={session}
          onBack={returnToList}
          onClose={() => void closeProject()}
          canClose={ready && !busy && !leaving}
        />
      )}
      <div className="studio-page-head" hidden={view !== "list"}>
        <div>
          <h1 id="projects-title">项目管理</h1>
          <p>从一个项目开始，把故事做成完整的短剧。</p>
        </div>
      </div>
      {message && !creating && (
        <p className="notice" role="alert">
          {message}
        </p>
      )}
      {!ready && view === "list" && (
        <p role="status">等待本地服务恢复，项目文件仍保存在原目录。</p>
      )}
      <div hidden={view !== "detail"}>
        {session && (
          <ProjectOverview
            session={session}
            onOpenEpisode={(item) => {
              setEpisode(item);
              onEpisode();
            }}
          />
        )}
      </div>
      {view === "episode" && session && episode && (
        <EpisodePage
          key={`${session.projectId}:${episode.id}`}
          session={session}
          episode={episode}
          ready={ready}
          number={
            readEpisodes(session.projectId).findIndex(
              (item) => item.id === episode.id,
            ) + 1
          }
          onBack={returnToProject}
        />
      )}
      <div hidden={view !== "list"}>
        <div className="project-actions">
          <Button
            type="primary"
            disabled={busy || !ready || !!pending}
            onClick={() => setCreating(true)}
          >
            新建项目
          </Button>
          <Button
            disabled={busy || !ready || !!pending}
            onClick={() => void action(openDirectory)}
          >
            打开项目
          </Button>
        </div>
        <ProjectList
          recent={recent}
          disabled={busy || !ready || !!pending}
          onOpen={(id) => void action(() => openRecent(id))}
        />
      </div>
      {view === "list" && creating && (
        <Dialog
          title="新建项目"
          className="project-create-dialog"
          onClose={() => setCreating(false)}
          canClose={!busy && !pending}
        >
          {message && (
            <p className="notice project-create-notice" role="alert">
              {message}
            </p>
          )}
          <ProjectCreateForm
            busy={busy}
            ready={ready}
            pending={!!pending}
            directory={directory?.name ?? null}
            name={name}
            aspect={aspect}
            seconds={seconds}
            onName={setName}
            onAspect={setAspect}
            onSeconds={setSeconds}
            onChoose={() => void action(choose)}
            onQuery={() => void action(query)}
            onCancel={() => setCreating(false)}
            onSubmit={(event) => void submit(event)}
          />
        </Dialog>
      )}
    </section>
  );
}
