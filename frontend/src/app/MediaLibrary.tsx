import { useCallback, useEffect, useRef, useState } from "react";
import { z } from "zod";
import {
  toolsCommandSchema,
  importMediaSchema,
  relocateMediaSchema,
  cancelJobSchema,
} from "../../electron/shared/media";
import type {
  Media,
  MediaJob,
  ToolSettings,
  ImportMedia,
} from "../../electron/shared/media";
import {
  projectError,
  projectUuid,
  type ProjectSession,
} from "../../electron/shared/projects";

const pendingSchema = z.discriminatedUnion("kind", [
  z.strictObject({
    id: projectUuid,
    scope: z.literal("tools"),
    label: z.literal("工具配置"),
    kind: z.literal("tools"),
    input: toolsCommandSchema,
  }),
  z.strictObject({
    id: projectUuid,
    scope: z.literal("project"),
    label: z.literal("素材导入"),
    kind: z.literal("import"),
    input: importMediaSchema,
  }),
  z.strictObject({
    id: projectUuid,
    scope: z.literal("project"),
    label: z.literal("重新定位"),
    kind: z.literal("relocate"),
    input: relocateMediaSchema,
  }),
  z.strictObject({
    id: projectUuid,
    scope: z.literal("project"),
    label: z.literal("取消作业"),
    kind: z.literal("cancel"),
    input: cancelJobSchema,
  }),
]);
type Pending = z.infer<typeof pendingSchema>;
type Choice = { grantId: string; name: string };
const uncertain = new Set([
  "BACKEND_UNAVAILABLE",
  "PROTOCOL_INVALID",
  "SESSION_EXPIRED",
]);
const jobLabels: Record<MediaJob["state"], string> = {
  queued: "准备导入",
  running: "复制与校验中",
  succeeded: "已完成",
  failed: "未完成",
  cancelled: "已取消",
};
const availabilityLabels: Record<Media["availability"], string> = {
  staging: "准备中",
  available: "可预览",
  missing: "文件缺失",
  quarantined: "需要核对文件",
};

export function MediaLibrary({
  session,
  ready,
  locked,
  action,
  prepareMutation,
}: {
  session: ProjectSession;
  ready: boolean;
  locked: boolean;
  action: (work: () => Promise<void>) => Promise<void>;
  prepareMutation: () => Promise<boolean>;
}) {
  const [settings, setSettings] = useState<ToolSettings | null>(null);
  const [jobs, setJobs] = useState<MediaJob[]>([]);
  const [items, setItems] = useState<Media[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [purpose, setPurpose] =
    useState<ImportMedia["command"]["payload"]["purpose"]>("reference");
  const pendingKey = `media-operation:${session.projectId}`;
  const [pending, updatePending] = useState<Pending | null>(() => {
    try {
      const parsed = pendingSchema.safeParse(
        JSON.parse(localStorage.getItem(pendingKey) ?? "null"),
      );
      if (!parsed.success) return null;
      const saved = parsed.data;
      const command =
        saved.kind === "tools" ? saved.input : saved.input.command;
      return command.clientOperationId === saved.id &&
        (saved.kind === "tools" || saved.input.projectId === session.projectId)
        ? saved
        : null;
    } catch {
      return null;
    }
  });
  function setPending(value: Pending | null) {
    // Preserve exact commands for explicit idempotent retries; never store file paths.
    if (value) localStorage.setItem(pendingKey, JSON.stringify(value));
    else localStorage.removeItem(pendingKey);
    updatePending(value);
  }
  const [message, setMessage] = useState("");
  const [pollError, setPollError] = useState("");
  const [cancelId, setCancelId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<Media | null>(null);
  const mounted = useRef(false);
  const epoch = useRef(0);
  const pageRequest = useRef(0);
  const context = useRef({ ready, sessionId: session.projectSessionId });
  if (
    context.current.ready !== ready ||
    context.current.sessionId !== session.projectSessionId
  ) {
    epoch.current++;
    context.current = { ready, sessionId: session.projectSessionId };
  }
  const alive = (token: number) => mounted.current && epoch.current === token;
  const projectId = session.projectId;
  const bridge = window.desktop.projects.media;
  const disabled = !ready || locked || session.mode === "read" || !!pending;

  const reload = useCallback(async () => {
    const token = epoch.current;
    const request = ++pageRequest.current;
    const result = await window.desktop.projects.media.list({
      projectId,
      limit: 24,
    });
    if (
      !mounted.current ||
      epoch.current !== token ||
      request !== pageRequest.current
    )
      return;
    if (result.ok) {
      setItems(result.data.items);
      setCursor(result.data.nextCursor);
      setLoaded(true);
      setPreview((current) =>
        current
          ? (result.data.items.find(
              (item) =>
                item.id === current.id && item.availability === "available",
            ) ?? null)
          : null,
      );
    } else setMessage(projectError(result.error.code).message);
  }, [projectId]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      epoch.current++;
    };
  }, []);

  useEffect(() => {
    if (!ready) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let signature = "";
    const token = epoch.current;
    void bridge
      .settings()
      .then((result) => {
        if (!active || !alive(token)) return;
        if (result.ok) setSettings(result.data);
        else setMessage(projectError(result.error.code).message);
      })
      .catch(() => {
        if (active && alive(token))
          setMessage("无法读取本地工具设置，请恢复连接后刷新。");
      });
    const poll = async () => {
      try {
        const result = await bridge.jobs({ projectId });
        if (!active || !alive(token)) return;
        if (result.ok) {
          setJobs(result.data);
          setPollError("");
          const next = JSON.stringify(
            result.data.map((job) => [job.id, job.state, job.resultId]),
          );
          if (next !== signature) {
            signature = next;
            await reload();
          }
        } else setPollError(projectError(result.error.code).message);
      } catch {
        if (active && alive(token))
          setPollError("作业状态暂时无法读取，恢复连接后会继续核对。");
      } finally {
        if (active && alive(token)) timer = setTimeout(() => void poll(), 1500);
      }
    };
    void poll();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [ready, session.projectSessionId, projectId, bridge, reload]);

  async function refreshTools(token: number) {
    const result = await bridge.settings();
    if (alive(token) && result.ok) setSettings(result.data);
  }
  async function query(operation: Pending, token = epoch.current) {
    try {
      const result =
        operation.scope === "tools"
          ? await window.desktop.projects.operation({
              operationId: operation.id,
            })
          : await window.desktop.projects.drafts.operation({
              projectId,
              operationId: operation.id,
            });
      if (!alive(token)) return;
      if (result.ok) {
        setPending(null);
        if (operation.label === "素材导入") setChoice(null);
        if (operation.label === "取消作业") setCancelId(null);
        setMessage(`${operation.label}已受理，可在下方查看结果。`);
        if (operation.scope === "tools") await refreshTools(token);
        else await reload();
      } else
        setMessage(
          `原操作尚未确认。${projectError(result.error.code).message} 可继续查询或重试原操作，编号和内容保持不变。`,
        );
    } catch {
      if (alive(token))
        setMessage("结果仍待核对，原操作编号已保留。请恢复连接后查询。");
    }
  }
  async function send(operation: Pending, token: number) {
    if (!alive(token)) return;
    setPending(operation);
    try {
      const result =
        operation.kind === "tools"
          ? await bridge.configureTools(operation.input)
          : operation.kind === "import"
            ? await bridge.import(operation.input)
            : operation.kind === "relocate"
              ? await bridge.relocate(operation.input)
              : await bridge.cancel(operation.input);
      if (!alive(token)) return;
      if (result.ok) {
        setPending(null);
        if (operation.label === "素材导入") setChoice(null);
        if (operation.label === "取消作业") setCancelId(null);
        setMessage(`${operation.label}已受理，可在下方查看结果。`);
        if (operation.scope === "tools") await refreshTools(token);
        else await reload();
      } else if (uncertain.has(result.error.code)) {
        await query(operation, token);
      } else {
        setPending(null);
        setMessage(projectError(result.error.code).message);
      }
    } catch {
      if (alive(token)) await query(operation, token);
    }
  }
  async function configure() {
    const token = epoch.current;
    if (!(await prepareMutation()) || !alive(token)) return;
    const selected = await bridge.chooseFile({ purpose: "ffmpeg" });
    if (!alive(token)) return;
    if (!selected.ok) {
      setMessage(projectError(selected.error.code).message);
      return;
    }
    if (!selected.data) return;
    const current = await bridge.settings();
    if (!alive(token)) return;
    if (!current.ok) {
      setMessage(projectError(current.error.code).message);
      return;
    }
    const id = crypto.randomUUID();
    await send(
      {
        id,
        scope: "tools",
        label: "工具配置",
        kind: "tools",
        input: {
          clientOperationId: id,
          expectedRevision: current.data.revision,
          payload: { ffmpegGrantId: selected.data!.grantId },
        },
      },
      token,
    );
  }
  async function selectImport() {
    const token = epoch.current;
    if (!(await prepareMutation()) || !alive(token)) return;
    const result = await bridge.chooseFile({ purpose: "importMedia" });
    if (!alive(token)) return;
    if (result.ok) {
      if (result.data) setChoice(result.data);
    } else setMessage(projectError(result.error.code).message);
  }
  async function mutate(kind: "import" | "cancel" | "relocate", media?: Media) {
    const token = epoch.current;
    if (!(await prepareMutation()) || !alive(token)) return;
    let selected = choice;
    if (kind === "relocate") {
      const result = await bridge.chooseFile({ purpose: "importMedia" });
      if (!alive(token)) return;
      if (!result.ok) {
        setMessage(projectError(result.error.code).message);
        return;
      }
      if (!result.data) return;
      selected = result.data;
    }
    const project = await window.desktop.projects.drafts.project({ projectId });
    if (!alive(token)) return;
    if (!project.ok) {
      setMessage(projectError(project.error.code).message);
      return;
    }
    const id = crypto.randomUUID();
    const common = {
      clientOperationId: id,
      expectedRevision: project.data.revision,
    };
    if (kind === "import" && selected) {
      await send(
        {
          id,
          scope: "project",
          kind: "import",
          label: "素材导入",
          input: {
            projectId,
            command: {
              ...common,
              payload: { fileGrantId: selected!.grantId, purpose },
            },
          },
        },
        token,
      );
    } else if (kind === "relocate" && selected && media) {
      await send(
        {
          id,
          scope: "project",
          kind: "relocate",
          label: "重新定位",
          input: {
            projectId,
            mediaId: media.id,
            command: {
              ...common,
              payload: {
                fileGrantId: selected!.grantId,
                expectedHash: media.sha256,
              },
            },
          },
        },
        token,
      );
    } else if (kind === "cancel" && cancelId && reason.trim()) {
      await send(
        {
          id,
          scope: "project",
          kind: "cancel",
          label: "取消作业",
          input: {
            projectId,
            jobId: cancelId,
            command: { ...common, payload: { reason: reason.trim() } },
          },
        },
        token,
      );
    }
  }
  async function more() {
    if (!cursor) return;
    const token = epoch.current;
    const request = ++pageRequest.current;
    const result = await bridge.list({ projectId, cursor, limit: 24 });
    if (!alive(token) || request !== pageRequest.current) return;
    if (result.ok) {
      setItems((previous) => [
        ...previous,
        ...result.data.items.filter(
          (item) => !previous.some((old) => old.id === item.id),
        ),
      ]);
      setCursor(result.data.nextCursor);
    } else setMessage(projectError(result.error.code).message);
  }

  return (
    <section className="media-library" aria-label="项目素材">
      <div className="section-heading">
        <h2>项目素材</h2>
        <span>本地导入，不产生模型费用</span>
      </div>
      <div className="media-tools">
        <div>
          <h3>本地媒体工具</h3>
          <p>
            {settings
              ? settings.ffmpegConfigured
                ? "FFmpeg 已配置，可校验图片、音频与视频。"
                : "尚未配置 FFmpeg。你仍可继续编写和保存故事草稿。"
              : "正在读取工具配置…"}
          </p>
        </div>
        <button disabled={disabled} onClick={() => void action(configure)}>
          {settings?.ffmpegConfigured ? "更换 FFmpeg" : "选择 FFmpeg"}
        </button>
      </div>
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      {pending && (
        <div className="media-pending">
          <p>正在核对{pending.label}，已保留本次操作。</p>
          <button
            disabled={!ready || locked}
            onClick={() => void action(() => query(pending))}
          >
            查询原媒体操作
          </button>
          <button
            disabled={!ready || locked || session.mode === "read"}
            onClick={() =>
              void action(async () => {
                const token = epoch.current;
                if (await prepareMutation()) await send(pending, token);
              })
            }
          >
            重试原媒体操作
          </button>
        </div>
      )}
      <div className="media-import">
        <label>
          素材用途
          <select
            value={purpose}
            disabled={disabled}
            onChange={(event) =>
              setPurpose(event.target.value as typeof purpose)
            }
          >
            <option value="reference">视觉参考</option>
            <option value="speech">对白与配音</option>
            <option value="video">视频片段</option>
            <option value="music">音乐</option>
            <option value="sfx">音效</option>
            <option value="evidence">核对依据</option>
          </select>
        </label>
        <button
          disabled={disabled || !settings?.ffmpegConfigured}
          onClick={() => void action(selectImport)}
        >
          选择素材文件
        </button>
        <span className="media-choice">{choice?.name ?? "尚未选择文件"}</span>
        <button
          className="primary-button"
          disabled={disabled || !choice || !settings?.ffmpegConfigured}
          onClick={() => void action(() => mutate("import"))}
        >
          导入素材
        </button>
      </div>
      <p className="muted">
        支持 PNG、JPEG、MP4、WAV、MP3、M4A，单文件不超过 2
        GiB。文件将复制到项目中，原文件保留。
      </p>
      {pollError && (
        <p role="alert" className="notice">
          {pollError}
        </p>
      )}
      {!!jobs.length && (
        <div className="media-jobs">
          <h3>导入与校验作业</h3>
          <ul>
            {jobs.map((job) => (
              <li key={job.id}>
                <div>
                  <strong>{jobLabels[job.state]}</strong>
                  <span className="muted"> · {job.id.slice(0, 8)}</span>
                  {job.state === "running" && (
                    <progress
                      aria-label="素材导入进度"
                      value={job.progress}
                      max={1}
                    />
                  )}
                  {job.errorCode && (
                    <p>{projectError(job.errorCode).message}</p>
                  )}
                </div>
                {(job.state === "queued" || job.state === "running") && (
                  <button
                    disabled={disabled}
                    onClick={() => setCancelId(job.id)}
                  >
                    取消此作业
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {cancelId && (
        <form
          className="media-cancel"
          onSubmit={(event) => {
            event.preventDefault();
            void action(() => mutate("cancel"));
          }}
        >
          <label>
            取消原因
            <input
              required
              maxLength={500}
              value={reason}
              disabled={disabled}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <p className="muted">
            取消会停止本次作业，并保留原文件和已存在的素材。
          </p>
          <button
            disabled={
              disabled ||
              !reason.trim() ||
              !jobs.some(
                (job) =>
                  job.id === cancelId &&
                  (job.state === "queued" || job.state === "running"),
              )
            }
          >
            确认取消作业
          </button>
          <button
            type="button"
            disabled={locked || !!pending}
            onClick={() => setCancelId(null)}
          >
            收起
          </button>
        </form>
      )}
      <div className="section-heading">
        <h3>已登记素材</h3>
        <button
          disabled={!ready || locked}
          onClick={() =>
            void action(async () => {
              await refreshTools(epoch.current);
              await reload();
            })
          }
        >
          刷新素材
        </button>
      </div>
      {!loaded ? (
        <p role="status">正在读取素材…</p>
      ) : !items.length ? (
        <p className="muted">
          还没有素材。选择文件并导入，完成校验后即可预览。
        </p>
      ) : (
        <ul className="media-items">
          {items.map((item) => (
            <li key={item.id}>
              <div>
                <strong>
                  {item.mime.startsWith("image/")
                    ? "图片"
                    : item.mime.startsWith("audio/")
                      ? "音频"
                      : "视频"}{" "}
                  · {item.id.slice(0, 8)}
                </strong>
                <p>
                  {availabilityLabels[item.availability]} ·{" "}
                  {(item.byteLength / 1024 / 1024).toFixed(2)} MiB
                  {item.width && item.height
                    ? ` · ${item.width} × ${item.height}`
                    : ""}
                  {item.durationMs
                    ? ` · ${(item.durationMs / 1000).toFixed(1)} 秒`
                    : ""}
                </p>
              </div>
              {item.availability === "available" && (
                <button
                  disabled={!ready || locked}
                  onClick={() => setPreview(item)}
                >
                  预览素材
                </button>
              )}
              {item.availability === "missing" && (
                <button
                  disabled={disabled}
                  onClick={() => void action(() => mutate("relocate", item))}
                >
                  重新定位原文件
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {cursor && (
        <button disabled={!ready || locked} onClick={() => void action(more)}>
          加载更多素材
        </button>
      )}
      {preview && (
        <div className="media-preview" aria-label="素材预览">
          <div className="section-heading">
            <h3>素材预览</h3>
            <button onClick={() => setPreview(null)}>关闭预览</button>
          </div>
          {preview.mime.startsWith("image/") ? (
            <img
              alt={`已导入图片 ${preview.id.slice(0, 8)}`}
              src={`avi-media://local/${projectId}/${preview.id}`}
              onError={() => {
                setPreview(null);
                setMessage("素材无法读取，请刷新并重新定位原文件。");
              }}
            />
          ) : preview.mime.startsWith("audio/") ? (
            <audio
              controls
              preload="metadata"
              src={`avi-media://local/${projectId}/${preview.id}`}
              onError={() => {
                setPreview(null);
                setMessage("音频无法读取，请刷新并核对文件。");
              }}
            />
          ) : (
            <video
              controls
              preload="metadata"
              src={`avi-media://local/${projectId}/${preview.id}`}
              onError={() => {
                setPreview(null);
                setMessage("视频无法读取，请刷新并核对文件。");
              }}
            />
          )}
        </div>
      )}
    </section>
  );
}
