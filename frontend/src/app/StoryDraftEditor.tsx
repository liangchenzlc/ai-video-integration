import {
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import type { ProjectSession } from "../../electron/shared/projects";
import type { Draft } from "../../electron/shared/drafts";
import { DraftAutosave } from "./draft-autosave";
import { StoryStructure } from "./StoryStructure";

export function StoryDraftEditor({
  session,
  ready,
  locked,
  onEngine,
}: {
  session: ProjectSession;
  ready: boolean;
  locked: boolean;
  onEngine: (engine: DraftAutosave | null) => void;
}) {
  const [engine, setEngine] = useState<DraftAutosave | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    let instance: DraftAutosave | null = null;
    const bridge = window.desktop.projects.drafts;
    void (async () => {
      try {
        const project = await bridge.project({ projectId: session.projectId });
        const list = await window.desktop.storyboard.list({
          projectId: session.projectId,
        });
        if (!project.ok || !list.ok) throw new Error("load");
        const summary = list.data.drafts.find((d) => d.kind === "story");
        let draft: Draft = {
          id: crypto.randomUUID(),
          artifactId: crypto.randomUUID(),
          baseRevisionId: null,
          content: {
            kind: "story",
            content: { sourceText: "", inputType: "idea", brief: "" },
          },
        };
        if (summary) {
          const loaded = await bridge.get({
            projectId: session.projectId,
            draftId: summary.id,
          });
          if (!loaded.ok) throw new Error("load");
          draft = loaded.data;
        }
        if (!active) return;
        instance = new DraftAutosave(
          bridge,
          session.projectId,
          draft,
          project.data.revision,
          summary?.savedAt ?? null,
        );
        setEngine(instance);
        setError("");
        onEngine(instance);
      } catch {
        if (active)
          setError("草稿未能载入。恢复连接后重试，已有内容不会被覆盖。");
      }
    })();
    return () => {
      active = false;
      instance?.dispose();
      onEngine(null);
    };
  }, [session.projectId, attempt, onEngine]);
  useEffect(() => {
    engine?.setPaused(!ready || session.mode === "read");
  }, [engine, ready, session.mode]);
  return (
    <section className="story-draft" aria-label="故事草稿">
      <div className="section-heading">
        <h2>故事草稿</h2>
        <span>随时记下想法，空白也能保存</span>
      </div>
      {error && (
        <p role="alert">
          {error}{" "}
          <button
            disabled={!ready || locked}
            onClick={() => {
              setError("");
              setAttempt((a) => a + 1);
            }}
          >
            重新载入草稿
          </button>
        </p>
      )}
      {!engine && !error && <p role="status">正在读取草稿…</p>}
      {engine && (
        <Editor
          engine={engine}
          projectId={session.projectId}
          ready={ready}
          readOnly={session.mode === "read" || locked}
        />
      )}
    </section>
  );
}

function Editor({
  engine,
  projectId,
  ready,
  readOnly,
}: {
  engine: DraftAutosave;
  projectId: string;
  ready: boolean;
  readOnly: boolean;
}) {
  const state = useSyncExternalStore(engine.subscribe, () => engine.snapshot);
  const sourceId = useId();
  const briefId = useId();
  const sourceField = useRef<HTMLTextAreaElement>(null);
  const text =
    typeof state.content.sourceText === "string"
      ? state.content.sourceText
      : "";
  const brief =
    typeof state.content.brief === "string" ? state.content.brief : "";
  const status = {
    saved: state.savedAt
      ? `已保存 · ${new Date(state.savedAt).toLocaleTimeString("zh-CN")}`
      : "当前没有待保存修改",
    dirty: "有修改待保存",
    saving: "正在保存…",
    unknown: "保存结果待核对",
    error: "尚未保存",
    conflict: "需要处理版本冲突",
  }[state.status];
  const update = (values: Record<string, string>) => {
    if (!readOnly) engine.edit({ ...state.content, ...values });
  };
  return (
    <>
      <div className="draft-toolbar">
        <label>
          内容入口
          <select
            disabled={readOnly}
            value={
              typeof state.content.inputType === "string"
                ? state.content.inputType
                : "idea"
            }
            onChange={(e) => update({ inputType: e.target.value })}
          >
            <option value="idea">一个想法</option>
            <option value="excerpt">小说片段</option>
            <option value="script">已有剧本</option>
          </select>
        </label>
        <p role="status" data-testid="draft-save-status">
          {status}
        </p>
      </div>
      {!ready && (
        <p className="notice">
          连接中断，仍可继续编辑。请保留窗口，恢复连接后保存。
        </p>
      )}
      <div className="draft-field">
        <label htmlFor={sourceId}>故事原文</label>
        <textarea
          id={sourceId}
          ref={sourceField}
          value={text}
          readOnly={readOnly}
          rows={10}
          onChange={(e) => update({ sourceText: e.target.value })}
          placeholder="写下人物、处境，或粘贴已有的故事。未完成也可以保存。"
        />
      </div>
      <p className="muted">
        {Array.from(text).length.toLocaleString("zh-CN")} / 100,000 字符 ·
        停止输入 0.8 秒后自动保存
      </p>
      <div className="draft-field">
        <label htmlFor={briefId}>创作简报（可稍后补充）</label>
        <textarea
          id={briefId}
          value={brief}
          readOnly={readOnly}
          rows={3}
          onChange={(e) => update({ brief: e.target.value })}
          placeholder="希望观众看到什么？风格、重点或限制是什么？"
        />
      </div>
      <StoryStructure
        content={state.content}
        sourceField={sourceField}
        readOnly={readOnly}
        projectId={projectId}
        onEdit={(content) => engine.edit(content)}
      />
      {state.message && (
        <p role="alert" className="notice">
          {state.message}
        </p>
      )}
      {state.status === "conflict" && (
        <div className="draft-conflict">
          <h3>已保存的原文</h3>
          <pre>
            {typeof state.remote?.sourceText === "string"
              ? state.remote.sourceText || "（空白）"
              : "正在核对已保存内容"}
          </pre>
          <h3>已保存的简报</h3>
          <pre>
            {typeof state.remote?.brief === "string"
              ? state.remote.brief || "（空白）"
              : "（未填写）"}
          </pre>
          <p>上方编辑框保留你的输入。选择后才会继续保存。</p>
          <button
            disabled={!ready || readOnly}
            onClick={() => void engine.resolveConflict("local")}
          >
            保留我的内容并保存
          </button>
          <button
            disabled={!ready || readOnly || !state.remote}
            onClick={() => void engine.resolveConflict("saved")}
          >
            使用已保存的内容
          </button>
        </div>
      )}
      <button
        disabled={
          !ready ||
          readOnly ||
          state.status === "saving" ||
          state.status === "conflict"
        }
        onClick={() => void engine.flush()}
      >
        {state.status === "unknown" ? "核对并继续保存" : "立即保存"}
      </button>
      <p className="muted">
        草稿保存不会采用或确认内容。开始生成前会检查完整性。
      </p>
    </>
  );
}
