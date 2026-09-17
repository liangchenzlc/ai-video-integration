import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import type { Draft } from "../../electron/shared/drafts";
import type { Media, MediaJob } from "../../electron/shared/media";
import type {
  ProjectResult,
  ProjectSession,
} from "../../electron/shared/projects";
import { projectMessages, receiptSchema } from "../../electron/shared/projects";
import {
  chosenTargetSchema,
  issueSchema,
  productionRoutes,
  type ProductionIndex,
  type RightEvidence,
} from "../../electron/shared/production";
import type { CapabilityProfile } from "../../electron/shared/settings";
import type { z } from "zod";
import { DraftAutosave } from "./draft-autosave";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import { ProductionFields } from "./ProductionFields";
import {
  blank,
  ids,
  number,
  rows,
  uid,
  word,
  type Content,
  type ProductionKind,
  type Row,
} from "./production-fields";

type Summary = ProductionIndex["drafts"][number];
type Adopted = ProductionIndex["adopted"][number];
type Issue = z.infer<typeof issueSchema>;
type Right = RightEvidence;
type Receipt = z.infer<typeof receiptSchema>;
type Choice = NonNullable<z.infer<typeof chosenTargetSchema>>;
type Report = {
  ready?: boolean;
  suitable?: boolean;
  requiredMs?: number;
  plannedMs?: number;
  shortageMs?: number;
  method?: string;
  blockers?: string[];
  warnings?: string[];
  canPreserveEdit?: boolean;
  affectedClipIds?: string[];
  requiredChecks?: string[];
};
type Pending = {
  method:
    "animatic" | "exportFilm" | "diagnostic" | "saveRights" | "decideIssue";
  id: string;
  revision: number;
  payload: Row;
  resourceId?: string;
};
const kindNames: Record<ProductionKind, string> = {
  speech: "配音",
  subtitle: "字幕",
  timeline: "时间线",
  observation: "原片观察",
};
const production = () => window.desktop.production;
const mediaName = (m: Media) => `${m.mime} · ${m.id.slice(0, 8)}`;
const jobStateNames: Record<string, string> = {
  pending: "等待中",
  queued: "排队中",
  running: "运行中",
  succeeded: "已完成",
  complete: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export function ProductionWorkbench({
  session,
  ready,
  locked,
  action,
  onEngine,
  storyEngine,
  contentEngine,
  onFocusArtifact,
  onOpenMedia,
  page,
}: {
  session: ProjectSession;
  ready: boolean;
  active: boolean;
  locked: boolean;
  action: (work: () => Promise<void>) => Promise<void>;
  onEngine: (engine: DraftAutosave | null) => void;
  storyEngine: DraftAutosave | null;
  contentEngine: DraftAutosave | null;
  onFocusArtifact: (artifactId: string) => void;
  onOpenMedia: () => void;
  page: string;
}) {
  const projectId = session.projectId;
  const [index, setIndex] = useState<{ drafts: Summary[]; adopted: Adopted[] }>(
    {
      drafts: [],
      adopted: [],
    },
  );
  const [media, setMedia] = useState<Media[]>([]);
  const [capabilities, setCapabilities] = useState<CapabilityProfile[]>([]);
  const [rights, setRights] = useState<Right[]>([]);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [issueCursor, setIssueCursor] = useState<string | null>(null);
  const [section, setSection] = useState<
    ProductionKind | "delivery" | "video" | "rights" | "diagnostic"
  >("speech");
  const [selected, setSelected] = useState<Summary | null>(null);
  const [fresh, setFresh] = useState<Draft | null>(null);
  const [engine, setEngine] = useState<DraftAutosave | null>(null);
  const engineRef = useRef<DraftAutosave | null>(null);
  const loadedDraftId = useRef<string | null>(null);
  const switchingDraft = useRef(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [timingBefore, setTimingBefore] = useState(600);
  const [timingAfter, setTimingAfter] = useState(600);
  const [shotRevisionId, setShotRevisionId] = useState("");
  const [speechRevisionIds, setSpeechRevisionIds] = useState<string[]>([]);
  const [capabilityId, setCapabilityId] = useState("");
  const [videoPath, setVideoPath] = useState<"research" | "production">(
    "research",
  );
  const [timelineRevisionId, setTimelineRevisionId] = useState("");
  const [chosenClip, setChosenClip] = useState("");
  const [replacementMediaId, setReplacementMediaId] = useState("");
  const [draftPreview, setDraftPreview] = useState<Content | null>(null);
  const [previewDraftId, setPreviewDraftId] = useState<string | null>(null);
  const [previewNote, setPreviewNote] = useState("");
  const [right, setRight] = useState<Right | null>(null);
  const [duckDb, setDuckDb] = useState(12);
  const [attackMs, setAttackMs] = useState(120);
  const [releaseMs, setReleaseMs] = useState(240);
  const [burnSubtitles, setBurnSubtitles] = useState(true);
  const [exportChoice, setExportChoice] = useState<Choice | null>(null);
  const [exportId, setExportId] = useState("");
  const [exportStatus, setExportStatus] = useState("");
  const [job, setJob] = useState<MediaJob | null>(null);
  const [issueReason, setIssueReason] = useState("");
  const pendingKey = `production-pending:${projectId}`;
  const [pending, setPending] = useState<Pending | null>(() => {
    try {
      const item = JSON.parse(
        localStorage.getItem(`production-pending:${projectId}`) ?? "null",
      ) as Pending | null;
      return item &&
        [
          "animatic",
          "exportFilm",
          "diagnostic",
          "saveRights",
          "decideIssue",
        ].includes(item.method) &&
        typeof item.id === "string" &&
        typeof item.revision === "number"
        ? item
        : null;
    } catch {
      return null;
    }
  });
  const disabled =
    !ready || locked || busy || !!pending || session.mode === "read";
  const activeDraftId = fresh?.id ?? selected?.id ?? null;
  const draftKind = fresh?.content.kind ?? selected?.kind;
  const state = useSyncExternalStore(
    engine?.subscribe ?? (() => () => {}),
    () => engine?.snapshot ?? null,
    () => null,
  );

  useEffect(() => {
    if (page === "镜头制作") setSection("video");
    else if (page === "检查与导出") setSection("delivery");
    else if (page === "声音与剪辑") setSection("speech");
    else if (page === "项目工具") setSection("diagnostic");
  }, [page]);

  const refresh = useCallback(async () => {
    const [files, settings] = await Promise.all([
      window.desktop.projects.media.list({ projectId, limit: 200 }),
      window.desktop.settings.get(),
    ]);
    const drafts: Summary[] = [];
    const adopted: Adopted[] = [];
    let offset = 0;
    let indexError = "";
    for (;;) {
      const listed = await production().index({ projectId, offset });
      if (!listed.ok) {
        indexError = listed.error.message;
        break;
      }
      drafts.push(...listed.data.drafts);
      adopted.push(...listed.data.adopted);
      if (listed.data.nextOffset === null) break;
      if (listed.data.nextOffset <= offset) {
        indexError = "制作索引分页没有前进，请重试读取。";
        break;
      }
      offset = listed.data.nextOffset;
    }
    if (indexError) setMessage(indexError);
    else setIndex({ drafts, adopted });
    if (files.ok) setMedia(files.data.items);
    if (settings.ok)
      setCapabilities(
        settings.data.capabilities.filter(
          (item) => item.enabled && item.stage === "video",
        ),
      );
  }, [projectId]);

  useEffect(() => {
    if (ready) void refresh();
  }, [ready, refresh]);
  useEffect(() => {
    if (pending) localStorage.setItem(pendingKey, JSON.stringify(pending));
    else localStorage.removeItem(pendingKey);
  }, [pending, pendingKey]);
  useEffect(() => {
    const advanced = (event: Event) => {
      const { before, after } = (
        event as CustomEvent<{ before: number; after: number }>
      ).detail;
      engineRef.current?.advanceProjectRevision(before, after);
    };
    window.addEventListener("content-revision-advanced", advanced);
    return () =>
      window.removeEventListener("content-revision-advanced", advanced);
  }, []);
  useEffect(() => {
    engineRef.current = engine;
    onEngine(engine);
    return () => {
      if (engineRef.current === engine) onEngine(null);
    };
  }, [engine, onEngine]);
  useEffect(() => {
    engine?.setPaused(!ready || session.mode === "read");
  }, [engine, ready, session.mode]);
  useEffect(() => {
    return () => {
      loadedDraftId.current = null;
      setEngine((current) => {
        current?.dispose();
        return null;
      });
    };
  }, [activeDraftId, projectId]);
  useEffect(() => {
    if (!activeDraftId || !ready || loadedDraftId.current === activeDraftId)
      return;
    let alive = true;
    void (async () => {
      const loaded = fresh
        ? { ok: true as const, data: fresh }
        : await window.desktop.projects.drafts.get({
            projectId,
            draftId: activeDraftId,
          });
      const project = await window.desktop.projects.drafts.project({
        projectId,
      });
      if (!alive) return;
      if (!loaded.ok || !project.ok) {
        setMessage(
          !loaded.ok
            ? loaded.error.message
            : !project.ok
              ? project.error.message
              : "",
        );
        return;
      }
      if (loadedDraftId.current === activeDraftId) return;
      loadedDraftId.current = activeDraftId;
      setEngine(
        new DraftAutosave(
          window.desktop.projects.drafts,
          projectId,
          loaded.data,
          project.data.revision,
          selected?.savedAt ?? null,
        ),
      );
    })();
    return () => {
      alive = false;
    };
  }, [activeDraftId, projectId, ready]);
  useEffect(() => {
    if (!engine) return;
    engine.onCommit = (before, after) => {
      storyEngine?.advanceProjectRevision(before, after);
      contentEngine?.advanceProjectRevision(before, after);
      if (fresh)
        setSelected({
          id: fresh.id,
          artifactId: fresh.artifactId,
          kind: fresh.content.kind,
          savedAt: new Date().toISOString(),
        });
      setFresh(null);
      void refresh();
      window.dispatchEvent(new Event("storyboard-updated"));
    };
    return () => {
      engine.onCommit = undefined;
    };
  }, [engine, storyEngine, contentEngine, refresh, fresh]);
  useEffect(
    () => () => {
      engineRef.current?.dispose();
      onEngine(null);
    },
    [onEngine],
  );

  async function flushAll() {
    if (engineRef.current && !(await engineRef.current.flush())) return false;
    if (storyEngine && !(await storyEngine.flush())) return false;
    if (contentEngine && !(await contentEngine.flush())) return false;
    return true;
  }
  async function switchDraft(
    summary: Summary | null,
    draft: Draft | null = null,
  ) {
    if (switchingDraft.current || pending || busy || locked || !ready)
      return setMessage("请先核对当前操作结果，再切换草稿。");
    if (activeDraftId && !engineRef.current)
      return setMessage("当前草稿尚未载入，不能切换；请恢复连接后重试。");
    switchingDraft.current = true;
    try {
      if (!(await flushAll()))
        return setMessage("先核对未保存草稿，再切换内容。");
      setSelected(summary);
      setFresh(draft);
      setDraftPreview(null);
      setPreviewDraftId(null);
      setMessage("");
    } finally {
      switchingDraft.current = false;
    }
  }
  async function create(kind: ProductionKind) {
    await switchDraft(null, blank(kind));
  }
  async function run(work: () => Promise<void>) {
    if (!ready || busy || locked) return;
    await action(async () => {
      setBusy(true);
      setMessage("");
      try {
        await work();
      } catch {
        setMessage("连接中断。输入已保留，请查询原操作再重试。");
      } finally {
        setBusy(false);
      }
    });
  }
  async function readReport(call: () => Promise<ProjectResult<Report>>) {
    await run(async () => {
      if (!(await flushAll())) return setMessage("请先核对草稿保存状态。");
      const result = await call();
      if (result.ok) setReport(result.data);
      else setMessage(result.error.message);
    });
  }
  async function acceptPreview() {
    if (
      !draftPreview ||
      !engine ||
      disabled ||
      previewDraftId !== activeDraftId ||
      draftKind !== "timeline"
    )
      return;
    engine.edit(draftPreview);
    setDraftPreview(null);
    setPreviewNote("已写入时间线草稿，请保存后到版本区创建候选并决定采用。");
  }
  async function previewEdit(
    edit: "move" | "split" | "trim",
    clipId: string,
    change: Row,
  ) {
    if (!engine) return;
    await run(async () => {
      if (!(await flushAll())) return setMessage("请先保存当前时间线草稿。");
      const input = productionRoutes.timelineEdit.input.safeParse({
        projectId,
        payload: {
          timeline: engine.snapshot.content,
          action: edit,
          clipId,
          ...change,
        },
      });
      if (!input.success)
        return setMessage("时间线草稿结构尚不完整，请核对后保存。");
      const result = await production().timelineEdit(input.data);
      if (result.ok) {
        setDraftPreview(result.data.timeline);
        setPreviewDraftId(activeDraftId);
        setPreviewNote(
          `${edit === "move" ? "移动" : edit === "split" ? "分割" : "裁切"}影响 ${result.data.affectedClipIds.length} 个片段；字幕切点 ${result.data.subtitleSplitPreview.length} 处。请核对后写入草稿。`,
        );
      } else setMessage(result.error.message);
    });
  }
  async function previewDucking() {
    if (!timelineRevisionId) return setMessage("先选择已采用时间线版本。");
    await run(async () => {
      const musicClipIds = rows(
        index.adopted.find((a) => a.revisionId === timelineRevisionId)?.content
          .clips,
      )
        .filter((clip) => {
          const timeline = index.adopted.find(
            (a) => a.revisionId === timelineRevisionId,
          );
          return rows(timeline?.content.tracks).some(
            (track) => track.id === clip.trackId && track.kind === "music",
          );
        })
        .map((clip) => word(clip.id));
      const result = await production().ducking({
        projectId,
        payload: {
          timelineRevisionId,
          musicClipIds,
          reductionDb: duckDb,
          attackMs,
          releaseMs,
        },
      });
      if (!result.ok) return setMessage(result.error.message);
      setDraftPreview(result.data.timeline);
      const source = index.adopted.find(
        (item) => item.revisionId === timelineRevisionId,
      );
      setPreviewDraftId(
        source?.artifactId === selected?.artifactId && draftKind === "timeline"
          ? activeDraftId
          : null,
      );
      setPreviewNote(
        `对白优先音量包络已预览：${result.data.warnings.join("；") || "请试听与对白重叠的区间"}。需手动写入时间线草稿。`,
      );
    });
  }

  const adopted = (kind: string) =>
    index.adopted.filter((a) => a.kind === kind);
  const options = (kind: string) =>
    adopted(kind).map((a) => ({
      id: a.revisionId,
      label: `${kind === "shot" ? "镜头" : kind === "speech" ? "配音" : "版本"} ${a.revisionId.slice(0, 8)}${a.confirmed ? " · 已确认" : " · 待确认"}`,
    }));
  const dialogues = adopted("story").flatMap((story) =>
    rows(story.content.dialogues).map((dialogue) => ({
      id: word(dialogue.id),
      label: word(dialogue.text) || `对白 ${word(dialogue.id).slice(0, 8)}`,
    })),
  );
  const shots = adopted("shot").map((shot) => ({
    id: word(shot.content.shotId),
    label:
      word(shot.content.purpose) ||
      `镜头 ${word(shot.content.shotId).slice(0, 8)}`,
  }));
  const currentTimeline = adopted("timeline").find(
    (a) => a.revisionId === timelineRevisionId,
  );
  const timelineClips = rows(currentTimeline?.content.clips);
  const selectableSpeech = options("speech");
  const selectedSpeech = ids(speechRevisionIds);
  const writeAllowed =
    ready && !locked && session.mode === "write" && !busy && !pending;

  return (
    <section className="production-workbench" aria-label="声音、剪辑与成片">
      <div className="section-heading">
        <h2>声音、剪辑与成片</h2>
        <span>草稿 · 候选 · 采用 · 检查 · 导出</span>
      </div>
      {message && (
        <p className="notice" role="alert">
          {message}
        </p>
      )}
      {session.mode === "read" && (
        <p className="notice">只读会话可以浏览，不能修改草稿或发起本地作业。</p>
      )}
      <nav className="production-tabs" aria-label="制作环节">
        {(
          [
            "speech",
            "subtitle",
            "timeline",
            "observation",
            "video",
            "rights",
            "delivery",
            "diagnostic",
          ] as const
        ).map((tab) => (
          <button
            type="button"
            aria-current={section === tab ? "page" : undefined}
            className={section === tab ? "selected" : ""}
            key={tab}
            onClick={() => setSection(tab)}
          >
            {tab in kindNames
              ? kindNames[tab as ProductionKind]
              : {
                  video: "视频准入",
                  rights: "音乐与来源",
                  delivery: "检查与导出",
                  diagnostic: "诊断",
                }[tab as "video" | "rights" | "delivery" | "diagnostic"]}
          </button>
        ))}
      </nav>

      {(["speech", "subtitle", "timeline", "observation"] as const).includes(
        section as ProductionKind,
      ) && (
        <div className="production-layout">
          <aside className="production-index">
            <h3>{kindNames[section as ProductionKind]}草稿</h3>
            {index.drafts
              .filter((d) => d.kind === section)
              .map((d) => (
                <button
                  key={d.id}
                  aria-pressed={activeDraftId === d.id}
                  onClick={() => void switchDraft(d)}
                >
                  {kindNames[section as ProductionKind]} · {d.id.slice(0, 8)}
                  <small>{new Date(d.savedAt).toLocaleString("zh-CN")}</small>
                </button>
              ))}
            <button
              type="button"
              disabled={!writeAllowed}
              onClick={() => void create(section as ProductionKind)}
            >
              新建{kindNames[section as ProductionKind]}草稿
            </button>
            <p>
              音频和视频先在项目工具中导入；新草稿只有保存后才能创建不可变版本。
            </p>
            <button type="button" onClick={onOpenMedia}>
              打开素材库与导入
            </button>
          </aside>
          <div className="production-main">
            {engine && draftKind === section && state ? (
              <>
                <div className="section-heading">
                  <h3>编辑{kindNames[section as ProductionKind]}</h3>
                  {selected && (
                    <button
                      type="button"
                      onClick={() => onFocusArtifact(selected.artifactId)}
                    >
                      版本对照与采用
                    </button>
                  )}
                  <span role="status">
                    {state.status === "saved"
                      ? "已保存"
                      : state.status === "saving"
                        ? "保存中"
                        : state.status === "dirty"
                          ? "待保存"
                          : "需核对保存"}
                  </span>
                </div>
                {state.message && (
                  <p className="notice" role="alert">
                    {state.message}
                  </p>
                )}
                <ProductionFields
                  kind={section as ProductionKind}
                  projectId={projectId}
                  content={state.content}
                  disabled={disabled}
                  media={media}
                  dialogues={dialogues}
                  speeches={selectableSpeech}
                  shots={shots}
                  onEdit={(next) => engine.edit(next)}
                  onTimelinePreview={(edit, clipId, change) =>
                    void previewEdit(edit, clipId, change)
                  }
                />
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() =>
                    void run(async () => {
                      if (await engine.flush()) {
                        setMessage(
                          "草稿已保存。请到版本区创建候选、检查并决定采用。",
                        );
                        await refresh();
                      } else setMessage("草稿尚未保存，输入已保留。");
                    })
                  }
                >
                  保存草稿
                </button>
                {draftPreview && section === "timeline" && (
                  <div className="production-preview">
                    <h4>时间线变更预览</h4>
                    <p>{previewNote}</p>
                    <button
                      type="button"
                      disabled={disabled || previewDraftId !== activeDraftId}
                      onClick={() => void acceptPreview()}
                    >
                      写入当前时间线草稿
                    </button>
                    <button type="button" onClick={() => setDraftPreview(null)}>
                      放弃预览
                    </button>
                  </div>
                )}
              </>
            ) : (
              <p className="version-empty-state">
                选择草稿，或创建新的{kindNames[section as ProductionKind]}草稿。
              </p>
            )}
          </div>
        </div>
      )}

      {section === "speech" && (
        <section className="production-command">
          <h3>镜头对白容量</h3>
          <p>按实测录音全长加镜头前后留白计算，不重复添加录音内部停顿。</p>
          <div className="form-row">
            <label>
              已采用镜头
              <select
                value={shotRevisionId}
                onChange={(e) => setShotRevisionId(e.target.value)}
              >
                <option value="">选择镜头</option>
                {options("shot").map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              镜头前留白（毫秒）
              <input
                type="number"
                min="0"
                value={timingBefore}
                onChange={(e) =>
                  setTimingBefore(Math.max(0, Number(e.target.value) || 0))
                }
              />
            </label>
            <label>
              镜头后留白（毫秒）
              <input
                type="number"
                min="0"
                value={timingAfter}
                onChange={(e) =>
                  setTimingAfter(Math.max(0, Number(e.target.value) || 0))
                }
              />
            </label>
          </div>
          <fieldset>
            <legend>已采用录音版本</legend>
            {selectableSpeech.map((o) => (
              <label className="check-option" key={o.id}>
                <input
                  type="checkbox"
                  checked={selectedSpeech.includes(o.id)}
                  onChange={(e) =>
                    setSpeechRevisionIds(
                      e.target.checked
                        ? [...selectedSpeech, o.id]
                        : selectedSpeech.filter((id) => id !== o.id),
                    )
                  }
                />
                {o.label}
              </label>
            ))}
          </fieldset>
          <button
            type="button"
            disabled={!ready || !shotRevisionId}
            onClick={() =>
              void readReport(() =>
                production().timing({
                  projectId,
                  payload: {
                    shotRevisionId,
                    speechRevisionIds: selectedSpeech,
                    beforeMs: timingBefore,
                    afterMs: timingAfter,
                  },
                }),
              )
            }
          >
            检查可容纳时长
          </button>
        </section>
      )}

      {section === "video" && (
        <section className="production-command">
          <h3>镜头视频准入</h3>
          <p>
            先核对已采用文字、参考、音频路径和局部预演；只有后续显式任务授权才会提交模型。
          </p>
          <div className="form-row">
            <label>
              镜头版本
              <select
                value={shotRevisionId}
                onChange={(e) => setShotRevisionId(e.target.value)}
              >
                <option value="">选择镜头</option>
                {options("shot").map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              路径
              <select
                value={videoPath}
                onChange={(e) =>
                  setVideoPath(e.target.value as typeof videoPath)
                }
              >
                <option value="research">单镜研究试片</option>
                <option value="production">正式制作</option>
              </select>
            </label>
            <label>
              视频能力档案
              <select
                value={capabilityId}
                onChange={(e) => setCapabilityId(e.target.value)}
              >
                <option value="">选择已启用能力</option>
                {capabilities.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.modelId} · {item.region} ·{" "}
                    {item.qualityState === "verified" ? "已核验" : "研究用"}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {!capabilities.length && (
            <p className="notice">
              尚无已启用的视频能力档案；仍可继续编辑草稿和进行其他本地工作。
            </p>
          )}
          <fieldset>
            <legend>使用的已采用配音</legend>
            {selectableSpeech.map((o) => (
              <label key={o.id} className="check-option">
                <input
                  type="checkbox"
                  checked={selectedSpeech.includes(o.id)}
                  onChange={(e) =>
                    setSpeechRevisionIds(
                      e.target.checked
                        ? [...selectedSpeech, o.id]
                        : selectedSpeech.filter((id) => id !== o.id),
                    )
                  }
                />
                {o.label}
              </label>
            ))}
          </fieldset>
          <button
            type="button"
            disabled={!ready || !shotRevisionId || !capabilityId}
            onClick={() =>
              void readReport(() =>
                production().readiness({
                  projectId,
                  payload: {
                    shotRevisionId,
                    speechRevisionIds: selectedSpeech,
                    capabilityId,
                    path: videoPath,
                  },
                }),
              )
            }
          >
            查看准入缺口
          </button>
          <p>
            已生成的原片通过项目工具导入并保留原件，再到「原片观察」标记可用范围。
          </p>
          <button type="button" onClick={onOpenMedia}>
            打开素材库
          </button>
        </section>
      )}

      {report &&
        ["speech", "video", "timeline", "rights", "delivery"].includes(
          section,
        ) && (
          <section className="production-result" aria-live="polite">
            <h3>本地检查结果</h3>
            {typeof report.suitable === "boolean" && (
              <p>
                {report.suitable ? "镜头容量合适" : "镜头容量不足"}： 需要{" "}
                {report.requiredMs} 毫秒，计划 {report.plannedMs} 毫秒，短缺{" "}
                {report.shortageMs} 毫秒。
                {report.method === "estimated" && " 此结果只按估算时间计算。"}
              </p>
            )}
            {typeof report.ready === "boolean" && (
              <p>{report.ready ? "已通过当前本地准入条件" : "还有准入缺口"}</p>
            )}
            {report.blockers?.length ? (
              <ul>
                {report.blockers.map((b, i) => (
                  <li key={i}>{b}</li>
                ))}
              </ul>
            ) : null}
            {report.warnings?.length ? (
              <ul>
                {report.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            ) : null}
            {report.shortageMs && (
              <p>新视频长度不足 {report.shortageMs} 毫秒；原剪辑保持不变。</p>
            )}
          </section>
        )}

      {section === "timeline" && (
        <section className="production-command">
          <h3>预演、替换与混音</h3>
          <p>下面预览依据已采用时间线；编辑预览不会自动写回或替换当前版本。</p>
          <label>
            已采用时间线
            <select
              value={timelineRevisionId}
              onChange={(e) => setTimelineRevisionId(e.target.value)}
            >
              <option value="">选择版本</option>
              {options("timeline").map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <div className="production-actions">
            <button
              type="button"
              disabled={!timelineRevisionId || !ready}
              onClick={() =>
                void run(async () => {
                  const result = await production().renderPlan({
                    projectId,
                    payload: {
                      timelineRevisionId,
                      burnSubtitles,
                    },
                  });
                  setMessage(
                    result.ok
                      ? "渲染计划已编译。检查素材引用后可启动本地静态预演。"
                      : result.error.message,
                  );
                })
              }
            >
              查看渲染计划
            </button>
            <button
              type="button"
              disabled={!timelineRevisionId || !writeAllowed}
              onClick={() => void command("animatic", { timelineRevisionId })}
            >
              生成静态预演
            </button>
          </div>
          <div className="form-row">
            <label>
              要替换的片段
              <select
                value={chosenClip}
                onChange={(e) => setChosenClip(e.target.value)}
              >
                <option value="">选择片段</option>
                {timelineClips.map((clip, i) => (
                  <option key={word(clip.id)} value={word(clip.id)}>
                    片段 {i + 1} · {number(clip.durationMs)} 毫秒
                  </option>
                ))}
              </select>
            </label>
            <label>
              候选视频
              <select
                value={replacementMediaId}
                onChange={(e) => setReplacementMediaId(e.target.value)}
              >
                <option value="">选择素材</option>
                {media
                  .filter(
                    (m) =>
                      m.mime === "video/mp4" && m.availability === "available",
                  )
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {mediaName(m)}
                    </option>
                  ))}
              </select>
            </label>
            <button
              type="button"
              disabled={
                !chosenClip || !replacementMediaId || !timelineRevisionId
              }
              onClick={() =>
                void readReport(() =>
                  production().replacement({
                    projectId,
                    payload: {
                      timelineRevisionId,
                      clipId: chosenClip,
                      newMediaId: replacementMediaId,
                    },
                  }),
                )
              }
            >
              预览替换影响
            </button>
          </div>
          <h4>对白优先混音预览</h4>
          <div className="form-row">
            <label>
              降低音乐（dB）
              <input
                type="number"
                min="0"
                max="48"
                value={duckDb}
                onChange={(e) => setDuckDb(Number(e.target.value))}
              />
            </label>
            <label>
              压低前沿（毫秒）
              <input
                type="number"
                min="0"
                value={attackMs}
                onChange={(e) => setAttackMs(Number(e.target.value))}
              />
            </label>
            <label>
              恢复时间（毫秒）
              <input
                type="number"
                min="0"
                value={releaseMs}
                onChange={(e) => setReleaseMs(Number(e.target.value))}
              />
            </label>
            <button
              type="button"
              disabled={!timelineRevisionId || !writeAllowed}
              onClick={() => void previewDucking()}
            >
              生成音量包络预览
            </button>
          </div>
          {draftPreview && (
            <div className="production-preview">
              <p>{previewNote}</p>
              <button
                type="button"
                disabled={
                  !engine ||
                  draftKind !== "timeline" ||
                  previewDraftId !== activeDraftId ||
                  disabled
                }
                onClick={() => void acceptPreview()}
              >
                写入当前时间线草稿
              </button>
              <button type="button" onClick={() => setDraftPreview(null)}>
                放弃
              </button>
            </div>
          )}
        </section>
      )}

      {section === "rights" && (
        <RightsSection
          projectId={projectId}
          media={media}
          rights={rights}
          current={right}
          onChange={setRight}
          disabled={!writeAllowed}
          onRefresh={() => void loadRights()}
          onSave={() => {
            if (right)
              void command("saveRights", { evidence: right }, right.id);
          }}
          onOpenMedia={onOpenMedia}
        />
      )}

      {section === "delivery" && (
        <DeliverySection
          projectId={projectId}
          ready={ready}
          disabled={!writeAllowed}
          index={index}
          media={media}
          issues={issues}
          issueCursor={issueCursor}
          onMore={() => void loadIssues(issueCursor)}
          onRefresh={() => void loadIssues(null)}
          onFocusArtifact={onFocusArtifact}
          reason={issueReason}
          onReason={setIssueReason}
          onDecide={(issueId, change) =>
            void command("decideIssue", change, issueId)
          }
          timelineRevisionId={timelineRevisionId}
          onTimeline={setTimelineRevisionId}
          burnSubtitles={burnSubtitles}
          onBurn={setBurnSubtitles}
          exportChoice={exportChoice}
          onChoice={() => void chooseTarget("export")}
          onExport={() =>
            void command("exportFilm", {
              timelineRevisionId,
              targetGrantId: exportChoice?.grantId,
              burnSubtitles,
              overwriteConfirmed: exportChoice?.exists ?? false,
            })
          }
          onChecks={() => void runLocalChecks()}
          exportId={exportId}
          exportStatus={exportStatus}
          onExportRefresh={() => void inspectExport()}
          job={job}
        />
      )}

      {section === "diagnostic" && (
        <DiagnosticsPanel
          ready={ready}
          active={page === "项目工具"}
          projectId={projectId}
        />
      )}
      {pending && (
        <div className="notice" role="status">
          <p>操作结果待核对。请查询原操作；保留了操作编号。</p>
          <button
            type="button"
            disabled={!ready || busy}
            onClick={() => void queryPending()}
          >
            查询原操作
          </button>
          <button
            type="button"
            disabled={!ready || busy || session.mode === "read"}
            onClick={() => void action(() => submit(pending))}
          >
            用原编号重试
          </button>
        </div>
      )}
    </section>
  );

  async function loadRights() {
    const result = await production().rights({ projectId });
    if (result.ok) setRights(result.data.items);
    else setMessage(result.error.message);
  }
  async function loadIssues(cursor: string | null) {
    const result = await production().issues({ projectId, cursor, limit: 50 });
    if (result.ok) {
      setIssues(
        cursor
          ? (current) => [...current, ...result.data.items]
          : result.data.items,
      );
      setIssueCursor(result.data.nextCursor);
    } else setMessage(result.error.message);
  }
  async function chooseTarget(purpose: "export" | "diagnostic") {
    const result = await production().chooseTarget({ purpose });
    if (!result.ok) return setMessage(result.error.message);
    setExportChoice(result.data);
  }
  async function inspectExport() {
    if (!exportId) return;
    const result = await production().getExport({ projectId, exportId });
    if (!result.ok) return setMessage(result.error.message);
    setExportStatus(result.data.state);
    const local = await window.desktop.projects.media.job({
      projectId,
      jobId: result.data.jobId,
    });
    if (local.ok) setJob(local.data);
  }
  async function runLocalChecks() {
    if (!timelineRevisionId || !(await flushAll())) return;
    const timeline = index.adopted.find(
      (item) => item.revisionId === timelineRevisionId,
    );
    if (timeline) onFocusArtifact(timeline.artifactId);
  }
  async function command(
    method: Pending["method"],
    payload: Row,
    resourceId?: string,
  ) {
    if (!writeAllowed) return;
    await run(async () => {
      if (!(await flushAll())) return setMessage("请先核对草稿保存状态。");
      const project =
        method === "diagnostic"
          ? null
          : await window.desktop.projects.drafts.project({ projectId });
      if (project && !project.ok) return setMessage(project.error.message);
      const pendingOperation: Pending = {
        method,
        payload,
        id: uid(),
        revision: project?.ok ? project.data.revision : 0,
        resourceId,
      };
      setPending(pendingOperation);
      await submit(pendingOperation);
    });
  }
  async function submit(item: Pending) {
    const command = {
      clientOperationId: item.id,
      expectedRevision: item.revision,
      payload: item.payload,
    };
    const api = production();
    async function invoke(): Promise<ProjectResult<Receipt> | null> {
      if (item.method === "animatic") {
        const input = productionRoutes.animatic.input.safeParse({
          projectId,
          command,
        });
        return input.success ? api.animatic(input.data) : null;
      }
      if (item.method === "exportFilm") {
        const input = productionRoutes.exportFilm.input.safeParse({
          projectId,
          command,
        });
        return input.success ? api.exportFilm(input.data) : null;
      }
      if (item.method === "diagnostic") {
        const input = productionRoutes.diagnostic.input.safeParse({ command });
        return input.success ? api.diagnostic(input.data) : null;
      }
      if (item.method === "saveRights") {
        const input = productionRoutes.saveRights.input.safeParse({
          projectId,
          evidenceId: item.resourceId,
          command,
        });
        return input.success ? api.saveRights(input.data) : null;
      }
      const input = productionRoutes.decideIssue.input.safeParse({
        projectId,
        issueId: item.resourceId,
        command,
      });
      return input.success ? api.decideIssue(input.data) : null;
    }
    const result = await invoke();
    if (!result) {
      setPending(null);
      setMessage("操作输入不符合当前协议，请核对草稿和所选目标。");
      return;
    }
    if (!result.ok) {
      setMessage(result.error.message);
      if (
        [
          "REQUEST_INVALID",
          "VALIDATION_FAILED",
          "REVISION_CONFLICT",
          "PROJECT_READ_ONLY",
          "CHECK_REQUIRED",
          "CHECK_BLOCKED",
          "OBJECT_NOT_FOUND",
          "GRANT_REJECTED",
          "OVERWRITE_CONFIRMATION_REQUIRED",
          "EXPORT_TARGET_IN_PROJECT",
          "PROJECT_BUSY",
          "TIMELINE_INVALID",
          "TIMELINE_GAP",
          "TIMELINE_MEDIA_SHORTAGE",
          "MEDIA_MISSING",
          "MEDIA_NOT_AVAILABLE",
          "MEDIA_HASH_MISMATCH",
          "MEDIA_TOOLS_UNAVAILABLE",
          "RENDER_SIZE_LIMIT",
          "RIGHTS_VERIFICATION_REQUIRED",
        ].includes(result.error.code)
      ) {
        setPending(null);
        if (
          item.method === "exportFilm" &&
          [
            "GRANT_REJECTED",
            "OVERWRITE_CONFIRMATION_REQUIRED",
            "EXPORT_TARGET_IN_PROJECT",
          ].includes(result.error.code)
        )
          setExportChoice(null);
      }
      return;
    }
    if (
      result.data.operationId !== item.id ||
      result.data.committedRevision !==
        (item.method === "diagnostic" ? 0 : item.revision + 1)
    ) {
      setMessage("回执不匹配，请查询原操作。");
      return;
    }
    await complete(item, result.data);
  }
  async function complete(item: Pending, receipt: Receipt) {
    setPending(null);
    if (item.method !== "diagnostic") {
      engine?.advanceProjectRevision(item.revision, receipt.committedRevision);
      storyEngine?.advanceProjectRevision(
        item.revision,
        receipt.committedRevision,
      );
      contentEngine?.advanceProjectRevision(
        item.revision,
        receipt.committedRevision,
      );
    }
    if (item.method === "exportFilm") {
      setExportId(receipt.resourceId);
      setExportStatus("pending");
    }
    setMessage(
      item.method === "diagnostic"
        ? "诊断包本地作业已登记；不会自动分享。"
        : item.method === "exportFilm"
          ? "导出作业已登记；目标成功发布前不会标为完成。"
          : item.method === "animatic"
            ? "本地静态预演作业已登记。"
            : "记录已保存；请复检相关采用内容。",
    );
    await refresh();
  }
  async function queryPending() {
    if (!pending) return;
    const result =
      pending.method === "diagnostic"
        ? await window.desktop.projects.operation({ operationId: pending.id })
        : await window.desktop.projects.drafts.operation({
            projectId,
            operationId: pending.id,
          });
    if (!result.ok) return setMessage(result.error.message);
    if (
      result.data.receipt.operationId !== pending.id ||
      result.data.receipt.committedRevision !==
        (pending.method === "diagnostic" ? 0 : pending.revision + 1)
    )
      return setMessage("原操作回执不匹配。");
    await complete(pending, result.data.receipt);
  }
}

function RightsSection({
  projectId,
  media,
  rights,
  current,
  onChange,
  disabled,
  onRefresh,
  onSave,
  onOpenMedia,
}: {
  projectId: string;
  media: Media[];
  rights: Right[];
  current: Right | null;
  onChange: (next: Right) => void;
  disabled: boolean;
  onRefresh: () => void;
  onSave: () => void;
  onOpenMedia: () => void;
}) {
  const update = (change: Partial<Right>) =>
    current && onChange({ ...current, ...change });
  return (
    <section className="production-command">
      <h3>声音素材来源与使用范围</h3>
      <p>
        导入音乐、音效或配音后记录来源、用途和证据。声明不等于核对完成；正式采用链需要检查。
      </p>
      <button type="button" onClick={onOpenMedia}>
        导入声音素材
      </button>
      <button type="button" onClick={onRefresh}>
        刷新来源记录
      </button>
      <div className="production-rights">
        <aside>
          {rights.map((item) => (
            <button type="button" key={item.id} onClick={() => onChange(item)}>
              {item.source || "未命名来源"}
              <small>{item.state === "verified" ? "已核对" : "待核对"}</small>
            </button>
          ))}
          <button
            type="button"
            disabled={disabled}
            onClick={() =>
              onChange({
                id: uid(),
                mediaId: "",
                source: "",
                use: "",
                evidenceMediaIds: [],
                state: "unverified",
                explanation: "",
              })
            }
          >
            新增来源记录
          </button>
        </aside>
        {current && (
          <div>
            <div className="form-row">
              <label>
                当前素材
                <select
                  value={current.mediaId}
                  disabled={disabled}
                  onChange={(e) => update({ mediaId: e.target.value })}
                >
                  <option value="">选择素材</option>
                  {media
                    .filter((m) => m.availability === "available")
                    .map((m) => (
                      <option key={m.id} value={m.id}>
                        {mediaName(m)}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                核对状态
                <select
                  value={current.state}
                  disabled={disabled}
                  onChange={(e) =>
                    update({ state: e.target.value as Right["state"] })
                  }
                >
                  <option value="unverified">待核对</option>
                  <option value="recheck">需复核</option>
                  <option value="verified">已核对（需要关联证据）</option>
                </select>
              </label>
            </div>
            <label>
              来源
              <input
                value={current.source}
                maxLength={2000}
                disabled={disabled}
                onChange={(e) => update({ source: e.target.value })}
              />
            </label>
            <label>
              使用范围
              <input
                value={current.use}
                maxLength={2000}
                disabled={disabled}
                onChange={(e) => update({ use: e.target.value })}
              />
            </label>
            <fieldset>
              <legend>关联的证据素材</legend>
              {media.map((m) => (
                <label key={m.id} className="check-option">
                  <input
                    type="checkbox"
                    disabled={disabled}
                    checked={current.evidenceMediaIds.includes(m.id)}
                    onChange={(e) =>
                      update({
                        evidenceMediaIds: e.target.checked
                          ? [...current.evidenceMediaIds, m.id]
                          : current.evidenceMediaIds.filter(
                              (id) => id !== m.id,
                            ),
                      })
                    }
                  />
                  {mediaName(m)}
                </label>
              ))}
            </fieldset>
            <label>
              核对依据与限制
              <textarea
                value={current.explanation}
                maxLength={4000}
                disabled={disabled}
                onChange={(e) => update({ explanation: e.target.value })}
              />
            </label>
            <button
              type="button"
              disabled={
                disabled ||
                !current.mediaId ||
                !current.source.trim() ||
                !current.use.trim()
              }
              onClick={onSave}
            >
              保存来源证据
            </button>
          </div>
        )}
      </div>
      <small>项目 {projectId.slice(0, 8)} · 证据不会自动授予使用权</small>
    </section>
  );
}

function DeliverySection({
  ready,
  disabled,
  index,
  media,
  issues,
  issueCursor,
  onMore,
  onRefresh,
  onFocusArtifact,
  reason,
  onReason,
  onDecide,
  timelineRevisionId,
  onTimeline,
  burnSubtitles,
  onBurn,
  exportChoice,
  onChoice,
  onExport,
  onChecks,
  exportId,
  exportStatus,
  onExportRefresh,
  job,
}: {
  projectId: string;
  ready: boolean;
  disabled: boolean;
  index: { drafts: Summary[]; adopted: Adopted[] };
  media: Media[];
  issues: Issue[];
  issueCursor: string | null;
  onMore: () => void;
  onRefresh: () => void;
  onFocusArtifact: (id: string) => void;
  reason: string;
  onReason: (v: string) => void;
  onDecide: (issueId: string, value: Row) => void;
  timelineRevisionId: string;
  onTimeline: (id: string) => void;
  burnSubtitles: boolean;
  onBurn: (v: boolean) => void;
  exportChoice: Choice | null;
  onChoice: () => void;
  onExport: () => void;
  onChecks: () => void;
  exportId: string;
  exportStatus: string;
  onExportRefresh: () => void;
  job: MediaJob | null;
}) {
  const [issueEvidence, setIssueEvidence] = useState<Record<string, string[]>>(
    {},
  );
  const ruleNames: Record<string, string> = {
    structural: "内容结构",
    references: "素材引用",
    rights: "来源与使用范围",
    subtitleTiming: "字幕时间",
    mix: "对白与音乐混合",
    export: "导出准入",
    timelinePlacement: "时间线位置",
    dialogueAudio: "对白配音",
  };
  const statusNames: Record<Issue["status"], string> = {
    open: "待处理",
    fixing: "处理中",
    recheck: "待复检",
    resolved: "已解决",
    accepted_deviation: "已记录偏差",
  };
  return (
    <section className="production-delivery">
      <div className="section-heading">
        <h3>检查与交付</h3>
        <span>仅使用当前采用链，不以问题数代替严重性</span>
      </div>
      <section className="production-command">
        <h4>当前采用的时间线</h4>
        <label>
          版本
          <select
            value={timelineRevisionId}
            onChange={(e) => onTimeline(e.target.value)}
          >
            <option value="">选择时间线</option>
            {index.adopted
              .filter((a) => a.kind === "timeline")
              .map((a) => (
                <option key={a.revisionId} value={a.revisionId}>
                  {a.revisionId.slice(0, 8)} ·{" "}
                  {a.confirmed ? "已确认" : "待确认"}
                  {a.needsUpdate ? " · 需要更新" : ""}
                </option>
              ))}
          </select>
        </label>
        <button
          type="button"
          disabled={disabled || !timelineRevisionId}
          onClick={onChecks}
        >
          前往版本区运行本地结构检查
        </button>
        <button type="button" disabled={!ready} onClick={onRefresh}>
          刷新问题列表
        </button>
      </section>
      <section className="production-issues" aria-label="待处理问题">
        {issues.length ? (
          issues.map((issue) => (
            <article key={issue.id}>
              <header>
                <strong>{ruleNames[issue.ruleId] ?? "专项检查"}</strong>
                <span>
                  {issue.severity === "blocking"
                    ? "阻断"
                    : issue.severity === "unknown_required"
                      ? "必须补证"
                      : "偏差"}{" "}
                  · {statusNames[issue.status]}
                </span>
              </header>
              <p>
                {Object.hasOwn(projectMessages, issue.message)
                  ? projectMessages[issue.message]
                  : issue.message}
              </p>
              {issue.time && (
                <p>
                  位置：{issue.time.startMs}–{issue.time.endMs} 毫秒
                </p>
              )}
              {issue.evidence && <p>依据：{issue.evidence}</p>}
              {issue.limitations && <p>限制：{issue.limitations}</p>}
              <button
                type="button"
                onClick={() => onFocusArtifact(issue.artifactId)}
              >
                查看相关版本
              </button>
              <label>
                处理说明
                <input
                  value={reason}
                  maxLength={2000}
                  disabled={disabled}
                  onChange={(e) => onReason(e.target.value)}
                />
              </label>
              <fieldset>
                <legend>补充证据素材</legend>
                {media.filter((item) => item.availability === "available")
                  .length ? (
                  media
                    .filter((item) => item.availability === "available")
                    .map((item) => (
                      <label key={item.id} className="check-option">
                        <input
                          type="checkbox"
                          disabled={disabled}
                          checked={(issueEvidence[issue.id] ?? []).includes(
                            item.id,
                          )}
                          onChange={(event) =>
                            setIssueEvidence((current) => {
                              const ids = current[issue.id] ?? [];
                              return {
                                ...current,
                                [issue.id]: event.target.checked
                                  ? [...ids, item.id]
                                  : ids.filter((id) => id !== item.id),
                              };
                            })
                          }
                        />
                        {mediaName(item)}
                      </label>
                    ))
                ) : (
                  <p>尚无可用证据素材，可先在项目工具导入。</p>
                )}
              </fieldset>
              <button
                type="button"
                disabled={
                  disabled || !reason.trim() || !issueEvidence[issue.id]?.length
                }
                onClick={() =>
                  onDecide(issue.id, {
                    action: "attach_evidence",
                    reason,
                    evidenceMediaIds: issueEvidence[issue.id],
                  })
                }
              >
                附证并请求复检
              </button>
              <button
                type="button"
                disabled={disabled || !reason.trim()}
                onClick={() =>
                  onDecide(issue.id, {
                    action: "request_recheck",
                    reason,
                    evidenceMediaIds: [],
                  })
                }
              >
                请求复检
              </button>
              {(issue.severity === "deviation" ||
                issue.severity === "advice") && (
                <button
                  type="button"
                  disabled={disabled || !reason.trim()}
                  onClick={() =>
                    onDecide(issue.id, {
                      action: "accept_deviation",
                      reason,
                      evidenceMediaIds: [],
                    })
                  }
                >
                  记录接受偏差
                </button>
              )}
            </article>
          ))
        ) : (
          <p>当前列表没有问题记录；导出仍需有效的本地检查与确认。</p>
        )}
        {issueCursor && (
          <button type="button" onClick={onMore}>
            加载更多问题
          </button>
        )}
      </section>
      <section className="production-command">
        <h4>正式导出</h4>
        <p>
          导出冻结所选时间线和字幕开关。外部目标发布成功后才会显示完成；项目内成片会保留。
        </p>
        <label className="check-option">
          <input
            type="checkbox"
            checked={burnSubtitles}
            onChange={(e) => onBurn(e.target.checked)}
            disabled={disabled}
          />
          烧录后期字幕
        </label>
        <button type="button" disabled={disabled} onClick={onChoice}>
          选择原生保存目标
        </button>
        <span>{exportChoice?.name ?? "尚未选择目标"}</span>
        {exportChoice?.exists && (
          <p className="notice">
            目标已存在。确认导出后，只有成功完成才会替换该文件。
          </p>
        )}
        <button
          type="button"
          disabled={disabled || !timelineRevisionId || !exportChoice}
          onClick={onExport}
        >
          核对并启动本地导出
        </button>
        {exportId && (
          <div className="production-preview">
            <p>
              导出 {exportId.slice(0, 8)}：
              {jobStateNames[exportStatus] ?? "待查询"}
            </p>
            {job && (
              <p>
                本地作业 {jobStateNames[job.state] ?? "待查询"} ·{" "}
                {Math.round(job.progress * 100)}%
              </p>
            )}
            <button type="button" onClick={onExportRefresh}>
              刷新导出状态
            </button>
          </div>
        )}
      </section>
    </section>
  );
}
