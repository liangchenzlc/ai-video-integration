import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { StoryDraftEditor } from "./StoryDraftEditor";
import { MediaLibrary } from "./MediaLibrary";
import { TaskPanel } from "./TaskPanel";
import { RevisionPanel } from "./RevisionPanel";
import { ContentWorkbench } from "./ContentWorkbench";
import { ProductionWorkbench } from "./ProductionWorkbench";
import type { Revision } from "../../electron/shared/versions";
import { flushSync } from "react-dom";
import type { DraftAutosave } from "./draft-autosave";
import type {
  CreateProject,
  ProjectSession,
  RecentProject,
} from "../../electron/shared/projects";

export async function prepareDraftMutation(
  engine: Pick<DraftAutosave, "flush"> | null,
): Promise<boolean> {
  return engine ? engine.flush() : false;
}

export function ProjectsHome({
  ready,
  runtimeId,
  onSettings,
  onPage,
  page,
}: {
  ready: boolean;
  runtimeId: string | null;
  onSettings: () => void;
  onPage: (page: string) => void;
  page: string;
}) {
  const [candidateFocus, setCandidateFocus] = useState<
    | { projectId: string; revision: Revision }
    | { projectId: string; artifactId: string }
    | null
  >(null);
  const [session, setSession] = useState<ProjectSession | null>(null);
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
  const editor = useRef<DraftAutosave | null>(null);
  const contentEditor = useRef<DraftAutosave | null>(null);
  const productionEditor = useRef<DraftAutosave | null>(null);
  const [storyEngine, setStoryEngine] = useState<DraftAutosave | null>(null);
  const onContentEngine = useCallback((instance: DraftAutosave | null) => {
    contentEditor.current = instance;
  }, []);
  const onProductionEngine = useCallback((instance: DraftAutosave | null) => {
    productionEditor.current = instance;
  }, []);
  const [draftReady, setDraftReady] = useState(false);
  const sessionRef = useRef(session);
  sessionRef.current = session;
  const onEngine = useCallback((engine: DraftAutosave | null) => {
    editor.current = engine;
    if (engine)
      engine.onCommit = (before, after) => {
        contentEditor.current?.advanceProjectRevision(before, after);
        productionEditor.current?.advanceProjectRevision(before, after);
        window.dispatchEvent(new Event("storyboard-updated"));
      };
    setStoryEngine(engine);
    setDraftReady(!!engine);
  }, []);
  const advanceDraftRevision = useCallback(
    (expectedRevision: number, committedRevision: number) => {
      contentEditor.current?.advanceProjectRevision(
        expectedRevision,
        committedRevision,
      );
      productionEditor.current?.advanceProjectRevision(
        expectedRevision,
        committedRevision,
      );
      return (
        editor.current?.advanceProjectRevision(
          expectedRevision,
          committedRevision,
        ) ?? false
      );
    },
    [],
  );
  const flush = useCallback(async () => {
    const storySaved = await (editor.current?.flush() ?? Promise.resolve(true));
    const contentSaved =
      storySaved &&
      (await (contentEditor.current?.flush() ?? Promise.resolve(true)));
    const saved =
      contentSaved &&
      (await (productionEditor.current?.flush() ?? Promise.resolve(true)));
    if (!saved) setMessage("草稿尚未保存，请处理保存提示后再切换或关闭项目。");
    return saved;
  }, []);
  const prepareMutation = useCallback(async () => {
    const saved =
      (await prepareDraftMutation(editor.current)) &&
      (await (contentEditor.current?.flush() ?? Promise.resolve(true))) &&
      (await (productionEditor.current?.flush() ?? Promise.resolve(true)));
    if (!saved)
      setMessage("草稿仍在读取或尚未保存，请等待草稿准备完成后再操作项目。");
    return saved;
  }, []);
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
          return flush();
        },
        () => {
          leavingRef.current = false;
          flushSync(() => setLeaving(false));
        },
      ),
    [flush],
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
  useEffect(() => {
    if (page !== "故事" || !session || !ready) return;
    let active = true;
    const focusStory = () => {
      void window.desktop.storyboard
        .list({ projectId: session.projectId })
        .then((result) => {
          if (!active || !result.ok) return;
          const story = result.data.drafts.find(
            (item) => item.kind === "story",
          );
          setCandidateFocus(
            story
              ? { projectId: session.projectId, artifactId: story.artifactId }
              : null,
          );
        });
    };
    // An unsaved story can become the first persisted artifact while this page stays mounted.
    setCandidateFocus(null);
    focusStory();
    window.addEventListener("storyboard-updated", focusStory);
    return () => {
      active = false;
      window.removeEventListener("storyboard-updated", focusStory);
    };
  }, [page, ready, session]);
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
    if (!(await flush())) return;
    const started = generation.current;
    const opened = await window.desktop.projects.openRecent({ projectId });
    if (started !== generation.current) return;
    if (opened.ok) {
      setSession(opened.data);
      setCreating(false);
      await refreshRecent();
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
    if (!(await flush())) return;
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
      setCreating(false);
      await refreshRecent();
    } else setMessage(result.error.message);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    await action(async () => {
      if (!directory && !pending) return;
      if (!(await flush())) return;
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
  return (
    <section className="projects-home" aria-labelledby="projects-title">
      <div className="section-heading">
        <h2 id="projects-title">本地项目</h2>
        <span>无需配置模型，即可开始准备</span>
      </div>
      {message && (
        <p className="notice" role="alert">
          {message}
        </p>
      )}
      {!ready && (
        <p role="status">等待本地服务恢复，项目文件仍保存在原目录。</p>
      )}
      {session && (
        <section className="project-summary" aria-label="当前项目">
          <div>
            <h3>{session.project.name}</h3>
            <p>
              {session.project.aspect} · {session.project.resolution} ·{" "}
              {session.project.fps.numerator} 帧/秒 · 目标{" "}
              {session.project.targetMs / 1000} 秒
            </p>
            <p>
              {session.mode === "read"
                ? "只读模式：项目正在其他会话中使用。"
                : "项目已打开，可以继续准备内容。"}
            </p>
            <p className="muted">原文与简报会自动保存在这个项目中。</p>
          </div>
          <button
            disabled={busy || !ready}
            onClick={() =>
              void action(async () => {
                if (!(await flush())) return;
                const r = await window.desktop.projects.close();
                if (r.ok) setSession(null);
                else setMessage(r.error.message);
              })
            }
          >
            关闭项目
          </button>
        </section>
      )}
      {session && (
        <div hidden={page !== "故事" && page !== "项目工具" && page !== "首页"}>
          <StoryDraftEditor
            key={`draft:${session.projectId}`}
            session={session}
            ready={ready}
            locked={busy || leaving}
            onEngine={onEngine}
          />
        </div>
      )}
      {session && (
        <div hidden={page !== "视觉与分镜" && page !== "项目工具"}>
          <ContentWorkbench
            key={`content:${session.projectId}`}
            session={session}
            ready={ready}
            locked={busy || leaving || !draftReady}
            action={action}
            storyEngine={storyEngine}
            onEngine={onContentEngine}
            onFocusArtifact={(artifactId) => {
              setCandidateFocus({ projectId: session.projectId, artifactId });
              requestAnimationFrame(() =>
                document
                  .querySelector(".revision-panel")
                  ?.scrollIntoView({ behavior: "smooth", block: "start" }),
              );
            }}
          />
        </div>
      )}
      {session && (
        <div
          hidden={
            !["镜头制作", "声音与剪辑", "检查与导出", "项目工具"].includes(page)
          }
        >
          <ProductionWorkbench
            key={`production:${session.projectId}`}
            session={session}
            ready={ready}
            active={[
              "镜头制作",
              "声音与剪辑",
              "检查与导出",
              "项目工具",
            ].includes(page)}
            page={page}
            locked={busy || leaving || !draftReady}
            action={action}
            onEngine={onProductionEngine}
            storyEngine={storyEngine}
            contentEngine={contentEditor.current}
            onFocusArtifact={(artifactId) => {
              setCandidateFocus({ projectId: session.projectId, artifactId });
              requestAnimationFrame(() =>
                document
                  .querySelector(".revision-panel")
                  ?.scrollIntoView({ behavior: "smooth", block: "start" }),
              );
            }}
            onOpenMedia={() => {
              onPage("项目工具");
              requestAnimationFrame(() =>
                document
                  .querySelector(".media-library")
                  ?.scrollIntoView({ behavior: "smooth", block: "start" }),
              );
            }}
          />
        </div>
      )}
      {session && (
        <div
          hidden={
            page !== "项目工具" &&
            page !== "故事" &&
            page !== "视觉与分镜" &&
            page !== "镜头制作" &&
            page !== "声音与剪辑" &&
            page !== "检查与导出"
          }
        >
          <RevisionPanel
            key={`versions:${session.projectId}`}
            session={session}
            ready={ready}
            locked={busy || leaving || !draftReady}
            action={action}
            prepareMutation={prepareMutation}
            advanceDraftRevision={advanceDraftRevision}
            focusRevision={
              candidateFocus?.projectId === session.projectId &&
              "revision" in candidateFocus
                ? candidateFocus.revision
                : null
            }
            focusArtifactId={
              candidateFocus?.projectId === session.projectId &&
              "artifactId" in candidateFocus
                ? candidateFocus.artifactId
                : null
            }
            storyWorkspace={page === "故事"}
          />
        </div>
      )}
      {session && (
        <div hidden={page !== "项目工具"}>
          <MediaLibrary
            key={`media:${session.projectId}`}
            session={session}
            ready={ready}
            locked={busy || leaving || !draftReady}
            action={action}
            prepareMutation={prepareMutation}
          />
        </div>
      )}
      {session && (
        <div hidden={page !== "项目工具"}>
          <TaskPanel
            key={`tasks:${session.projectId}`}
            session={session}
            ready={ready}
            locked={busy || leaving || !draftReady}
            action={action}
            prepareMutation={prepareMutation}
            advanceDraftRevision={advanceDraftRevision}
            onSettings={onSettings}
            onCompareCandidate={(revision) => {
              setCandidateFocus({ projectId: session.projectId, revision });
              requestAnimationFrame(() =>
                document
                  .querySelector(".revision-panel")
                  ?.scrollIntoView({ behavior: "smooth", block: "start" }),
              );
            }}
          />
        </div>
      )}
      <div className="project-actions">
        <button
          className="primary-button"
          disabled={busy || !ready || !!pending}
          onClick={() => setCreating(true)}
        >
          新建项目
        </button>
        <button
          disabled={busy || !ready || !!pending}
          onClick={() => void action(openDirectory)}
        >
          打开项目
        </button>
      </div>
      {!session &&
        ["故事", "视觉与分镜", "镜头制作", "声音与剪辑", "检查与导出"].includes(
          page,
        ) && (
          <p className="notice">
            先创建或打开一个本地项目，再整理故事、视觉资产与分镜。
          </p>
        )}
      {creating && (
        <form className="project-form" onSubmit={(e) => void submit(e)}>
          <h3>创建你的项目</h3>
          <fieldset disabled={busy || !ready || !!pending}>
            <label>
              项目名称
              <input
                autoFocus
                maxLength={120}
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="例如：雨夜借光"
              />
            </label>
            <div className="form-row">
              <label>
                画幅
                <select
                  value={aspect}
                  onChange={(e) => setAspect(e.target.value as "16:9" | "9:16")}
                >
                  <option value="16:9">横屏 16:9</option>
                  <option value="9:16">竖屏 9:16</option>
                </select>
              </label>
              <label>
                目标时长（秒）
                <input
                  type="number"
                  min="1"
                  step="1"
                  required
                  value={seconds}
                  onChange={(e) => setSeconds(e.target.value)}
                />
              </label>
            </div>
            <p>输出设置：1080p · 24 帧/秒</p>
            <div className="directory-choice">
              <button type="button" onClick={() => void action(choose)}>
                选择空目录
              </button>
              <span>{directory?.name ?? "尚未选择目录"}</span>
            </div>
            <p className="muted">
              项目保存在你选择的本机目录，请避开网盘同步文件夹。
            </p>
          </fieldset>
          {pending && (
            <p role="status">
              正在核对这次新建的结果。重试沿用原操作，不会另建一个项目。
            </p>
          )}
          <div className="project-actions">
            <button
              className="primary-button"
              type="submit"
              disabled={busy || !ready || (!directory && !pending)}
            >
              {busy ? "请稍候…" : pending ? "重试原操作" : "创建项目"}
            </button>
            {pending ? (
              <button
                type="button"
                disabled={busy || !ready}
                onClick={() => void action(query)}
              >
                查询原操作
              </button>
            ) : (
              <button
                type="button"
                disabled={busy}
                onClick={() => setCreating(false)}
              >
                取消
              </button>
            )}
          </div>
        </form>
      )}
      <section className="recent-projects" aria-label="最近项目">
        <h3>最近打开</h3>
        {recent.length ? (
          <ul>
            {recent.map((p) => (
              <li key={p.projectId}>
                <button
                  disabled={busy || !ready || !!pending}
                  onClick={() => void action(() => openRecent(p.projectId))}
                >
                  {p.name}
                </button>
                <span>
                  {new Date(p.lastOpenedAt).toLocaleDateString("zh-CN")}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">
            还没有最近项目。创建一个新项目，或打开已有项目目录。
          </p>
        )}
        <p className="muted">目录移动后，请通过“打开项目”重新选择。</p>
      </section>
    </section>
  );
}
