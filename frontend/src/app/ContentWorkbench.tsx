import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import type { ProjectSession } from "../../electron/shared/projects";
import type { Draft } from "../../electron/shared/drafts";
import type { Media } from "../../electron/shared/media";
import { DraftAutosave } from "./draft-autosave";
import { ContentFields } from "./ContentFields";
import { entries, uuid, value } from "./storyboard-fields";

type Summary = {
  id: string;
  artifactId: string;
  kind: string;
  savedAt: string;
};
type Index = { drafts: Summary[]; shotIds: string[] };
type Coverage = {
  unassignedRequirementIds: string[];
  unresolvedRequirementIds: string[];
  invalidReferenceIds: string[];
};
type Pending = {
  operationId: string;
  expectedRevision: number;
  kind: "reorder" | "verify";
  payload:
    | { shotIds: string[] }
    | {
        draftId: string;
        mediaId: string;
        role: string;
        matchesPurpose: boolean;
        note: string;
      };
};
const referenceNames: Record<string, string> = {
  identity: "身份",
  style: "风格",
  location: "地点",
  prop: "道具",
  composition: "构图",
  firstFrame: "首帧",
  keyMoment: "关键时刻",
  endFrame: "末帧",
  voiceDrive: "声音驱动",
  voiceReference: "声音参考",
};
const referenceStates: Record<string, string> = {
  verified: "已核对",
  incompatible: "用途不符",
  pending: "待核对",
  imported: "已导入",
  missing: "缺失",
};

function blank(kind: "asset" | "shot", sceneId: string): Draft {
  const id = uuid();
  return {
    id,
    artifactId: uuid(),
    baseRevisionId: null,
    content: {
      kind,
      content:
        kind === "asset"
          ? {
              assetType: "character",
              name: "",
              identityAnchors: [],
              allowedChanges: [],
              states: [],
              references: [],
            }
          : {
              shotId: uuid(),
              purpose: "",
              sceneId,
              assetRevisionIds: [],
              requirementIds: [],
              startState: "",
              events: [],
              endState: "",
              camera: "",
              subjectHand: "none",
              plannedMs: 1000,
              dialogueIds: [],
              references: [],
              videoMediaId: null,
              pickupOfShotId: null,
              use: "original",
            },
    },
  };
}
type Options = {
  scenes: { id: string; label: string }[];
  requirements: { id: string; label: string }[];
  dialogues: { id: string; label: string }[];
  assets: { id: string; label: string }[];
};
function ActiveEditor({
  engine,
  kind,
  session,
  ready,
  locked,
  media,
  shots,
  options,
  onVerify,
  onPrompt,
}: {
  engine: DraftAutosave;
  kind: "asset" | "shot";
  session: ProjectSession;
  ready: boolean;
  locked: boolean;
  media: Media[];
  shots: string[];
  options: Options;
  onVerify: (index: number, matchesPurpose: boolean, note: string) => void;
  onPrompt: (phase: "image" | "video") => void;
}) {
  const state = useSyncExternalStore(engine.subscribe, () => engine.snapshot);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const readOnly = session.mode === "read" || locked;
  return (
    <div className="active-content-editor">
      <p role="status">
        {
          {
            saved: "草稿已保存",
            dirty: "修改待保存",
            saving: "正在保存…",
            unknown: "结果待核对",
            error: "尚未保存",
            conflict: "版本冲突待处理",
          }[state.status]
        }
      </p>
      <ContentFields
        kind={kind}
        state={state}
        readOnly={readOnly}
        media={media}
        shots={shots}
        options={options}
        projectId={session.projectId}
        onEdit={(content) => engine.edit(content)}
      />
      {kind === "shot" && (
        <div className="project-actions">
          <button
            disabled={!ready || readOnly}
            onClick={() => onPrompt("image")}
          >
            预览单帧模板
          </button>
          <button
            disabled={!ready || readOnly}
            onClick={() => onPrompt("video")}
          >
            预览视频模板
          </button>
        </div>
      )}
      {entries(state.content.references).map((reference, i) => (
        <div
          className="reference-review"
          key={`${value(reference.mediaId)}-${i}`}
        >
          <span>
            {(referenceNames as Record<string, string>)[
              value(reference.role)
            ] ?? "参考"}{" "}
            ·{" "}
            {(referenceStates as Record<string, string>)[
              value(reference.state)
            ] ?? "待核对"}
          </span>
          <label>
            核对说明
            <input
              value={notes[i] ?? ""}
              disabled={readOnly}
              maxLength={2000}
              placeholder="写下与当前用途相符或不符的原因"
              onChange={(e) =>
                setNotes((current) => ({ ...current, [i]: e.target.value }))
              }
            />
          </label>
          <button
            disabled={!ready || readOnly || !(notes[i] ?? "").trim()}
            onClick={() => onVerify(i, true, notes[i].trim())}
          >
            核对用途一致
          </button>
          <button
            disabled={!ready || readOnly || !(notes[i] ?? "").trim()}
            onClick={() => onVerify(i, false, notes[i].trim())}
          >
            标记用途不符
          </button>
        </div>
      ))}
      {state.message && (
        <p className="notice" role="alert">
          {state.message}
        </p>
      )}
      {state.status === "conflict" && (
        <div className="draft-conflict">
          <p>远端内容已变化。当前输入仍保留，请逐项核对后选择。</p>
          <button
            disabled={!ready || readOnly}
            onClick={() => void engine.resolveConflict("local")}
          >
            保留当前输入并保存
          </button>
          <button
            disabled={!ready || readOnly || !state.remote}
            onClick={() => void engine.resolveConflict("saved")}
          >
            使用已保存内容
          </button>
        </div>
      )}
      <button
        className="primary-button"
        disabled={
          !ready ||
          readOnly ||
          state.status === "saving" ||
          state.status === "conflict"
        }
        onClick={() => void engine.flush()}
      >
        {state.status === "unknown" ? "核对原操作并保存" : "保存当前草稿"}
      </button>
      <p className="muted">
        草稿不会自动采用。保存为候选后，到版本区预览影响并采用。
      </p>
    </div>
  );
}

export function ContentWorkbench({
  session,
  ready,
  locked,
  action,
  storyEngine,
  onEngine,
  onFocusArtifact,
}: {
  session: ProjectSession;
  ready: boolean;
  locked: boolean;
  action: (work: () => Promise<void>) => Promise<void>;
  storyEngine: DraftAutosave | null;
  onEngine: (engine: DraftAutosave | null) => void;
  onFocusArtifact: (artifactId: string) => void;
}) {
  const [index, setIndex] = useState<Index>({ drafts: [], shotIds: [] });
  const [shotDrafts, setShotDrafts] = useState<Record<string, string>>({});
  const [assetNames, setAssetNames] = useState<Record<string, string>>({});
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [media, setMedia] = useState<Media[]>([]);
  const [options, setOptions] = useState<Options>({
    scenes: [],
    requirements: [],
    dialogues: [],
    assets: [],
  });
  const [selected, setSelected] = useState<Summary | null>(null);
  const [fresh, setFresh] = useState<Draft | null>(null);
  const activeDraftId = fresh?.id ?? selected?.id ?? null;
  const [engine, setEngine] = useState<DraftAutosave | null>(null);
  const active = useRef<DraftAutosave | null>(null);
  const [message, setMessage] = useState("");
  const pendingKey = `storyboard-operation:${session.projectId}`;
  const [pending, setPending] = useState<Pending | null>(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(pendingKey) ?? "null");
      return stored?.operationId && stored?.expectedRevision !== undefined
        ? stored
        : null;
    } catch {
      return null;
    }
  });
  const [prompt, setPrompt] = useState<{
    prompt: string;
    templateId: string;
    templateVersion: string;
    blockers: string[];
    sourceRevisionIds: string[];
    reusableVideoMediaId: string | null;
  } | null>(null);
  const [promptPhase, setPromptPhase] = useState<"image" | "video">("image");
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);
  const disabled =
    !ready || locked || busy || session.mode === "read" || !!pending;
  useEffect(() => {
    if (pending) localStorage.setItem(pendingKey, JSON.stringify(pending));
    else localStorage.removeItem(pendingKey);
  }, [pending, pendingKey]);
  const refresh = useCallback(async () => {
    const [listed, covered, loadedMedia] = await Promise.all([
      window.desktop.storyboard.list({ projectId: session.projectId }),
      window.desktop.storyboard.coverage({ projectId: session.projectId }),
      window.desktop.projects.media.list({
        projectId: session.projectId,
        limit: 200,
      }),
    ]);
    if (!mounted.current) return;
    if (listed.ok) {
      setIndex(listed.data);
      const drafts = listed.data.drafts.filter((d) => d.kind === "shot");
      const loaded = await Promise.all(
        drafts.map(async (d) => ({
          id: d.id,
          result: await window.desktop.projects.drafts.get({
            projectId: session.projectId,
            draftId: d.id,
          }),
        })),
      );
      if (!mounted.current) return;
      setShotDrafts(
        Object.fromEntries(
          loaded
            .filter((row) => row.result.ok)
            .map((row) => [
              value(
                row.result.ok ? row.result.data.content.content.shotId : "",
              ),
              row.id,
            ]),
        ),
      );
      const story = listed.data.drafts.find((d) => d.kind === "story");
      const loadedStory =
        story &&
        (await window.desktop.projects.drafts.get({
          projectId: session.projectId,
          draftId: story.id,
        }));
      const content = loadedStory?.ok ? loadedStory.data.content.content : {};
      const assetStates = await Promise.all(
        listed.data.drafts
          .filter((d) => d.kind === "asset")
          .map(async (d) => ({
            draft: d,
            result: await window.desktop.versions.artifact({
              projectId: session.projectId,
              artifactId: d.artifactId,
            }),
          })),
      );
      const assetDrafts = await Promise.all(
        listed.data.drafts
          .filter((d) => d.kind === "asset")
          .map(async (d) => ({
            id: d.id,
            result: await window.desktop.projects.drafts.get({
              projectId: session.projectId,
              draftId: d.id,
            }),
          })),
      );
      if (!mounted.current) return;
      setAssetNames(
        Object.fromEntries(
          assetDrafts.map((row) => [
            row.id,
            row.result.ok ? value(row.result.data.content.content.name) : "",
          ]),
        ),
      );
      setOptions({
        scenes: entries(content.scenes).map((s) => ({
          id: value(s.id),
          label: value(s.title) || value(s.id).slice(0, 8),
        })),
        requirements: entries(content.requirements).map((r) => ({
          id: value(r.id),
          label: value(r.text) || value(r.id).slice(0, 8),
        })),
        dialogues: entries(content.dialogues).map((d) => ({
          id: value(d.id),
          label: value(d.text) || value(d.id).slice(0, 8),
        })),
        assets: assetStates
          .filter((row) => row.result.ok && !!row.result.data.adoptedRevisionId)
          .map((row) => ({
            id: row.result.ok ? row.result.data.adoptedRevisionId! : "",
            label: `资产 ${row.draft.id.slice(0, 8)}`,
          })),
      });
    } else setMessage(listed.error.message);
    if (covered.ok) setCoverage(covered.data);
    if (loadedMedia.ok) setMedia(loadedMedia.data.items);
  }, [session.projectId]);
  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => {
      mounted.current = false;
      active.current?.dispose();
      onEngine(null);
    };
  }, [refresh, onEngine]);
  useEffect(() => {
    active.current = engine;
    onEngine(engine);
    return () => {
      if (active.current === engine) {
        active.current = null;
        onEngine(null);
      }
    };
  }, [engine, onEngine]);
  useEffect(() => {
    engine?.setPaused(!ready || session.mode === "read");
  }, [engine, ready, session.mode]);
  useEffect(() => {
    if (engine && storyEngine) {
      engine.onCommit = (before, after) => {
        storyEngine.advanceProjectRevision(before, after);
        window.dispatchEvent(
          new CustomEvent("content-revision-advanced", {
            detail: { before, after },
          }),
        );
        void refresh();
        window.dispatchEvent(new Event("storyboard-updated"));
        if (fresh) {
          setSelected({
            id: fresh.id,
            artifactId: fresh.artifactId,
            kind: fresh.content.kind,
            savedAt: new Date().toISOString(),
          });
          setFresh(null);
        }
      };
      return () => {
        engine.onCommit = undefined;
      };
    }
  }, [engine, storyEngine, refresh, fresh]);
  useEffect(() => {
    const onUpdate = () => {
      void refresh();
    };
    window.addEventListener("storyboard-updated", onUpdate);
    return () => window.removeEventListener("storyboard-updated", onUpdate);
  }, [refresh]);
  useEffect(() => {
    let alive = true;
    if (!activeDraftId) {
      setEngine(null);
      return;
    }
    void (async () => {
      setEngine(null);
      const result = fresh
        ? null
        : await window.desktop.projects.drafts.get({
            projectId: session.projectId,
            draftId: activeDraftId,
          });
      if (!alive) return;
      if (result && !result.ok) {
        setMessage(result.error.message);
        return;
      }
      const loaded = fresh ?? (result?.ok ? result.data : null);
      const project = await window.desktop.projects.drafts.project({
        projectId: session.projectId,
      });
      if (!alive || !loaded) return;
      if (!project.ok) {
        setMessage(project.error.message);
        return;
      }
      setEngine(
        new DraftAutosave(
          window.desktop.projects.drafts,
          session.projectId,
          loaded,
          project.data.revision,
          selected?.savedAt ?? null,
        ),
      );
      setMessage("");
    })();
    return () => {
      alive = false;
      setEngine((current) => {
        current?.dispose();
        return null;
      });
    };
  }, [activeDraftId, session.projectId]);
  async function switchTo(target: Summary | null, draft: Draft | null = null) {
    if (busy || pending) return;
    if (active.current && !(await active.current.flush())) {
      setMessage("当前草稿尚未保存，请核对结果后再切换。");
      return;
    }
    if (storyEngine && !(await storyEngine.flush())) {
      setMessage("故事草稿尚未保存，请核对结果后再切换。");
      return;
    }
    setSelected(target);
    setFresh(draft);
    setPrompt(null);
  }
  async function create(kind: "asset" | "shot") {
    const story = await window.desktop.storyboard.list({
      projectId: session.projectId,
    });
    if (!story.ok) return setMessage(story.error.message);
    const existing = story.data.drafts.find((item) => item.kind === "story");
    const loaded = existing
      ? await window.desktop.projects.drafts.get({
          projectId: session.projectId,
          draftId: existing.id,
        })
      : null;
    const sceneId = loaded?.ok
      ? value(entries(loaded.data.content.content.scenes)[0]?.id)
      : "";
    if (kind === "shot" && !sceneId)
      return setMessage("先在故事草稿中添加并保存分场，再新建镜头。");
    await switchTo(null, blank(kind, sceneId));
  }
  async function command(kind: Pending["kind"], payload: Pending["payload"]) {
    if (disabled) return;
    await action(async () => {
      if (
        (engine && !(await engine.flush())) ||
        (storyEngine && !(await storyEngine.flush()))
      ) {
        setMessage("先核对草稿保存结果，再执行操作。");
        return;
      }
      setBusy(true);
      setMessage("");
      const project = await window.desktop.projects.drafts.project({
        projectId: session.projectId,
      });
      if (!project.ok) {
        setMessage(project.error.message);
        setBusy(false);
        return;
      }
      const operation: Pending = {
        kind,
        payload,
        operationId: uuid(),
        expectedRevision: project.data.revision,
      };
      setPending(operation);
      try {
        await submit(operation);
      } finally {
        setBusy(false);
      }
    });
  }
  async function submit(operation: Pending) {
    try {
      const result =
        operation.kind === "reorder"
          ? await window.desktop.storyboard.reorder({
              projectId: session.projectId,
              command: {
                clientOperationId: operation.operationId,
                expectedRevision: operation.expectedRevision,
                payload: operation.payload as { shotIds: string[] },
              },
            })
          : await window.desktop.storyboard.verify({
              projectId: session.projectId,
              command: {
                clientOperationId: operation.operationId,
                expectedRevision: operation.expectedRevision,
                payload: operation.payload as Parameters<
                  typeof window.desktop.storyboard.verify
                >[0]["command"]["payload"],
              },
            });
      if (!result.ok) {
        setMessage(result.error.message);
        if (
          [
            "REQUEST_INVALID",
            "VALIDATION_FAILED",
            "PROJECT_READ_ONLY",
            "REVISION_CONFLICT",
            "OBJECT_NOT_FOUND",
            "REFERENCE_INVALID",
            "MEDIA_HASH_MISMATCH",
            "MEDIA_MISSING",
            "INPUT_LOCKED",
          ].includes(result.error.code)
        )
          setPending(null);
        return;
      }
      if (
        result.data.operationId !== operation.operationId ||
        result.data.committedRevision !== operation.expectedRevision + 1
      ) {
        setMessage("回执与原操作不符，请查询原操作。");
        return;
      }
      await complete(operation, result.data.committedRevision);
    } catch {
      setMessage("操作结果未知。请查询原操作；当前输入和操作编号已保留。");
    }
  }
  async function complete(operation: Pending, committedRevision: number) {
    setPending(null);
    engine?.advanceProjectRevision(
      operation.expectedRevision,
      committedRevision,
    );
    storyEngine?.advanceProjectRevision(
      operation.expectedRevision,
      committedRevision,
    );
    if (operation.kind === "verify") {
      const draftId = (operation.payload as { draftId: string }).draftId;
      const refreshed = await window.desktop.projects.drafts.get({
        projectId: session.projectId,
        draftId,
      });
      if (refreshed.ok && selected?.id === draftId)
        setEngine((current) => {
          current?.dispose();
          return new DraftAutosave(
            window.desktop.projects.drafts,
            session.projectId,
            refreshed.data,
            committedRevision,
            selected.savedAt,
          );
        });
    }
    await refresh();
    setMessage(
      operation.kind === "reorder"
        ? "镜头顺序已更新；相关采用成果的影响需重新核对。"
        : "用途核对已记录；采用状态没有改变。",
    );
  }
  async function queryPending() {
    if (!pending) return;
    await action(async () => {
      const result = await window.desktop.projects.drafts.operation({
        projectId: session.projectId,
        operationId: pending.operationId,
      });
      if (!result.ok) {
        setMessage(result.error.message);
        return;
      }
      if (
        result.data.receipt.operationId !== pending.operationId ||
        result.data.receipt.committedRevision !== pending.expectedRevision + 1
      ) {
        setMessage("原操作回执不匹配。");
        return;
      }
      await complete(pending, result.data.receipt.committedRevision);
    });
  }
  async function viewPrompt(phase: "image" | "video") {
    if (!engine || !(await engine.flush())) {
      setMessage("先保存当前镜头草稿。");
      return;
    }
    const shotId = value(engine.snapshot.content.shotId);
    const result = await window.desktop.storyboard.prompt({
      projectId: session.projectId,
      shotId,
      phase,
    });
    if (result.ok) {
      setPromptPhase(phase);
      setPrompt(result.data);
    } else setMessage(result.error.message);
  }
  const kind = (fresh?.content.kind ?? selected?.kind) as
    "asset" | "shot" | undefined;
  const requirementLabel = (id: string) =>
    options.requirements.find((r) => r.id === id)?.label ||
    `要求 ${id.slice(0, 8)}`;
  const referenceLabel = (id: string) => {
    const found = media.find((m) => m.id === id);
    return found
      ? `${found.mime} 素材 ${id.slice(0, 8)}`
      : `参考 ${id.slice(0, 8)}`;
  };
  return (
    <section className="content-workbench" aria-label="视觉资产与分镜">
      <div className="section-heading">
        <h2>视觉资产与分镜</h2>
        <span>草稿、候选与采用分开管理</span>
      </div>
      {message && (
        <p className="notice" role="alert">
          {message}
        </p>
      )}
      {pending && (
        <div className="notice">
          <p>操作结果待核对，请只查询原操作。</p>
          <button
            disabled={!ready || locked}
            onClick={() => void queryPending()}
          >
            查询原操作
          </button>
          <button
            disabled={!ready || locked}
            onClick={() => void action(() => submit(pending))}
          >
            重试原操作
          </button>
        </div>
      )}
      {session.mode === "read" && (
        <p className="notice">只读模式可以浏览，不能修改草稿或镜头顺序。</p>
      )}
      <div className="workbench-layout">
        <aside className="workbench-index">
          <h3>资产</h3>
          {index.drafts
            .filter((d) => d.kind === "asset")
            .map((d) => (
              <button
                aria-pressed={selected?.id === d.id}
                key={d.id}
                onClick={() => void switchTo(d)}
              >
                {assetNames[d.id] || `未命名资产 ${d.id.slice(0, 8)}`} ·{" "}
                {new Date(d.savedAt).toLocaleDateString("zh-CN")}
              </button>
            ))}
          <button disabled={disabled} onClick={() => void create("asset")}>
            新建资产
          </button>
          <h3>镜头顺序</h3>
          {index.shotIds.map((shotId, i) => {
            const draft = index.drafts.find((d) => d.id === shotDrafts[shotId]);
            return (
              <div key={shotId} className="shot-order-row">
                <button
                  onClick={() => {
                    if (draft) void switchTo(draft);
                  }}
                  aria-pressed={selected?.id === draft?.id}
                >
                  镜头 {i + 1}
                </button>
                <button
                  aria-label={`上移镜头 ${i + 1}`}
                  disabled={disabled || i === 0}
                  onClick={() => {
                    const order = [...index.shotIds];
                    [order[i - 1], order[i]] = [order[i], order[i - 1]];
                    void command("reorder", { shotIds: order });
                  }}
                >
                  ↑
                </button>
                <button
                  aria-label={`下移镜头 ${i + 1}`}
                  disabled={disabled || i === index.shotIds.length - 1}
                  onClick={() => {
                    const order = [...index.shotIds];
                    [order[i + 1], order[i]] = [order[i], order[i + 1]];
                    void command("reorder", { shotIds: order });
                  }}
                >
                  ↓
                </button>
              </div>
            );
          })}
          <button disabled={disabled} onClick={() => void create("shot")}>
            新建镜头
          </button>
        </aside>
        <div className="workbench-main">
          {engine && kind ? (
            <>
              <div className="section-heading">
                <h3>{kind === "asset" ? "资产草稿" : "镜头草稿"}</h3>
                {selected && (
                  <button onClick={() => onFocusArtifact(selected.artifactId)}>
                    查看版本与对照
                  </button>
                )}
              </div>
              <ActiveEditor
                engine={engine}
                kind={kind}
                session={session}
                ready={ready}
                locked={locked || busy || !!pending}
                media={media}
                shots={index.shotIds}
                options={options}
                onVerify={(i, matchesPurpose, note) => {
                  const reference = entries(engine.snapshot.content.references)[
                    i
                  ];
                  if (reference)
                    void command("verify", {
                      draftId: selected?.id ?? fresh!.id,
                      mediaId: value(reference.mediaId),
                      role: value(reference.role),
                      matchesPurpose,
                      note,
                    });
                }}
                onPrompt={(phase) => void viewPrompt(phase)}
              />
            </>
          ) : (
            <div className="version-empty-state">
              <h3>从资产或镜头开始</h3>
              <p>
                选取已有草稿，或新建一个对象。保存后可以进入版本区对照和采用。
              </p>
            </div>
          )}
          {prompt && (
            <section className="prompt-preview" aria-label="本地模板预览">
              <h4>
                {promptPhase === "video" ? "视频制作依据" : "单帧制作依据"}
              </h4>
              <pre>{prompt.prompt}</pre>
              <details>
                <summary>制作记录</summary>
                <p>
                  模板 {prompt.templateId} / {prompt.templateVersion}
                </p>
                <p>
                  来源版本：
                  {prompt.sourceRevisionIds.length
                    ? prompt.sourceRevisionIds.join("、")
                    : "尚无已采用来源"}
                </p>
                {prompt.reusableVideoMediaId && (
                  <p>已有可复用素材：{prompt.reusableVideoMediaId}</p>
                )}
              </details>
              {prompt.blockers.length ? (
                <>
                  <h5>当前准入缺口</h5>
                  <ul>
                    {prompt.blockers.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                </>
              ) : (
                <p>模板仅供准备参考；实际生成仍需经过任务入口与准入检查。</p>
              )}
            </section>
          )}
        </div>
      </div>
      <section className="coverage-panel">
        <h3>承载缺口</h3>
        <p>仅核对已采用内容的结构与引用；语义和画面质量仍需人工检查。</p>
        {coverage ? (
          <dl>
            <div>
              <dt>未安排的必留要求</dt>
              <dd>
                {coverage.unassignedRequirementIds.length
                  ? coverage.unassignedRequirementIds
                      .map(requirementLabel)
                      .join("、")
                  : "暂无"}
              </dd>
            </div>
            <div>
              <dt>尚未决定的要求</dt>
              <dd>
                {coverage.unresolvedRequirementIds.length
                  ? coverage.unresolvedRequirementIds
                      .map(requirementLabel)
                      .join("、")
                  : "暂无"}
              </dd>
            </div>
            <div>
              <dt>不可用参考</dt>
              <dd>
                {coverage.invalidReferenceIds.length
                  ? coverage.invalidReferenceIds.map(referenceLabel).join("、")
                  : "暂无"}
              </dd>
            </div>
          </dl>
        ) : (
          <p role="status">正在读取承载缺口…</p>
        )}
        <button disabled={!ready} onClick={() => void refresh()}>
          刷新缺口
        </button>
      </section>
    </section>
  );
}
