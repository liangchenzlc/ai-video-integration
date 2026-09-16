import { useEffect, useRef, useState, type FormEvent } from "react";
import { flushSync } from "react-dom";
import type {
  Settings,
  SettingsDetails,
  Phase,
  CredentialSecret,
  CapabilityProfile,
} from "../../electron/shared/settings";
import { phaseSchema } from "../../electron/shared/settings";
import {
  projectError,
  type ProjectResult,
  type ProjectSession,
} from "../../electron/shared/projects";
import type { MediaJob } from "../../electron/shared/media";
import { DiagnosticsPanel } from "./DiagnosticsPanel";

type Pending = {
  operationId: string;
  projectId?: string;
  connectionCheck?: boolean;
};
const phaseNames: Record<Phase, string> = {
  story_adaptation: "故事改编",
  story_outline: "故事大纲",
  story_scene: "场景",
  story_dialogue: "对白",
  image_character: "角色图像",
  image_location: "场景图像",
  image_prop: "道具图像",
  image_keyframe: "关键帧",
  video: "视频",
  speech: "配音",
  lipsync: "口型",
  music: "音乐",
  sfx: "音效",
  check: "AI 检查",
};
const groups = [
  {
    name: "文字 / 图像",
    phases: [
      "story_adaptation",
      "story_outline",
      "story_scene",
      "story_dialogue",
      "image_character",
      "image_location",
      "image_prop",
      "image_keyframe",
      "check",
    ],
  },
  { name: "声音", phases: ["speech"] },
  { name: "视频 / 口型", phases: ["video", "lipsync"] },
  { name: "音乐 / 音效", phases: ["music", "sfx"] },
];
const statusNames = {
  unknown: "未检查",
  available: "可用",
  unavailable: "不可用",
  unverified: "未验证",
  verified: "已验证",
  research_only: "仅供研究",
};
function CapabilityStates({ capability }: { capability: CapabilityProfile }) {
  return (
    <p className="capability-states">
      <span>账户：{statusNames[capability.accountState]}</span>
      <span>接口：{statusNames[capability.interfaceState]}</span>
      <span>效果：{statusNames[capability.qualityState]}</span>
    </p>
  );
}
export function SettingsPanel({
  ready,
  active,
  runtimeId,
  onLocal,
}: {
  ready: boolean;
  active: boolean;
  runtimeId: string | null;
  onLocal: () => void;
}) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [details, setDetails] = useState<SettingsDetails | null>(null);
  const [session, setSession] = useState<ProjectSession | null>(null);
  const [stageModels, setStageModels] = useState<
    { phase: Phase; capabilityId: string; capabilityVersion: string }[]
  >([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [provider, setProvider] = useState("");
  const [kind, setKind] = useState<"api_key" | "oss">("api_key");
  const [persistence, setPersistence] = useState<"dpapi" | "session_only">(
    "dpapi",
  );
  const [apiKey, setApiKey] = useState("");
  const [accessKeyId, setAccessKeyId] = useState("");
  const [accessKeySecret, setAccessKeySecret] = useState("");
  const [securityToken, setSecurityToken] = useState("");
  const credentialForm = useRef<HTMLFormElement>(null);
  const [deleteProvider, setDeleteProvider] = useState<string | null>(null);
  const [storage, setStorage] = useState({
    providerId: "",
    region: "",
    bucket: "",
    credentialRef: "",
    retentionHours: 48,
  });
  const [phase, setPhase] = useState<Phase>("story_adaptation");
  const [capabilityId, setCapabilityId] = useState("");
  const [check, setCheck] = useState<CapabilityProfile | null>(null);
  const [job, setJob] = useState<MediaJob | null>(null);
  function clearSecrets() {
    setApiKey("");
    setAccessKeyId("");
    setAccessKeySecret("");
    setSecurityToken("");
    credentialForm.current
      ?.querySelectorAll<HTMLInputElement>('input[type="password"]')
      .forEach((input) => {
        input.value = "";
      });
  }
  async function refresh() {
    const [currentSettings, currentDetails, currentSession] = await Promise.all(
      [
        window.desktop.settings.get(),
        window.desktop.settings.details(),
        window.desktop.projects.current(),
      ],
    );
    if (!currentSettings.ok) {
      setMessage(currentSettings.error.message);
      return;
    }
    if (!currentDetails.ok) {
      setMessage(currentDetails.error.message);
      return;
    }
    setSettings(currentSettings.data);
    setDetails(currentDetails.data);
    if (!currentSession.ok) {
      setMessage(currentSession.error.message);
      return;
    }
    setSession(currentSession.data);
    if (currentSession.data) {
      const selected = await window.desktop.settings.stageModels({
        projectId: currentSession.data.projectId,
      });
      if (selected.ok) setStageModels(selected.data);
      else setMessage(selected.error.message);
    } else setStageModels([]);
  }
  useEffect(() => {
    if (!active || !ready) {
      clearSecrets();
      return;
    }
    void refresh();
  }, [active, ready, runtimeId]);
  async function run(work: () => Promise<void>) {
    if (working.current) return;
    working.current = true;
    setBusy(true);
    setMessage("");
    try {
      await work();
    } catch {
      setMessage(projectError("BACKEND_UNAVAILABLE").message);
    } finally {
      working.current = false;
      setBusy(false);
    }
  }
  async function accept(
    result: ProjectResult<{ resourceId: string }>,
    operation: Pending,
  ) {
    if (!result.ok) {
      setMessage(result.error.message);
      if (
        !["BACKEND_UNAVAILABLE", "PROTOCOL_INVALID"].includes(result.error.code)
      )
        setPending(null);
      if (result.error.code === "REVISION_CONFLICT") await refresh();
      return;
    }
    setPending(null);
    setMessage(
      operation.connectionCheck
        ? "检测已提交，请查看检测结果。"
        : "设置已保存。",
    );
    if (operation.connectionCheck) {
      const resultJob = await window.desktop.settings.job({
        jobId: result.data.resourceId,
      });
      if (resultJob.ok) setJob(resultJob.data);
      else setMessage(resultJob.error.message);
    }
    await refresh();
  }
  function saveCredential(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settings || working.current || pending) return;
    const secret: CredentialSecret =
      kind === "api_key"
        ? { kind, apiKey }
        : {
            kind,
            accessKeyId,
            accessKeySecret,
            securityToken: securityToken || null,
          };
    // Clear both controlled values and the live input before the bridge is invoked.
    flushSync(clearSecrets);
    const operation = { operationId: crypto.randomUUID() };
    setPending(operation);
    void run(async () =>
      accept(
        await window.desktop.settings.setCredential({
          providerId: provider,
          command: {
            clientOperationId: operation.operationId,
            expectedRevision: settings.revision,
            payload: { secret, persistence },
          },
        }),
        operation,
      ),
    );
  }
  function saveStorage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settings || pending) return;
    const operation = { operationId: crypto.randomUUID() };
    setPending(operation);
    void run(async () =>
      accept(
        await window.desktop.settings.configureStorage({
          clientOperationId: operation.operationId,
          expectedRevision: settings.revision,
          payload: storage,
        }),
        operation,
      ),
    );
  }
  function removeCredential() {
    if (!settings || !deleteProvider || pending) return;
    const providerId = deleteProvider;
    setDeleteProvider(null);
    const operation = { operationId: crypto.randomUUID() };
    setPending(operation);
    void run(async () =>
      accept(
        await window.desktop.settings.deleteCredential({
          providerId,
          command: {
            clientOperationId: operation.operationId,
            expectedRevision: settings.revision,
            payload: { confirmed: true },
          },
        }),
        operation,
      ),
    );
  }
  function saveStage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    void run(async () => {
      const current = await window.desktop.projects.current();
      if (!current.ok || !current.data) {
        setMessage("请先打开可写项目，再选择阶段模型。");
        return;
      }
      // current() binds identity; project() reads the latest project CAS revision.
      const project = await window.desktop.projects.drafts.project({
        projectId: current.data.projectId,
      });
      if (!project.ok) {
        setMessage(project.error.message);
        return;
      }
      const operation = {
        operationId: crypto.randomUUID(),
        projectId: current.data.projectId,
      };
      setPending(operation);
      await accept(
        await window.desktop.settings.configureStage({
          projectId: current.data.projectId,
          command: {
            clientOperationId: operation.operationId,
            expectedRevision: project.data.revision,
            payload: { phase, capabilityId },
          },
        }),
        operation,
      );
    });
  }
  function queryOperation() {
    if (!pending) return;
    const operation = pending;
    void run(async () => {
      const result = operation.projectId
        ? await window.desktop.projects.drafts.operation({
            projectId: operation.projectId,
            operationId: operation.operationId,
          })
        : await window.desktop.projects.operation({
            operationId: operation.operationId,
          });
      if (!result.ok) {
        setMessage(
          result.error.code === "OBJECT_NOT_FOUND"
            ? "尚未查到原操作，结果仍未确定。请保留编号并稍后再次查询。"
            : result.error.message,
        );
        return;
      }
      await accept({ ok: true, data: result.data.receipt }, operation);
    });
  }
  function checkConnection() {
    if (!settings || !check || pending) return;
    const capability = check;
    setCheck(null);
    const operation = {
      operationId: crypto.randomUUID(),
      connectionCheck: true,
    };
    setPending(operation);
    void run(async () =>
      accept(
        await window.desktop.settings.checkConnection({
          clientOperationId: operation.operationId,
          expectedRevision: settings.revision,
          payload: { capabilityId: capability.id },
        }),
        operation,
      ),
    );
  }
  function chooseTools() {
    if (!settings || pending) return;
    void run(async () => {
      const choice = await window.desktop.projects.media.chooseFile({
        purpose: "ffmpeg",
      });
      if (!choice.ok) {
        setMessage(choice.error.message);
        return;
      }
      if (!choice.data) return;
      const operation = { operationId: crypto.randomUUID() };
      setPending(operation);
      await accept(
        await window.desktop.projects.media.configureTools({
          clientOperationId: operation.operationId,
          expectedRevision: settings.revision,
          payload: { ffmpegGrantId: choice.data.grantId },
        }),
        operation,
      );
    });
  }
  const locked = !ready || busy || !!pending || !settings;
  const matching =
    settings?.capabilities.filter((item) => item.phases.includes(phase)) ?? [];
  const selected = stageModels.find((item) => item.phase === phase);
  return (
    <div className="settings-workspace">
      <div className="intro">
        <h1>设置</h1>
        <p>
          先看清制作所需的服务，再配置凭据与模型。账户连接、接口验证和效果验证分别记录。
        </p>
        <button onClick={onLocal}>继续本地准备</button>
      </div>
      {!ready && (
        <p className="notice">
          等待本地服务恢复后可读取和修改设置；仍可浏览本地工作区。
        </p>
      )}
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      {pending && (
        <section className="settings-pending" aria-label="待确认设置操作">
          <h2>核对这次操作</h2>
          <p>
            {busy
              ? "正在等待保存结果。"
              : "结果尚未确定，请查询原操作，避免重复提交。"}
          </p>
          <p>
            操作编号：<code>{pending.operationId}</code>
          </p>
          <button disabled={!ready || busy} onClick={queryOperation}>
            查询原操作
          </button>
        </section>
      )}
      <section className="settings-panel" aria-labelledby="readiness-title">
        <div className="section-heading">
          <h2 id="readiness-title">制作准备情况</h2>
          <button disabled={!ready || busy} onClick={() => void run(refresh)}>
            刷新设置
          </button>
        </div>
        <p>
          缺少生成服务不影响整理故事、编辑草稿或导入已有素材。研究候选未经真实验证，不代表可用于生产。
        </p>
        <ul className="settings-readiness">
          {groups.map((group) => {
            const candidates =
              settings?.capabilities.filter((item) =>
                item.phases.some((p) => group.phases.includes(p)),
              ) ?? [];
            return (
              <li key={group.name}>
                <h3>{group.name}</h3>
                {candidates.length ? (
                  candidates.map((item) => (
                    <div className="capability-row" key={item.id}>
                      <strong>
                        {item.providerId} / {item.modelId}
                      </strong>
                      <p>
                        {item.region} · 档案 {item.version} ·{" "}
                        {item.enabled ? "已启用" : "尚未启用"}
                      </p>
                      <CapabilityStates capability={item} />
                      {item.restrictions.map((text, index) => (
                        <p key={index}>{text}</p>
                      ))}
                      <p>
                        资料来源：{item.priceSource} · {item.priceDate}
                      </p>
                      <button disabled={locked} onClick={() => setCheck(item)}>
                        查看免费检测内容
                      </button>
                    </div>
                  ))
                ) : (
                  <p>
                    {settings
                      ? "暂无已验证模型，请配置凭据并等待可验证的能力档案。"
                      : "等待读取能力档案。"}
                  </p>
                )}
              </li>
            );
          })}
          <li>
            <h3>媒体工具</h3>
            <p>
              {settings?.ffmpegConfigured
                ? "本机媒体工具已配置；模型生成能力仍需单独验证。"
                : "尚未配置 FFmpeg，导入检查与导出需要本机媒体工具。"}
            </p>
            {details?.toolSummary && (
              <p>
                {details.toolSummary.version} · H.264{" "}
                {details.toolSummary.h264 ? "支持" : "缺失"} · AAC{" "}
                {details.toolSummary.aac ? "支持" : "缺失"} · 字幕{" "}
                {details.toolSummary.subtitles ? "支持" : "缺失"}
              </p>
            )}
            <button disabled={locked} onClick={chooseTools}>
              选择本机 FFmpeg
            </button>
          </li>
        </ul>
      </section>
      {check && (
        <section className="settings-panel" aria-label="免费检测说明">
          <h2>检测账户连接</h2>
          <p>
            仅在存在已核定免费的适配器时，向 {check.providerId}{" "}
            查询账户权限或模型元数据。不会提交故事、图片、声音或视频进行推理。检测成功只更新账户状态，不代表接口或效果通过。
          </p>
          <p>
            没有免费适配器时不会发起请求。收费试听和试片需在后续任务计划中单独确认预算，目前尚未开放。
          </p>
          <button disabled={locked} onClick={checkConnection}>
            确认免费检测
          </button>
          <button onClick={() => setCheck(null)}>取消检测</button>
        </section>
      )}
      {job && (
        <section className="settings-panel" aria-label="账户检测结果">
          <h2>账户检测结果</h2>
          <p>
            {
              {
                queued: "等待检测",
                running: "正在检测",
                succeeded: "账户检测完成；接口和效果状态保持独立。",
                failed: "检测未通过",
                cancelled: "检测已取消",
              }[job.state]
            }
          </p>
          {job.errorCode && <p>{projectError(job.errorCode).message}</p>}
          <button
            disabled={!ready || busy}
            onClick={() =>
              void run(async () => {
                const result = await window.desktop.settings.job({
                  jobId: job.id,
                });
                if (result.ok) {
                  setJob(result.data);
                  await refresh();
                } else setMessage(result.error.message);
              })
            }
          >
            刷新检测结果
          </button>
        </section>
      )}
      <section className="settings-panel" aria-labelledby="credentials-title">
        <h2 id="credentials-title">服务凭据</h2>
        <p>
          提交后立即清空输入。加密保存绑定当前 Windows
          用户；仅本次使用的凭据在服务退出后失效。
        </p>
        <ul className="settings-saved">
          {details?.credentials.map((item) => (
            <li key={item.id}>
              <span>
                <strong>{item.providerId}</strong> ·{" "}
                {item.kind === "oss" ? "OSS" : "API Key"} · 尾号{" "}
                {item.maskedSuffix} ·{" "}
                {item.persistence === "dpapi"
                  ? "Windows 加密保存"
                  : "仅本次使用"}
              </span>
              <button
                disabled={locked}
                onClick={() => {
                  clearSecrets();
                  setProvider(item.providerId);
                  setKind(item.kind);
                  setPersistence(item.persistence);
                  credentialForm.current
                    ?.querySelector<HTMLInputElement>('input[name="provider"]')
                    ?.focus();
                }}
              >
                替换凭据
              </button>
              <button
                disabled={locked}
                onClick={() => setDeleteProvider(item.providerId)}
              >
                删除凭据
              </button>
            </li>
          ))}
        </ul>
        {deleteProvider && (
          <div
            className="settings-confirm"
            role="group"
            aria-label="确认删除凭据"
          >
            <p>
              确认删除 {deleteProvider}{" "}
              的凭据？依赖它的服务将需要重新配置，已有项目和素材会保留。
            </p>
            <button disabled={locked} onClick={removeCredential}>
              确认删除凭据
            </button>
            <button onClick={() => setDeleteProvider(null)}>保留凭据</button>
          </div>
        )}
        <form ref={credentialForm} onSubmit={saveCredential} autoComplete="off">
          <fieldset disabled={locked}>
            <legend>录入或替换凭据</legend>
            <div className="settings-fields">
              <label>
                服务商标识
                <input
                  name="provider"
                  required
                  pattern="[a-zA-Z0-9][a-zA-Z0-9._\-]{0,99}"
                  maxLength={100}
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                  placeholder="例如 dashscope 或 aliyun-oss"
                />
              </label>
              <div className="settings-field">
                <label htmlFor="credential-kind">凭据类型</label>
                <select
                  id="credential-kind"
                  value={kind}
                  onChange={(e) => {
                    clearSecrets();
                    setKind(e.target.value as typeof kind);
                  }}
                >
                  <option value="api_key">API Key</option>
                  <option value="oss">OSS 存储凭据</option>
                </select>
              </div>
              {kind === "api_key" ? (
                <label>
                  API Key
                  <input
                    type="password"
                    autoComplete="new-password"
                    required
                    maxLength={8192}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                  />
                </label>
              ) : (
                <>
                  <label>
                    Access Key ID
                    <input
                      type="password"
                      autoComplete="new-password"
                      required
                      maxLength={256}
                      value={accessKeyId}
                      onChange={(e) => setAccessKeyId(e.target.value)}
                    />
                  </label>
                  <label>
                    Access Key Secret
                    <input
                      type="password"
                      autoComplete="new-password"
                      required
                      maxLength={8192}
                      value={accessKeySecret}
                      onChange={(e) => setAccessKeySecret(e.target.value)}
                    />
                  </label>
                  <label>
                    Security Token（可选）
                    <input
                      type="password"
                      autoComplete="new-password"
                      maxLength={16384}
                      value={securityToken}
                      onChange={(e) => setSecurityToken(e.target.value)}
                    />
                  </label>
                </>
              )}
              <div className="settings-field">
                <label htmlFor="credential-persistence">凭据保存方式</label>
                <select
                  id="credential-persistence"
                  value={persistence}
                  onChange={(e) =>
                    setPersistence(e.target.value as typeof persistence)
                  }
                >
                  <option value="dpapi">Windows 加密保存</option>
                  <option value="session_only">仅本次使用</option>
                </select>
              </div>
            </div>
            <button type="submit">保存凭据</button>
          </fieldset>
        </form>
      </section>
      <section className="settings-panel" aria-labelledby="storage-title">
        <h2 id="storage-title">生产音频存储</h2>
        <p>
          使用你自己的 OSS bucket。先录入 OSS
          凭据，再配置地域与保留期；当前只保存配置，不执行上传或清理。
        </p>
        <ul className="settings-saved">
          {details?.storageProfiles.map((item) => (
            <li key={item.id}>
              <span>
                {item.providerId} · {item.region} · {item.bucket} ·{" "}
                {item.retentionHours} 小时 ·{" "}
                {item.persistence === "dpapi" ? "加密凭据" : "仅本次使用"}
              </span>
              <button
                disabled={locked}
                onClick={() =>
                  setStorage({
                    providerId: item.providerId,
                    region: item.region,
                    bucket: item.bucket,
                    credentialRef: item.credentialRef,
                    retentionHours: item.retentionHours,
                  })
                }
              >
                修改存储配置
              </button>
            </li>
          ))}
        </ul>
        <form onSubmit={saveStorage}>
          <fieldset disabled={locked}>
            <legend>存储配置</legend>
            <div className="settings-fields">
              <div className="settings-field">
                <label htmlFor="storage-credential">OSS 凭据</label>
                <select
                  id="storage-credential"
                  required
                  value={storage.credentialRef}
                  onChange={(e) => {
                    const item = details?.credentials.find(
                      (c) => c.id === e.target.value,
                    );
                    setStorage({
                      ...storage,
                      credentialRef: e.target.value,
                      providerId: item?.providerId ?? "",
                    });
                  }}
                >
                  <option value="">选择已保存的 OSS 凭据</option>
                  {details?.credentials
                    .filter((item) => item.kind === "oss")
                    .map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.providerId} · 尾号 {item.maskedSuffix}
                      </option>
                    ))}
                </select>
              </div>
              <label>
                Region
                <input
                  required
                  maxLength={100}
                  value={storage.region}
                  onChange={(e) =>
                    setStorage({ ...storage, region: e.target.value })
                  }
                />
              </label>
              <label>
                Bucket
                <input
                  required
                  maxLength={100}
                  value={storage.bucket}
                  onChange={(e) =>
                    setStorage({ ...storage, bucket: e.target.value })
                  }
                />
              </label>
              <label>
                保留期（小时）
                <input
                  type="number"
                  min={1}
                  max={168}
                  step={1}
                  required
                  value={storage.retentionHours}
                  onChange={(e) =>
                    setStorage({
                      ...storage,
                      retentionHours: e.target.valueAsNumber,
                    })
                  }
                />
              </label>
            </div>
            <button type="submit">保存存储配置</button>
          </fieldset>
        </form>
      </section>
      <section className="settings-panel" aria-labelledby="stages-title">
        <h2 id="stages-title">项目阶段模型</h2>
        <p>
          {session
            ? `当前项目：${session.project.name}。设置只用于后续任务，已有结果保留原模型来源。`
            : "先创建或打开项目，再选择各制作阶段的模型。"}
        </p>
        <form onSubmit={saveStage}>
          <fieldset disabled={locked || !session || session.mode !== "write"}>
            <legend>为当前项目选择模型</legend>
            <div className="settings-fields">
              <div className="settings-field">
                <label htmlFor="pipeline-phase">制作阶段</label>
                <select
                  id="pipeline-phase"
                  value={phase}
                  onChange={(e) => {
                    setPhase(e.target.value as Phase);
                    setCapabilityId("");
                  }}
                >
                  {phaseSchema.options.map((value) => (
                    <option key={value} value={value}>
                      {phaseNames[value]}
                    </option>
                  ))}
                </select>
              </div>
              <div className="settings-field">
                <label htmlFor="phase-model">阶段模型</label>
                <select
                  id="phase-model"
                  required
                  value={capabilityId}
                  onChange={(e) => setCapabilityId(e.target.value)}
                >
                  <option value="">选择匹配的模型</option>
                  {matching.map((item) => (
                    <option
                      key={item.id}
                      value={item.id}
                      disabled={!item.enabled}
                    >
                      {item.providerId} / {item.modelId} · {item.region}
                      {item.enabled ? "" : "（尚未启用）"}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            {selected && (
              <p>
                已保存档案：
                {settings?.capabilities.find(
                  (item) => item.id === selected.capabilityId,
                )?.modelId ?? "当前档案不可用"}{" "}
                · 版本 {selected.capabilityVersion}
              </p>
            )}
            {!matching.length && (
              <p>该阶段暂无匹配的能力档案；可以继续本地准备。</p>
            )}
            {matching.map((item) => (
              <div key={item.id}>
                <strong>{item.modelId}</strong>
                <CapabilityStates capability={item} />
              </div>
            ))}
            <button type="submit" disabled={!capabilityId}>
              保存阶段模型
            </button>
          </fieldset>
        </form>
      </section>
      <DiagnosticsPanel
        ready={ready}
        active={active}
        projectId={session?.projectId}
      />
    </div>
  );
}
