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
}: {
  ready: boolean;
  runtimeId: string | null;
  onSettings: () => void;
}) {
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
  const [draftReady, setDraftReady] = useState(false);
  const sessionRef = useRef(session);
  sessionRef.current = session;
  const onEngine = useCallback((engine: DraftAutosave | null) => {
    editor.current = engine;
    setDraftReady(!!engine);
  }, []);
  const advanceDraftRevision = useCallback(
    (expectedRevision: number, committedRevision: number) =>
      editor.current?.advanceProjectRevision(
        expectedRevision,
        committedRevision,
      ) ?? false,
    [],
  );
  const flush = useCallback(async () => {
    const saved = await (editor.current?.flush() ?? Promise.resolve(true));
    if (!saved) setMessage("草稿尚未保存，请处理保存提示后再切换或关闭项目。");
    return saved;
  }, []);
  const prepareMutation = useCallback(async () => {
    const saved = await prepareDraftMutation(editor.current);
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
        <StoryDraftEditor
          key={`draft:${session.projectId}`}
          session={session}
          ready={ready}
          locked={busy || leaving}
          onEngine={onEngine}
        />
      )}
      {session && (
        <RevisionPanel
          key={`versions:${session.projectId}`}
          session={session}
          ready={ready}
          locked={busy || leaving || !draftReady}
          action={action}
          prepareMutation={prepareMutation}
          advanceDraftRevision={advanceDraftRevision}
        />
      )}
      {session && (
        <MediaLibrary
          key={`media:${session.projectId}`}
          session={session}
          ready={ready}
          locked={busy || leaving || !draftReady}
          action={action}
          prepareMutation={prepareMutation}
        />
      )}
      {session && (
        <TaskPanel
          key={`tasks:${session.projectId}`}
          session={session}
          ready={ready}
          locked={busy || leaving || !draftReady}
          action={action}
          prepareMutation={prepareMutation}
          advanceDraftRevision={advanceDraftRevision}
          onSettings={onSettings}
        />
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
