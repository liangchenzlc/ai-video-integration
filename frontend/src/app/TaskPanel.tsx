import { useCallback, useEffect, useRef, useState } from "react";
import { z } from "zod";
import {
  projectUuid,
  type ProjectResult,
  type ProjectSession,
  type receiptSchema,
} from "../../electron/shared/projects";
import {
  stages,
  type Budget,
  type Call,
  type CostSummary,
  type Task,
  type TaskPlan,
  type taskListSchema,
  type taskRoutes,
} from "../../electron/shared/tasks";
import { formatYuan, parseYuan } from "./task-money";
import { taskLabels } from "./TaskActivity";
import { StoryPlanPreview } from "./StoryPlanPreview";
import type { Revision } from "../../electron/shared/versions";

type CandidateDescription = {
  kind: "text" | "image";
  title: string;
  summary: string;
  mediaUrl: string | null;
};

export async function loadAllTaskCandidates(
  load: (
    cursor?: string,
  ) => Promise<ProjectResult<{ items: Revision[]; nextCursor: string | null }>>,
): Promise<{ items: Revision[]; error: string | null }> {
  const items: Revision[] = [];
  let cursor: string | undefined;
  do {
    const page = await load(cursor);
    if (!page.ok) return { items, error: page.error.message };
    items.push(...page.data.items);
    cursor = page.data.nextCursor ?? undefined;
  } while (cursor);
  return { items, error: null };
}

export function describeCandidate(
  projectId: string,
  payload: Revision["payload"],
): CandidateDescription {
  if (payload.kind === "story") {
    const content = payload.content;
    const summary = content.outline.length
      ? content.outline.join("\n")
      : content.brief;
    return { kind: "text", title: "故事候选", summary, mediaUrl: null };
  }
  if (payload.kind === "asset") {
    const content = payload.content;
    const typeLabels = {
      character: "角色",
      location: "场景",
      prop: "道具",
      style: "风格",
    } as const;
    const generated = [...content.references]
      .sort((left, right) => right.order - left.order)
      .find((reference) => reference.state === "pending");
    return {
      kind: "image",
      title: `${typeLabels[content.assetType]}图像候选：${content.name}`,
      summary: `身份锚点：${content.identityAnchors.join("、")}`,
      mediaUrl: generated
        ? `avi-media://local/${projectId}/${generated.mediaId}`
        : null,
    };
  }
  return {
    kind: "text",
    title: `${payload.kind} 候选`,
    summary: "请在版本对照中查看完整结构。",
    mediaUrl: null,
  };
}
const disclosureLabels = {
  text: "文字",
  image: "图片",
  audio: "音频",
  video: "视频",
  upload: "上传素材",
};
const stageLabels = {
  story: "故事",
  image: "图像",
  video: "视频",
  speech: "配音",
  lipsync: "口型",
  music: "音乐",
  sfx: "音效",
  check: "检查",
};
const pendingSchema = z.strictObject({
  id: projectUuid,
  kind: z.enum(["plan", "start", "other", "image_input"]),
  resourceId: projectUuid.nullable(),
  objectId: projectUuid.optional(),
  inputSignature: z.string().max(10000).optional(),
  label: z.string(),
  expectedRevision: z.number().int().nonnegative().optional(),
});
type Pending = z.infer<typeof pendingSchema>;
type Receipt = z.infer<typeof receiptSchema>;
type TaskList = z.infer<typeof taskListSchema>;
export function advanceTaskDraftRevision(
  pending: Pick<Pending, "id" | "expectedRevision">,
  receipt: Receipt,
  advance: (expectedRevision: number, committedRevision: number) => boolean,
): boolean {
  if (
    pending.id !== receipt.operationId ||
    pending.expectedRevision === undefined
  )
    return false;
  return advance(pending.expectedRevision, receipt.committedRevision);
}
const uncertain = new Set([
  "BACKEND_UNAVAILABLE",
  "PROTOCOL_INVALID",
  "SESSION_EXPIRED",
]);
const callMessages: Record<string, string> = {
  CALL_RESULT_UNKNOWN: "结果尚未确认，可能已计费。请核对请求时间和原调用。",
  CALL_FAILED: "此次调用已确定失败；已有结果仍保留，费用需按依据核对。",
  DOWNLOAD_FAILED: "结果下载未完成。请恢复原结果下载，不重新生成。",
  STRUCTURED_RESULT_INVALID:
    "结果结构不符合固定候选协议；原始结果已保留，不会自动补写或采用。",
  MEDIA_TOOLS_NOT_CONFIGURED:
    "尚未配置本地 FFmpeg。配置后请恢复原结果下载，不要重新生成。",
  RESULT_URL_REJECTED:
    "结果地址未通过安全校验；原调用已保留，不会访问该地址或自动重试生成。",
  RESULT_MEDIA_INVALID:
    "结果媒体未通过格式或解码校验；原调用已保留，不会自动修复或采用。",
  RESULT_SIZE_LIMIT:
    "结果媒体超过允许大小；原调用已保留，不会继续下载或自动采用。",
  MEDIA_HASH_MISMATCH:
    "结果媒体与原记录不一致；原调用已保留，请核对来源后处理。",
};
export function TaskPanel({
  session,
  ready,
  locked,
  action,
  prepareMutation,
  advanceDraftRevision,
  onSettings,
  onCompareCandidate,
}: {
  session: ProjectSession;
  ready: boolean;
  locked: boolean;
  action: (work: () => Promise<void>) => Promise<void>;
  prepareMutation: () => Promise<boolean>;
  advanceDraftRevision: (
    expectedRevision: number,
    committedRevision: number,
  ) => boolean;
  onSettings: () => void;
  onCompareCandidate: (revision: Revision) => void;
}) {
  const projectId = session.projectId;
  const bridge = window.desktop.tasks;
  const pendingKey = `task-operation:${projectId}`;
  const [pending, updatePending] = useState<Pending | null>(() => {
    try {
      const parsed = pendingSchema.safeParse(
        JSON.parse(localStorage.getItem(pendingKey) ?? "null"),
      );
      return parsed.success ? parsed.data : null;
    } catch {
      return null;
    }
  });
  const [budget, setBudget] = useState<Budget | null>(null);
  const [total, setTotal] = useState("0");
  const [limits, setLimits] = useState<Record<string, string>>(
    Object.fromEntries(stages.map((s) => [s, "0"])),
  );
  const [warning, setWarning] = useState("80");
  const [mode, setMode] = useState<"synthetic" | "real">("synthetic");
  const [phase, setPhase] = useState<
    | "story_adaptation"
    | "story_outline"
    | "story_scene"
    | "story_dialogue"
    | "image_character"
    | "image_location"
    | "image_prop"
  >("story_adaptation");
  const [taskStage, setTaskStage] = useState<"story" | "image">("story");
  const [assetName, setAssetName] = useState("门灯旅人");
  const [assetType, setAssetType] = useState<"character" | "location" | "prop">(
    "character",
  );
  const [identityAnchors, setIdentityAnchors] = useState("深色雨衣\n旧帆布包");
  const [preparedImage, setPreparedImage] = useState<{
    artifactId: string;
    signature: string;
  } | null>(null);
  const [goal, setGoal] = useState("根据当前原文与简报整理故事");
  const [candidates, setCandidates] = useState("1");
  const [precheck, setPrecheck] = useState(false);
  const [plan, setPlan] = useState<TaskPlan | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [list, setList] = useState<TaskList>({ items: [], nextCursor: null });
  const [task, setTask] = useState<Task | null>(null);
  const [taskPlan, setTaskPlan] = useState<TaskPlan | null>(null);
  const [taskCandidates, setTaskCandidates] = useState<{
    taskId: string | null;
    items: Revision[];
  }>({ taskId: null, items: [] });
  const [calls, setCalls] = useState<Call[]>([]);
  const [costs, setCosts] = useState<CostSummary | null>(null);
  const [entries, setEntries] = useState<
    z.infer<(typeof taskRoutes.entries)["output"]>
  >({ items: [], nextCursor: null });
  const [message, setMessage] = useState("");
  const [settlementCall, setSettlementCall] = useState("");
  const [amount, setAmount] = useState("");
  const [basis, setBasis] = useState("");
  const [reason, setReason] = useState("");
  const [expenseAmount, setExpenseAmount] = useState("");
  const [expenseBasis, setExpenseBasis] = useState("");
  const [category, setCategory] = useState<
    "storage" | "transfer" | "procurement"
  >("storage");
  const [expenseState, setExpenseState] = useState<
    "estimated" | "pending" | "settled"
  >("estimated");
  const selected = useRef<string | null>(null);
  const blocked = locked || !ready || session.mode !== "write" || !!pending;
  function setPending(value: Pending | null) {
    if (value) localStorage.setItem(pendingKey, JSON.stringify(value));
    else localStorage.removeItem(pendingKey);
    updatePending(value);
  }
  const loadTask = useCallback(
    async (taskId: string) => {
      selected.current = taskId;
      const result = await bridge.get({ projectId, taskId });
      if (!result.ok) {
        setMessage(result.error.message);
        return;
      }
      const loaded = await Promise.all(
        result.data.callIds.map((callId) => bridge.call({ projectId, callId })),
      );
      const [loadedPlan, loadedCandidates] = await Promise.all([
        bridge.getPlan({ projectId, planId: result.data.planId }),
        loadAllTaskCandidates((cursor) =>
          bridge.candidates({ projectId, taskId, cursor, limit: 50 }),
        ),
      ]);
      if (selected.current !== taskId) return;
      setTask(result.data);
      setTaskPlan(loadedPlan.ok ? loadedPlan.data : null);
      setTaskCandidates((current) => {
        const retained = current.taskId === taskId ? current.items : [];
        const items = loadedCandidates.error
          ? [
              ...loadedCandidates.items,
              ...retained.filter(
                (known) =>
                  !loadedCandidates.items.some((item) => item.id === known.id),
              ),
            ]
          : loadedCandidates.items;
        return { taskId, items };
      });
      setCalls(loaded.flatMap((r) => (r.ok ? [r.data] : [])));
      const failed = loaded.find((r) => !r.ok);
      if (failed && !failed.ok) setMessage(failed.error.message);
      if (loadedCandidates.error) setMessage(loadedCandidates.error);
    },
    [bridge, projectId],
  );
  const refresh = useCallback(
    async (includeBudget = false) => {
      const results = await Promise.all([
        bridge.list({ projectId }),
        bridge.costs({ projectId }),
        bridge.entries({ projectId }),
      ]);
      if (results[0].ok) setList(results[0].data);
      else setMessage(results[0].error.message);
      if (results[1].ok) setCosts(results[1].data);
      else setMessage(results[1].error.message);
      if (results[2].ok) setEntries(results[2].data);
      if (includeBudget) {
        const r = await bridge.budget({ projectId });
        if (r.ok) {
          setBudget(r.data);
          setTotal(formatYuan(r.data.totalMicroCny));
          setLimits(
            Object.fromEntries(
              stages.map((s) => [
                s,
                formatYuan(
                  r.data.allocations.find((a) => a.stage === s)
                    ?.limitMicroCny ?? 0,
                ),
              ]),
            ),
          );
          setWarning(String(r.data.warningPercent));
          if (r.data.executionMode) setMode(r.data.executionMode);
        } else setMessage(r.error.message);
      }
    },
    [bridge, projectId],
  );
  useEffect(() => {
    if (ready) void refresh(true);
  }, [ready, session.projectSessionId, refresh]);
  useEffect(() => {
    if (!ready) return;
    const timer = setInterval(() => {
      if (selected.current) void loadTask(selected.current);
    }, 3000);
    return () => clearInterval(timer);
  }, [ready, loadTask]);
  async function complete(saved: Pending, receipt: Receipt) {
    if (receipt.operationId !== saved.id) {
      setMessage("原操作回执不匹配，请继续查询原操作。");
      return false;
    }
    advanceTaskDraftRevision(saved, receipt, advanceDraftRevision);
    if (saved.kind === "plan") {
      const r = await bridge.getPlan({ projectId, planId: receipt.resourceId });
      if (!r.ok) {
        setMessage(r.error.message);
        return false;
      }
      setPlan(r.data);
      setAccepted(false);
    }
    if (saved.kind === "start") {
      await loadTask(receipt.resourceId);
      setPlan(null);
      setAccepted(false);
    }
    if (saved.kind === "other" && saved.resourceId)
      await loadTask(saved.resourceId);
    if (
      saved.kind === "image_input" &&
      saved.objectId &&
      saved.inputSignature
    ) {
      setPreparedImage({
        artifactId: saved.objectId,
        signature: saved.inputSignature,
      });
      setMessage("图像输入已保存。现在可以为这份固定输入生成计划。");
    }
    setPending(null);
    await refresh(true);
    return true;
  }
  async function mutate(
    kind: Pending["kind"],
    label: string,
    send: (command: {
      clientOperationId: string;
      expectedRevision: number;
    }) => Promise<ProjectResult<Receipt>>,
    resourceId: string | null = null,
  ) {
    if (pending || !(await prepareMutation())) return;
    const current = await window.desktop.projects.drafts.project({ projectId });
    if (!current.ok) {
      setMessage(current.error.message);
      return;
    }
    const saved: Pending = {
      id: crypto.randomUUID(),
      kind,
      resourceId,
      label,
      expectedRevision: current.data.revision,
    };
    setPending(saved);
    setMessage("");
    try {
      const result = await send({
        clientOperationId: saved.id,
        expectedRevision: current.data.revision,
      });
      if (result.ok) await complete(saved, result.data);
      else {
        setMessage(result.error.message);
        if (!uncertain.has(result.error.code)) setPending(null);
      }
    } catch {
      setMessage("响应未能确认，可能已经计费。请查询原操作，不要重新启动。");
    }
  }
  async function queryPending() {
    if (!pending) return;
    const result = await window.desktop.projects.drafts.operation({
      projectId,
      operationId: pending.id,
    });
    if (result.ok) await complete(pending, result.data.receipt);
    else
      setMessage(
        result.error.code === "OBJECT_NOT_FOUND"
          ? "尚未查到原操作，请恢复连接后再次查询。不会自动重新提交。"
          : result.error.message,
      );
  }
  function run(work: () => Promise<void>) {
    void action(async () => {
      try {
        await work();
      } catch (error) {
        setMessage(
          error instanceof Error ? error.message : "请检查输入后重试。",
        );
      }
    });
  }
  async function makePlan() {
    if (!(await prepareMutation())) return;
    const drafts = await window.desktop.projects.drafts.list({ projectId });
    if (!drafts.ok) {
      setMessage(drafts.error.message);
      return;
    }
    let draft = drafts.data.find((d) => d.kind === "story");
    if (taskStage === "image") {
      const anchors = identityAnchors
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean);
      if (!assetName.trim() || anchors.length === 0) {
        setMessage("请填写素材名称，并至少提供一个身份锚点。");
        return;
      }
      const signature = JSON.stringify({
        assetType,
        name: assetName.trim(),
        anchors,
      });
      if (preparedImage?.signature === signature) {
        draft = {
          id: "",
          artifactId: preparedImage.artifactId,
          kind: "asset",
          savedAt: "",
        };
      } else {
        const current = await window.desktop.projects.drafts.project({
          projectId,
        });
        if (!current.ok) {
          setMessage(current.error.message);
          return;
        }
        const draftId = crypto.randomUUID();
        const artifactId = crypto.randomUUID();
        const operationId = crypto.randomUUID();
        const pendingImage: Pending = {
          id: operationId,
          kind: "image_input",
          resourceId: null,
          objectId: artifactId,
          inputSignature: signature,
          label: "保存图像输入",
          expectedRevision: current.data.revision,
        };
        setPending(pendingImage);
        let saved: Awaited<
          ReturnType<typeof window.desktop.projects.drafts.save>
        >;
        try {
          saved = await window.desktop.projects.drafts.save({
            projectId,
            command: {
              clientOperationId: operationId,
              expectedRevision: current.data.revision,
              payload: {
                draftId,
                artifactId,
                baseRevisionId: null,
                content: {
                  kind: "asset",
                  content: {
                    assetType,
                    name: assetName.trim(),
                    identityAnchors: anchors,
                    allowedChanges: [],
                    states: [],
                    references: [],
                  },
                },
              },
            },
          });
        } catch {
          setMessage("图像输入保存响应未能确认。请查询原操作，不要重新提交。");
          return;
        }
        if (!saved.ok) {
          setMessage(saved.error.message);
          if (!uncertain.has(saved.error.code)) setPending(null);
          return;
        }
        if (saved.data.operationId !== operationId) {
          setMessage("图像输入保存回执不匹配，请查询原操作后再继续。");
          return;
        }
        await complete(pendingImage, saved.data);
        draft = { id: draftId, artifactId, kind: "asset", savedAt: "" };
      }
    }
    if (!draft) {
      setMessage("请先填写并保存故事原文和创作简报，再生成本地计划。");
      return;
    }
    await mutate("plan", "生成本地计划", (command) =>
      bridge.plan({
        projectId,
        command: {
          ...command,
          payload: {
            objectId: draft.artifactId,
            stage: taskStage,
            phase,
            goal,
            inputRevisionIds: [],
            candidates: Number(candidates),
            includePrecheck: precheck,
            executionMode: mode,
          },
        },
      }),
    );
  }
  function recover(
    call: Call,
    recovery: "query" | "download" | "stop_waiting" | "cancel_remote",
  ) {
    run(() =>
      mutate(
        "other",
        "恢复原调用",
        (command) =>
          bridge.recover({
            projectId,
            callId: call.id,
            command: { ...command, payload: { action: recovery } },
          }),
        call.taskId,
      ),
    );
  }
  const balance = costs
    ? Math.max(
        0,
        costs.budgetMicroCny - costs.settledMicroCny - costs.reservedMicroCny,
      )
    : 0;
  const nearLimit =
    costs &&
    budget &&
    costs.budgetMicroCny > 0 &&
    ((costs.settledMicroCny + costs.reservedMicroCny) / costs.budgetMicroCny) *
      100 >=
      budget.warningPercent;
  return (
    <section className="task-panel settings-workspace" aria-label="任务与费用">
      <div className="section-heading">
        <h2>任务与费用</h2>
        <span>
          {budget?.executionMode === "real"
            ? "真实服务费用"
            : "本地练习 · 模拟费用，不是云端账单"}
        </span>
      </div>
      <p>先核对冻结输入和最高费用，再决定启动。切换工作区不会重新生成。</p>
      {message && (
        <p className="notice" role="alert">
          {message} <a href="#task-budget">查看预算配置</a> ·{" "}
          <button onClick={onSettings}>查看模型设置</button>
        </p>
      )}
      {pending && (
        <div className="settings-pending" role="status">
          {budget?.executionMode === "synthetic" && (
            <p>
              本项目为本地练习，下述费用仅指模拟占用，不会产生真实云端账单。
            </p>
          )}
          <p>{pending.label}的响应尚待确认；若涉及生成，可能已计费。</p>
          <p>
            原操作 <code>{pending.id}</code>
          </p>
          <button disabled={!ready || locked} onClick={() => run(queryPending)}>
            查询原操作
          </button>
        </div>
      )}
      <details id="task-budget">
        <summary>预算配置（元）</summary>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => {
              const payload = {
                totalMicroCny: parseYuan(total),
                allocations: stages.map((stage) => ({
                  stage,
                  limitMicroCny: parseYuan(limits[stage]),
                })),
                warningPercent: Number(warning),
              };
              await mutate("other", "保存预算", (command) =>
                bridge.setBudget({
                  projectId,
                  command: { ...command, payload },
                }),
              );
            });
          }}
        >
          <fieldset disabled={blocked || !budget}>
            <div className="settings-fields">
              <label>
                项目总预算（元）
                <input
                  required
                  inputMode="decimal"
                  value={total}
                  onChange={(e) => setTotal(e.target.value)}
                />
              </label>
              <label>
                费用预警百分比
                <input
                  required
                  type="number"
                  min="1"
                  max="100"
                  step="1"
                  value={warning}
                  onChange={(e) => setWarning(e.target.value)}
                />
              </label>
              {stages.map((s) => (
                <label key={s}>
                  {stageLabels[s]}预算（元）
                  <input
                    required
                    inputMode="decimal"
                    value={limits[s]}
                    onChange={(e) =>
                      setLimits({ ...limits, [s]: e.target.value })
                    }
                  />
                </label>
              ))}
            </div>
            <p className="muted">
              阶段分配合计不能超过项目预算；已结算与占用金额不能被减掉。金额最多保留六位小数。
            </p>
            <button type="submit">保存预算</button>
          </fieldset>
        </form>
      </details>
      {costs && (
        <section className="task-costs" aria-label="费用汇总">
          <dl>
            {[
              ["已结算", costs.settledMicroCny],
              ["已提交占用", costs.reservedMicroCny],
              ["可用余额", balance],
              ["未提交工作估算", costs.remainingWorkMicroCny],
              ["返工情景估算", costs.reworkScenarioMicroCny],
              ["完工预测", costs.forecastMicroCny],
            ].map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>¥ {formatYuan(Number(value))}</dd>
              </div>
            ))}
          </dl>
          {costs.containsUnknown && (
            <p role="status">
              含未知费用：占用仍保留，请核对原调用与结算依据。
            </p>
          )}
          {nearLimit && (
            <p className="notice">
              费用已达到 {budget?.warningPercent}% 预警线，请检查剩余预算。
            </p>
          )}
        </section>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          run(makePlan);
        }}
      >
        <fieldset disabled={blocked}>
          <legend>生成冻结任务计划</legend>
          <div className="settings-fields">
            <label>
              结果类型
              <select
                value={taskStage}
                onChange={(event) => {
                  const value = event.target.value as typeof taskStage;
                  setTaskStage(value);
                  setPhase(
                    value === "story"
                      ? "story_adaptation"
                      : assetType === "location"
                        ? "image_location"
                        : assetType === "prop"
                          ? "image_prop"
                          : "image_character",
                  );
                }}
              >
                <option value="story">文字故事候选</option>
                <option value="image">图像素材候选</option>
              </select>
            </label>
            <label>
              执行模式
              <select
                value={budget?.executionMode ?? mode}
                disabled={!!budget?.executionMode}
                onChange={(e) => setMode(e.target.value as typeof mode)}
              >
                <option value="synthetic">本地练习（不调用模型）</option>
                <option value="real">真实模型（需准入能力）</option>
              </select>
            </label>
            {taskStage === "story" && (
              <label>
                故事阶段
                <select
                  value={phase}
                  onChange={(e) => setPhase(e.target.value as typeof phase)}
                >
                  <option value="story_adaptation">改编</option>
                  <option value="story_outline">大纲</option>
                  <option value="story_scene">场景</option>
                  <option value="story_dialogue">对白</option>
                </select>
              </label>
            )}
            {taskStage === "image" && (
              <>
                <label>
                  素材类型
                  <select
                    value={assetType}
                    onChange={(event) => {
                      const value = event.target.value as typeof assetType;
                      setAssetType(value);
                      setPhase(
                        value === "location"
                          ? "image_location"
                          : value === "prop"
                            ? "image_prop"
                            : "image_character",
                      );
                    }}
                  >
                    <option value="character">角色</option>
                    <option value="location">场景</option>
                    <option value="prop">道具</option>
                  </select>
                </label>
                <label>
                  素材名称
                  <input
                    required
                    maxLength={200}
                    value={assetName}
                    onChange={(event) => setAssetName(event.target.value)}
                  />
                </label>
                <label>
                  身份锚点（每行一项）
                  <textarea
                    required
                    rows={3}
                    value={identityAnchors}
                    onChange={(event) => setIdentityAnchors(event.target.value)}
                  />
                </label>
              </>
            )}
            <label>
              本次意图
              <input
                required
                maxLength={2000}
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
              />
            </label>
            <label>
              候选数量
              <input
                type="number"
                required
                min="1"
                max="8"
                step="1"
                value={candidates}
                onChange={(e) => setCandidates(e.target.value)}
              />
            </label>
          </div>
          <label className="task-check">
            <input
              type="checkbox"
              checked={precheck}
              onChange={(e) => setPrecheck(e.target.checked)}
            />
            包含预检（次数与上限将在计划中列出）
          </label>
          <p className="muted">
            {taskStage === "story"
              ? "使用上方已保存的故事草稿。"
              : "素材名称、类型与身份锚点会先保存为结构化草稿，再冻结进计划。"}
            首个成功计划将固定项目模式；当前真实模型尚无准入路径。
          </p>
          <button type="submit">生成本地计划</button>
        </fieldset>
      </form>
      {plan && (
        <section className="task-plan" aria-label="冻结计划预览">
          <h3>启动前核对</h3>
          <p>
            {plan.executionMode === "synthetic"
              ? "本地练习，不向云端发送"
              : "真实服务调用"}{" "}
            · 候选 {plan.candidates} 个 · 本次最高 ¥{" "}
            {formatYuan(plan.maximumMicroCny)}
          </p>
          <p>
            计划有效至 {new Date(plan.expiresAt).toLocaleString("zh-CN")}
            ；当前余额 ¥ {formatYuan(balance)}
          </p>
          <details open>
            <summary>冻结的实际输入</summary>
            <StoryPlanPreview input={plan.inputPreview} />
          </details>
          <ul>
            {plan.steps.map((step) => {
              const model = plan.models.find((m) => m.stepId === step.id);
              return (
                <li key={step.id}>
                  {step.purpose === "precheck"
                    ? "预检"
                    : step.purpose === "revise"
                      ? "修订"
                      : "生成"}{" "}
                  · 最多 {step.maxCalls} 次 · 最高 ¥{" "}
                  {formatYuan(step.maxMicroCny)}
                  <p>
                    {model
                      ? `${model.providerId} / ${model.modelId} / ${model.region} · 能力 ${model.capabilityVersion}`
                      : "模型信息缺失"}
                  </p>
                  <p>
                    {plan.executionMode === "synthetic"
                      ? "练习披露种类"
                      : "外发内容"}
                    ：
                    {step.disclosure
                      .map((kind) => disclosureLabels[kind])
                      .join("、") || "无"}
                    {step.requestedMs
                      ? ` · 请求时长 ${step.requestedMs / 1000} 秒`
                      : ""}
                  </p>
                </li>
              );
            })}
          </ul>
          <p className="muted">
            价格版本 {plan.priceVersion} · 模板版本 {plan.templateVersion}
          </p>
          <label className="task-check">
            <input
              type="checkbox"
              disabled={blocked}
              checked={accepted}
              onChange={(e) => setAccepted(e.target.checked)}
            />
            我已核对输入、外发内容与最高费用，并接受本次披露
          </label>
          <button
            className="primary-button"
            disabled={blocked || !accepted}
            onClick={() =>
              run(() =>
                mutate("start", "启动任务", (command) =>
                  bridge.start({
                    projectId,
                    command: {
                      ...command,
                      payload: {
                        planId: plan.id,
                        authorizedMaximumMicroCny: plan.maximumMicroCny,
                        disclosureAccepted: true,
                      },
                    },
                  }),
                ),
              )
            }
          >
            确认并启动任务
          </button>
        </section>
      )}
      <section aria-label="持久任务">
        <div className="section-heading">
          <h3>已保存的任务</h3>
          <button
            disabled={!ready || locked}
            onClick={() => run(() => refresh())}
          >
            刷新任务与费用
          </button>
        </div>
        {list.items.length ? (
          <ul className="task-list">
            {list.items.map((item) => (
              <li key={item.id}>
                <button
                  disabled={!ready || locked}
                  onClick={() => run(() => loadTask(item.id))}
                >
                  {taskLabels[item.state]} · {item.id}
                </button>
                {item.active && <span>正在执行</span>}
                {item.observationStopped && <span>已停止本地等待</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">
            还没有任务。保存计划并确认启动后，任务会保留在这里。
          </p>
        )}
        {list.nextCursor && (
          <button
            disabled={!ready || locked}
            onClick={() =>
              run(async () => {
                const r = await bridge.list({
                  projectId,
                  cursor: list.nextCursor!,
                });
                if (r.ok)
                  setList({
                    items: [...list.items, ...r.data.items],
                    nextCursor: r.data.nextCursor,
                  });
                else setMessage(r.error.message);
              })
            }
          >
            更多任务
          </button>
        )}
      </section>
      {task && (
        <section className="task-detail" aria-label="原任务详情">
          <h3>{taskLabels[task.state]}</h3>
          <p>
            任务 {task.id} · 已保存候选 {task.candidateRevisionIds.length} 个
          </p>
          <p className="muted">
            {taskPlan?.executionMode === "synthetic"
              ? "本地合成练习结果，不代表真实模型质量。"
              : taskPlan?.executionMode === "real"
                ? "真实服务结果"
                : "结果来源尚待核对。"}
            选择候选只会打开对照，不会自动采用。
          </p>
          {taskCandidates.taskId === task.id &&
            taskCandidates.items.length > 0 && (
              <section className="task-candidates" aria-label="任务候选结果">
                {taskCandidates.items.map((candidate) => {
                  const display = describeCandidate(
                    projectId,
                    candidate.payload,
                  );
                  return (
                    <article key={candidate.id}>
                      <div>
                        <h4>{display.title}</h4>
                        <p>{display.summary}</p>
                        <small>
                          来源：
                          {taskPlan?.executionMode === "synthetic"
                            ? "本地固定合成"
                            : taskPlan?.executionMode === "real"
                              ? "真实服务"
                              : "尚待核对"}
                          {" · "}候选 {candidate.id.slice(0, 8)}
                        </small>
                      </div>
                      {display.mediaUrl && (
                        <img
                          src={display.mediaUrl}
                          alt={`${display.title}缩略图`}
                          loading="lazy"
                        />
                      )}
                      <button
                        type="button"
                        onClick={() => onCompareCandidate(candidate)}
                      >
                        在版本面板中对照
                      </button>
                    </article>
                  );
                })}
              </section>
            )}
          {task.observationStopped && (
            <p>已停止本地等待；这不代表云端取消，也不会减少费用。</p>
          )}
          <button
            disabled={!ready || locked}
            onClick={() => run(() => loadTask(task.id))}
          >
            查询原任务
          </button>
          {["pending", "partial", "failed"].includes(task.state) && (
            <button
              disabled={blocked}
              onClick={() =>
                run(() =>
                  mutate(
                    "other",
                    "继续原计划未提交步骤",
                    (command) =>
                      bridge.continue({
                        projectId,
                        taskId: task.id,
                        command: {
                          ...command,
                          payload: { confirmedUnsubmittedOnly: true },
                        },
                      }),
                    task.id,
                  ),
                )
              }
            >
              确认继续原计划未提交步骤
            </button>
          )}
          {calls.map((call) => (
            <article key={call.id}>
              <h4>{taskLabels[call.state]}</h4>
              <p>
                {call.providerId} / {call.modelId} / {call.region}
                <br />
                请求时间：{call.requestedAt || "尚未提交"}
              </p>
              <p>
                调用 {call.id}
                {call.remoteTaskId && ` · 远端编号 ${call.remoteTaskId}`}
              </p>
              <p>
                占用 ¥ {formatYuan(call.reservedMicroCny)} ·{" "}
                {call.billingState === "settled"
                  ? `已结算 ¥ ${formatYuan(call.settledMicroCny!)}`
                  : "待核对结算"}
              </p>
              {["result_unknown", "submitting"].includes(call.state) && (
                <p className="notice">
                  请求可能已经受理并计费。仅查询原调用，不重新生成。
                </p>
              )}
              {call.errorCode && (
                <p>
                  {callMessages[call.errorCode] ??
                    "调用状态需要核对，请查询原任务并检查费用依据。"}
                </p>
              )}
              <div className="project-actions">
                {["result_unknown", "running"].includes(call.state) && (
                  <button
                    disabled={blocked}
                    onClick={() => recover(call, "query")}
                  >
                    查询原调用
                  </button>
                )}
                {call.state === "pending_download" && (
                  <button
                    disabled={blocked}
                    onClick={() => recover(call, "download")}
                  >
                    恢复原结果下载
                  </button>
                )}
                {["result_unknown", "running", "pending_download"].includes(
                  call.state,
                ) && (
                  <button
                    disabled={blocked}
                    onClick={() => recover(call, "stop_waiting")}
                  >
                    停止本地等待
                  </button>
                )}
                <button
                  disabled={blocked}
                  onClick={() => {
                    setSettlementCall(call.id);
                    setAmount(
                      call.settledMicroCny === null
                        ? ""
                        : formatYuan(call.settledMicroCny),
                    );
                    setBasis("");
                    setReason("");
                  }}
                >
                  核对或更正结算
                </button>
              </div>
            </article>
          ))}
        </section>
      )}
      {settlementCall && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => {
              const value = parseYuan(amount);
              await mutate(
                "other",
                "保存结算",
                (command) =>
                  bridge.settle({
                    projectId,
                    callId: settlementCall,
                    command: {
                      ...command,
                      payload: {
                        settledMicroCny: value,
                        basis,
                        reason,
                        evidenceMediaIds: [],
                      },
                    },
                  }),
                task?.id ?? null,
              );
            });
          }}
        >
          <fieldset disabled={blocked}>
            <legend>核对调用结算</legend>
            <p>{settlementCall} · 零元结算也必须填写依据与理由。</p>
            <div className="settings-fields">
              <label>
                结算金额（元）
                <input
                  required
                  inputMode="decimal"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                />
              </label>
              <label>
                结算依据
                <input
                  required
                  maxLength={2000}
                  value={basis}
                  onChange={(e) => setBasis(e.target.value)}
                />
              </label>
              <label>
                更正理由
                <input
                  required
                  maxLength={2000}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
            </div>
            <button type="submit">保存结算依据</button>
          </fieldset>
        </form>
      )}
      <details>
        <summary>调用费用明细（{entries.items.length}）</summary>
        <ul>
          {entries.items.map((entry) => (
            <li key={entry.callId}>
              {entry.callId} ·{" "}
              {entry.state === "settled"
                ? `已结算 ¥ ${formatYuan(entry.settledMicroCny!)}`
                : `占用 ¥ ${formatYuan(entry.reservedMicroCny)}`}
              <p>{entry.basis || "尚无结算依据"}</p>
            </li>
          ))}
        </ul>
        {entries.nextCursor && (
          <button
            disabled={!ready || locked}
            onClick={() =>
              run(async () => {
                const r = await bridge.entries({
                  projectId,
                  cursor: entries.nextCursor!,
                });
                if (r.ok)
                  setEntries({
                    items: [...entries.items, ...r.data.items],
                    nextCursor: r.data.nextCursor,
                  });
                else setMessage(r.error.message);
              })
            }
          >
            更多费用明细
          </button>
        )}
      </details>
      <details>
        <summary>登记独立外部开销</summary>
        <p>
          采购、存储与传输单独登记，不伪装成模型调用。练习项目的开销也仅用于模拟核对。
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => {
              const value = parseYuan(expenseAmount);
              const expenseId = crypto.randomUUID();
              await mutate("other", "登记外部开销", (command) =>
                bridge.setExpense({
                  projectId,
                  expenseId,
                  command: {
                    ...command,
                    payload: {
                      expenseId,
                      category,
                      state: expenseState,
                      amountMicroCny: value,
                      basis: expenseBasis,
                    },
                  },
                }),
              );
            });
          }}
        >
          <fieldset disabled={blocked}>
            <div className="settings-fields">
              <label>
                开销类别
                <select
                  value={category}
                  onChange={(e) =>
                    setCategory(e.target.value as typeof category)
                  }
                >
                  <option value="storage">存储</option>
                  <option value="transfer">传输</option>
                  <option value="procurement">采购</option>
                </select>
              </label>
              <label>
                开销状态
                <select
                  value={expenseState}
                  onChange={(e) =>
                    setExpenseState(e.target.value as typeof expenseState)
                  }
                >
                  <option value="estimated">估算</option>
                  <option value="pending">待结算</option>
                  <option value="settled">已结算</option>
                </select>
              </label>
              <label>
                开销金额（元）
                <input
                  required
                  inputMode="decimal"
                  value={expenseAmount}
                  onChange={(e) => setExpenseAmount(e.target.value)}
                />
              </label>
              <label>
                开销依据
                <input
                  required
                  maxLength={2000}
                  value={expenseBasis}
                  onChange={(e) => setExpenseBasis(e.target.value)}
                />
              </label>
            </div>
            <button type="submit">登记外部开销</button>
          </fieldset>
        </form>
      </details>
    </section>
  );
}
