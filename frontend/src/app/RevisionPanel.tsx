import { useCallback, useEffect, useMemo, useState } from "react";
import { z } from "zod";
import {
  projectUuid,
  type ProjectResult,
  type ProjectSession,
} from "../../electron/shared/projects";
import type { MediaJob } from "../../electron/shared/media";
import type {
  ArtifactState,
  CheckReport,
  Impact,
  Revision,
} from "../../electron/shared/versions";
import { StoryPlanPreview } from "./StoryPlanPreview";

const ruleLabels: Record<string, string> = {
  structural: "内容结构",
  references: "引用关系",
};
const scopeLabels: Record<string, string> = {
  identityVisual: "角色视觉一致性",
  dialogueAudio: "对白音频",
  subtitleTiming: "字幕时间",
  referenceInput: "生成参考输入",
  requirementCoverage: "故事要求覆盖",
  revealTiming: "信息揭示节奏",
  timelinePlacement: "时间线位置",
  mix: "声音混合",
  export: "导出结果",
};
const outcomeLabels: Record<CheckReport["outcome"], string> = {
  pass: "通过",
  fail: "未通过",
  unknown: "结果未知",
  not_applicable: "不适用",
};
const uncertainErrors = new Set(["BACKEND_UNAVAILABLE", "PROTOCOL_INVALID"]);

export function validConfirmationReport(
  report: CheckReport | null,
  revisionId: string,
  requiredRuleIds: string[],
): boolean {
  return !!(
    report &&
    report.method === "local" &&
    report.ruleVersion === "local-structure-v1" &&
    report.outcome === "pass" &&
    report.revisionIds.includes(revisionId) &&
    requiredRuleIds.every((ruleId) => report.ruleIds.includes(ruleId))
  );
}

function RevisionContent({ revision }: { revision: Revision | null }) {
  if (!revision)
    return <p className="version-empty">当前还没有可显示的正式版本。</p>;
  return (
    <StoryPlanPreview
      input={{ kind: revision.payload.kind, payload: revision.payload.content }}
    />
  );
}

export function RevisionComparison({
  artifact,
  adopted,
  selected,
  impact,
}: {
  artifact: ArtifactState;
  adopted: Revision | null;
  selected: Revision;
  impact: Impact | null;
}) {
  const same = adopted?.id === selected.id;
  return (
    <section className="version-comparison" aria-label="版本内容对照">
      <div className="version-state-strip" aria-label="版本状态">
        <span>
          <strong>正在查看</strong>
          {same ? "当前采用版本" : "候选版本"}
        </span>
        <span>
          <strong>当前采用</strong>
          {artifact.adoptedRevisionId ? "已有版本" : "尚未采用"}
        </span>
        <span>
          <strong>当前确认</strong>
          {artifact.confirmedRevisionId === artifact.adoptedRevisionId &&
          artifact.confirmedRevisionId
            ? "已确认当前采用"
            : artifact.confirmedRevisionId
              ? "确认仍停留在较早版本"
              : "尚未确认"}
        </span>
        <span>
          <strong>下游状态</strong>
          {artifact.needsUpdate ? "需要更新" : "无需更新"}
        </span>
      </div>
      <div className="version-columns">
        <article>
          <header>
            <h4>当前采用</h4>
            <span>{adopted ? "作品正在使用" : "尚无基准"}</span>
          </header>
          <RevisionContent revision={adopted} />
        </article>
        <article>
          <header>
            <h4>正在查看</h4>
            <span>{same ? "与当前采用相同" : "浏览不会改变作品"}</span>
          </header>
          <RevisionContent revision={selected} />
        </article>
      </div>
      {impact && impact.toRevisionId === selected.id && (
        <section className="version-impact" aria-label="采用影响预览">
          <div className="section-heading">
            <h4>采用影响</h4>
            <span>
              预览有效至{" "}
              {new Date(impact.expiresAt).toLocaleTimeString("zh-CN")}
            </span>
          </div>
          <dl>
            <div>
              <dt>相关成果</dt>
              <dd>{impact.affectedArtifactIds.length} 个</dd>
            </div>
            <div>
              <dt>可能增加的费用</dt>
              <dd>
                {impact.estimatedExtraMicroCny === null
                  ? "额外费用暂时无法确定"
                  : `¥ ${(impact.estimatedExtraMicroCny / 1_000_000).toFixed(2)}`}
              </dd>
            </div>
          </dl>
          <div className="version-impact-lists">
            <div>
              <h5>受影响范围</h5>
              {impact.affectedScopes.length ? (
                <ul>
                  {impact.affectedScopes.map((scope) => (
                    <li key={scope}>
                      {scopeLabels[scope] ?? "需要核对的范围"}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>没有已知的下游影响。</p>
              )}
            </div>
            <div>
              <h5>采用后需要检查</h5>
              {impact.requiredChecks.length ? (
                <ul>
                  {impact.requiredChecks.map((rule) => (
                    <li key={rule}>{ruleLabels[rule] ?? "对应流程检查"}</li>
                  ))}
                </ul>
              ) : (
                <p>没有额外的必要检查。</p>
              )}
            </div>
          </div>
        </section>
      )}
    </section>
  );
}

type PendingOperation = {
  kind: "create" | "adopt" | "confirm" | "undo" | "runChecks";
  operationId: string;
  expectedRevision: number;
  targetRevisionId?: string;
};

type VersionReceipt = {
  operationId: string;
  committedRevision: number;
  resourceId: string;
  state: string;
};

export function receiptForPendingVersionOperation<T extends VersionReceipt>(
  pending: PendingOperation,
  outerOperationId: string,
  receipt: T,
): T | null {
  return outerOperationId === pending.operationId &&
    receipt.operationId === pending.operationId
    ? receipt
    : null;
}

const checkJobHandleSchema = z.strictObject({
  jobId: projectUuid,
  targetRevisionId: projectUuid,
});
type CheckJobHandle = z.infer<typeof checkJobHandleSchema>;
type CheckJobInspection =
  | { state: "pending"; handle: CheckJobHandle }
  | { state: "report"; handle: CheckJobHandle; report: CheckReport }
  | { state: "retry"; handle: CheckJobHandle; message: string }
  | { state: "terminal"; handle: CheckJobHandle; message: string };

export async function inspectCheckJob(
  handle: CheckJobHandle,
  getJob: () => Promise<ProjectResult<MediaJob>>,
  getReport: (checkId: string) => Promise<ProjectResult<CheckReport>>,
): Promise<CheckJobInspection> {
  const job = await getJob();
  if (!job.ok) return { state: "retry", handle, message: job.error.message };
  if (job.data.state === "queued" || job.data.state === "running")
    return { state: "pending", handle };
  if (job.data.state === "failed" || job.data.state === "cancelled")
    return {
      state: "terminal",
      handle,
      message: "本地检查未完成。候选与当前采用内容均已保留。",
    };
  if (!job.data.resultId)
    return {
      state: "retry",
      handle,
      message: "检查已结束但报告尚不可读取，请查询这次检查。",
    };
  const report = await getReport(job.data.resultId);
  return report.ok
    ? { state: "report", handle, report: report.data }
    : { state: "retry", handle, message: report.error.message };
}

export function RevisionPanel({
  session,
  ready,
  locked,
  action,
  prepareMutation,
  advanceDraftRevision,
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
}) {
  const [artifact, setArtifact] = useState<ArtifactState | null>(null);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [draft, setDraft] = useState<{
    id: string;
    artifactId: string;
  } | null>(null);
  const [impact, setImpact] = useState<Impact | null>(null);
  const [report, setReport] = useState<CheckReport | null>(null);
  const checkJobKey = `version-check-job:${session.projectId}`;
  const [checkJob, updateCheckJob] = useState<CheckJobHandle | null>(() => {
    try {
      const parsed = checkJobHandleSchema.safeParse(
        JSON.parse(localStorage.getItem(checkJobKey) ?? "null"),
      );
      return parsed.success ? parsed.data : null;
    } catch {
      return null;
    }
  });
  const [checking, setChecking] = useState(false);
  const [pending, setPending] = useState<PendingOperation | null>(null);
  const [lastAdoptionId, setLastAdoptionId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [refreshRequired, setRefreshRequired] = useState(false);
  const [loading, setLoading] = useState(true);

  function retainCheckJob(value: CheckJobHandle) {
    localStorage.setItem(checkJobKey, JSON.stringify(value));
    updateCheckJob(value);
  }

  const loadState = useCallback(
    async (targetRevisionId?: string) => {
      setLoading(true);
      const [draftsResult, projectResult] = await Promise.all([
        window.desktop.projects.drafts.list({ projectId: session.projectId }),
        window.desktop.projects.drafts.project({
          projectId: session.projectId,
        }),
      ]);
      if (!draftsResult.ok || !projectResult.ok) {
        if (!draftsResult.ok) setMessage(draftsResult.error.message);
        else if (!projectResult.ok) setMessage(projectResult.error.message);
        setLoading(false);
        return;
      }
      const story = draftsResult.data.find((item) => item.kind === "story");
      setRefreshRequired(false);
      if (!story) {
        setDraft(null);
        setArtifact(null);
        setRevisions([]);
        setSelectedId(null);
        setLoading(false);
        return;
      }
      setDraft({ id: story.id, artifactId: story.artifactId });
      const artifactResult = await window.desktop.versions.artifact({
        projectId: session.projectId,
        artifactId: story.artifactId,
      });
      if (!artifactResult.ok) {
        if (artifactResult.error.code === "OBJECT_NOT_FOUND") {
          setArtifact(null);
          setRevisions([]);
          setSelectedId(null);
          setNextCursor(null);
          setLastAdoptionId(null);
        } else setMessage(artifactResult.error.message);
        setLoading(false);
        return;
      }
      const state = artifactResult.data;
      const wanted = new Set(
        [
          state.adoptedRevisionId,
          state.confirmedRevisionId,
          targetRevisionId,
        ].filter((id): id is string => !!id),
      );
      const items: Revision[] = [];
      let cursor: string | undefined;
      let remainingCursor: string | null = null;
      do {
        const page = await window.desktop.versions.list({
          projectId: session.projectId,
          artifactId: story.artifactId,
          cursor,
          limit: 1,
        });
        if (!page.ok) {
          setMessage(page.error.message);
          break;
        }
        for (const item of page.data.items)
          if (!items.some((known) => known.id === item.id)) items.push(item);
        remainingCursor = page.data.nextCursor;
        for (const id of [...wanted])
          if (items.some((item) => item.id === id)) wanted.delete(id);
        cursor = page.data.nextCursor ?? undefined;
      } while (cursor && wanted.size > 0);
      setArtifact(state);
      setLastAdoptionId(state.latestAdoptionId);
      setRevisions(items);
      setNextCursor(remainingCursor);
      setSelectedId((current) => {
        if (
          targetRevisionId &&
          items.some((item) => item.id === targetRevisionId)
        )
          return targetRevisionId;
        if (current && items.some((item) => item.id === current))
          return current;
        return items[0]?.id ?? state.adoptedRevisionId;
      });
      setLoading(false);
    },
    [session.projectId],
  );

  useEffect(() => {
    void (async () => {
      await loadState(checkJob?.targetRevisionId);
      if (checkJob) await pollCheck(checkJob);
    })();
    // The persisted handle is recovered once per project mount. New jobs call pollCheck directly.
  }, [loadState]);

  const selected = useMemo(
    () => revisions.find((item) => item.id === selectedId) ?? null,
    [revisions, selectedId],
  );
  const adopted = useMemo(
    () =>
      revisions.find((item) => item.id === artifact?.adoptedRevisionId) ?? null,
    [artifact?.adoptedRevisionId, revisions],
  );
  const requiredRules = impact?.requiredChecks ?? ["structural", "references"];
  const canConfirmSelected = selected
    ? validConfirmationReport(report, selected.id, requiredRules)
    : false;
  const disabled = !ready || locked || session.mode === "read" || !!pending;

  function acceptFailure(
    failure: { code: string; message: string },
    pendingOperation: PendingOperation,
  ) {
    setMessage(failure.message);
    if (failure.code === "PREVIEW_STALE") setImpact(null);
    if (uncertainErrors.has(failure.code)) setPending(pendingOperation);
    else {
      setPending(null);
      if (failure.code === "REVISION_CONFLICT") setRefreshRequired(true);
    }
  }

  async function projectHead(): Promise<number | null> {
    const result = await window.desktop.projects.drafts.project({
      projectId: session.projectId,
    });
    if (!result.ok) {
      setMessage(result.error.message);
      return null;
    }
    return result.data.revision;
  }

  async function createCandidate() {
    await action(async () => {
      if (!(await prepareMutation())) return;
      const head = await projectHead();
      const drafts = await window.desktop.projects.drafts.list({
        projectId: session.projectId,
      });
      const story = drafts.ok
        ? drafts.data.find((item) => item.kind === "story")
        : null;
      if (head === null || !story) {
        setMessage(drafts.ok ? "故事草稿尚未准备好。" : drafts.error.message);
        return;
      }
      const operation: PendingOperation = {
        kind: "create",
        operationId: crypto.randomUUID(),
        expectedRevision: head,
      };
      setPending(operation);
      setMessage("");
      const result = await window.desktop.versions.create({
        projectId: session.projectId,
        artifactId: story.artifactId,
        command: {
          clientOperationId: operation.operationId,
          expectedRevision: head,
          payload: { draftId: story.id },
        },
      });
      if (!result.ok) return acceptFailure(result.error, operation);
      const receipt = receiptForPendingVersionOperation(
        operation,
        result.data.operationId,
        result.data,
      );
      if (!receipt) {
        setMessage("候选回执与原操作不匹配，请只查询原操作。");
        return;
      }
      setPending(null);
      advanceDraftRevision(head, receipt.committedRevision);
      setImpact(null);
      setReport(null);
      await loadState(receipt.resourceId);
      setMessage("候选已保存。当前采用与确认状态没有改变。");
    });
  }

  async function loadMore() {
    if (!draft || !nextCursor) return;
    const page = await window.desktop.versions.list({
      projectId: session.projectId,
      artifactId: draft.artifactId,
      cursor: nextCursor,
      limit: 1,
    });
    if (!page.ok) return setMessage(page.error.message);
    setRevisions((current) => [
      ...current,
      ...page.data.items.filter(
        (item) => !current.some((known) => known.id === item.id),
      ),
    ]);
    setNextCursor(page.data.nextCursor);
  }

  async function previewAdoption() {
    if (!draft || !selected) return;
    await action(async () => {
      if (!(await prepareMutation())) return;
      const head = await projectHead();
      if (head === null) return;
      const result = await window.desktop.versions.preview({
        projectId: session.projectId,
        artifactId: draft.artifactId,
        toRevisionId: selected.id,
        expectedRevision: head,
      });
      if (result.ok) {
        setImpact(result.data);
        setMessage("");
      } else {
        setImpact(null);
        setMessage(result.error.message);
        if (result.error.code === "REVISION_CONFLICT") setRefreshRequired(true);
      }
    });
  }

  async function pollCheck(handle: CheckJobHandle) {
    setChecking(true);
    for (let attempt = 0; attempt < 20; attempt++) {
      const result = await inspectCheckJob(
        handle,
        () =>
          window.desktop.projects.media.job({
            projectId: session.projectId,
            jobId: handle.jobId,
          }),
        (checkId) =>
          window.desktop.versions.report({
            projectId: session.projectId,
            checkId,
          }),
      );
      if (result.state === "retry" || result.state === "terminal") {
        setMessage(result.message);
        setChecking(false);
        return;
      }
      if (result.state === "report") {
        setReport(result.report);
        setMessage(
          result.report.outcome === "pass"
            ? "本地结构与引用检查已完成。"
            : "本地检查已完成，请查看结果后再确认。",
        );
        setChecking(false);
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    setMessage("本地检查仍在进行，可以稍后重新读取版本状态。");
    setChecking(false);
    if (selectedId !== handle.targetRevisionId) setReport(null);
  }

  async function runChecks() {
    if (!selected) return;
    await action(async () => {
      if (!(await prepareMutation())) return;
      const head = await projectHead();
      if (head === null) return;
      const operation: PendingOperation = {
        kind: "runChecks",
        operationId: crypto.randomUUID(),
        expectedRevision: head,
        targetRevisionId: selected.id,
      };
      setPending(operation);
      setMessage("");
      const result = await window.desktop.versions.runChecks({
        projectId: session.projectId,
        command: {
          clientOperationId: operation.operationId,
          expectedRevision: head,
          payload: {
            revisionIds: [selected.id],
            ruleIds: ["structural", "references"],
          },
        },
      });
      if (!result.ok) return acceptFailure(result.error, operation);
      const receipt = receiptForPendingVersionOperation(
        operation,
        result.data.operationId,
        result.data,
      );
      if (!receipt) {
        setMessage("检查回执与原操作不匹配，请只查询原操作。");
        return;
      }
      setPending(null);
      advanceDraftRevision(head, receipt.committedRevision);
      setImpact(null);
      const handle = {
        jobId: receipt.resourceId,
        targetRevisionId: selected.id,
      };
      retainCheckJob(handle);
      await pollCheck(handle);
    });
  }

  async function adoptSelected() {
    if (!draft || !selected || !impact || impact.toRevisionId !== selected.id)
      return;
    await action(async () => {
      if (!(await prepareMutation())) return;
      const head = await projectHead();
      if (head === null) return;
      const operation: PendingOperation = {
        kind: "adopt",
        operationId: crypto.randomUUID(),
        expectedRevision: head,
        targetRevisionId: selected.id,
      };
      setPending(operation);
      setMessage("");
      const result = await window.desktop.versions.adopt({
        projectId: session.projectId,
        artifactId: draft.artifactId,
        command: {
          clientOperationId: operation.operationId,
          expectedRevision: head,
          payload: {
            previewId: impact.previewId,
            toRevisionId: selected.id,
            confirm: canConfirmSelected,
          },
        },
      });
      if (!result.ok) return acceptFailure(result.error, operation);
      const receipt = receiptForPendingVersionOperation(
        operation,
        result.data.operationId,
        result.data,
      );
      if (!receipt) {
        setMessage("采用回执与原操作不匹配，请只查询原操作。");
        return;
      }
      setPending(null);
      advanceDraftRevision(head, receipt.committedRevision);
      setLastAdoptionId(receipt.resourceId);
      setImpact(null);
      await loadState(selected.id);
      setMessage(
        canConfirmSelected
          ? "候选已采用并确认。"
          : "候选已采用，必要检查通过后才能确认。",
      );
    });
  }

  async function confirmSelected() {
    if (!draft || !selected || !report || !canConfirmSelected) return;
    await action(async () => {
      if (!(await prepareMutation())) return;
      const head = await projectHead();
      if (head === null) return;
      const operation: PendingOperation = {
        kind: "confirm",
        operationId: crypto.randomUUID(),
        expectedRevision: head,
        targetRevisionId: selected.id,
      };
      setPending(operation);
      const result = await window.desktop.versions.confirm({
        projectId: session.projectId,
        artifactId: draft.artifactId,
        command: {
          clientOperationId: operation.operationId,
          expectedRevision: head,
          payload: { revisionId: selected.id, checkIds: [report.id] },
        },
      });
      if (!result.ok) return acceptFailure(result.error, operation);
      const receipt = receiptForPendingVersionOperation(
        operation,
        result.data.operationId,
        result.data,
      );
      if (!receipt) {
        setMessage("确认回执与原操作不匹配，请只查询原操作。");
        return;
      }
      setPending(null);
      advanceDraftRevision(head, receipt.committedRevision);
      await loadState(selected.id);
      setMessage("当前采用版本已确认。");
    });
  }

  async function undoLatest() {
    if (!lastAdoptionId) return;
    await action(async () => {
      if (!(await prepareMutation())) return;
      const head = await projectHead();
      if (head === null) return;
      const operation: PendingOperation = {
        kind: "undo",
        operationId: crypto.randomUUID(),
        expectedRevision: head,
      };
      setPending(operation);
      const result = await window.desktop.versions.undo({
        projectId: session.projectId,
        adoptionId: lastAdoptionId,
        command: {
          clientOperationId: operation.operationId,
          expectedRevision: head,
          payload: { adoptionId: lastAdoptionId },
        },
      });
      if (!result.ok) return acceptFailure(result.error, operation);
      const receipt = receiptForPendingVersionOperation(
        operation,
        result.data.operationId,
        result.data,
      );
      if (!receipt) {
        setMessage("撤销回执与原操作不匹配，请只查询原操作。");
        return;
      }
      setPending(null);
      advanceDraftRevision(head, receipt.committedRevision);
      setLastAdoptionId(null);
      setImpact(null);
      setReport(null);
      await loadState();
      setMessage("最近一次采用已撤销；候选、素材与已有费用记录仍保留。");
    });
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
      const receipt = receiptForPendingVersionOperation(
        pending,
        result.data.operationId,
        result.data.receipt,
      );
      if (!receipt) {
        setMessage("原操作回执不匹配，请继续查询原操作。");
        return;
      }
      const completed = pending;
      setPending(null);
      advanceDraftRevision(
        completed.expectedRevision,
        receipt.committedRevision,
      );
      if (completed.kind === "adopt") setLastAdoptionId(receipt.resourceId);
      if (completed.kind === "runChecks" && completed.targetRevisionId) {
        const handle = {
          jobId: receipt.resourceId,
          targetRevisionId: completed.targetRevisionId,
        };
        retainCheckJob(handle);
        await pollCheck(handle);
      } else await loadState(completed.targetRevisionId);
    });
  }

  return (
    <section className="revision-panel" aria-label="故事版本">
      <div className="section-heading">
        <h2>故事版本</h2>
        <span>候选、采用与确认分别记录</span>
      </div>
      <p>
        保存候选会冻结当前草稿内容。浏览和放弃候选不会改变作品，也不会产生模型费用。
      </p>
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      {pending && (
        <section className="version-pending" aria-label="待核对操作">
          <h3>操作结果尚待核对</h3>
          <p>原操作编号已保留。请只查询这次操作，避免重复采用或检查。</p>
          <button
            disabled={!ready || locked}
            onClick={() => void queryPending()}
          >
            查询原操作
          </button>
        </section>
      )}
      {refreshRequired && !pending && (
        <p>
          项目版本已变化。核对当前状态后再创建新的操作。{" "}
          <button
            className="text-button"
            disabled={!ready || locked}
            onClick={() => void loadState(selectedId ?? undefined)}
          >
            重新读取版本状态
          </button>
        </p>
      )}
      <div className="version-toolbar">
        <button
          className="primary-button"
          disabled={disabled || refreshRequired}
          onClick={() => void createCandidate()}
        >
          保存为新候选
        </button>
        {session.mode === "read" && <span>只读模式只能浏览已有候选。</span>}
        {checking && <span role="status">正在执行本地结构检查…</span>}
        {checkJob && !checking && checkJob.targetRevisionId === selectedId && (
          <button
            disabled={!ready || locked}
            onClick={() => void action(() => pollCheck(checkJob))}
          >
            查询这次检查
          </button>
        )}
      </div>
      {loading ? (
        <p role="status">正在读取版本状态…</p>
      ) : revisions.length === 0 ? (
        <div className="version-empty-state">
          <h3>还没有正式候选</h3>
          <p>草稿可以继续保持未完成；准备核对时，再保存第一个候选。</p>
        </div>
      ) : (
        <>
          <div className="version-workspace">
            <aside aria-label="候选历史">
              <h3>候选历史</h3>
              <ol>
                {revisions.map((item) => (
                  <li key={item.id}>
                    <button
                      className={item.id === selectedId ? "selected" : ""}
                      aria-pressed={item.id === selectedId}
                      onClick={() => {
                        setSelectedId(item.id);
                        setImpact(null);
                        if (!report?.revisionIds.includes(item.id))
                          setReport(null);
                      }}
                    >
                      <strong>候选</strong>
                      <span>
                        {new Date(item.createdAt).toLocaleString("zh-CN")}
                      </span>
                      <small>
                        {item.id === artifact?.adoptedRevisionId && "当前采用"}
                        {item.id === artifact?.confirmedRevisionId &&
                          `${item.id === artifact?.adoptedRevisionId ? " · " : ""}已确认`}
                      </small>
                    </button>
                  </li>
                ))}
              </ol>
              {nextCursor && (
                <button
                  disabled={!ready || locked}
                  onClick={() => void loadMore()}
                >
                  加载更多候选
                </button>
              )}
            </aside>
            <div className="version-detail">
              {artifact && selected && (
                <RevisionComparison
                  artifact={artifact}
                  adopted={adopted}
                  selected={selected}
                  impact={impact}
                />
              )}
              {report &&
                selected &&
                report.revisionIds.includes(selected.id) && (
                  <section className="version-report" aria-label="本地检查报告">
                    <div className="section-heading">
                      <h4>本地检查报告</h4>
                      <span>{outcomeLabels[report.outcome]}</span>
                    </div>
                    <p>
                      检查范围：
                      {report.ruleIds
                        .map((rule) => ruleLabels[rule] ?? rule)
                        .join("、")}
                    </p>
                    <p>{report.limitations || "没有补充限制说明。"}</p>
                    <p className="muted">
                      这份报告只说明确定性的结构与引用结果，不代表语义、审美、模型质量或人工审核结论。
                    </p>
                  </section>
                )}
              <div className="version-actions" aria-label="版本操作">
                <button
                  disabled={
                    disabled || !selected || checking || refreshRequired
                  }
                  onClick={() => void runChecks()}
                >
                  运行本地结构检查
                </button>
                {selected &&
                  selected.id !== artifact?.adoptedRevisionId &&
                  (impact?.toRevisionId === selected.id ? (
                    <button
                      className="primary-button"
                      disabled={disabled || refreshRequired}
                      onClick={() => void adoptSelected()}
                    >
                      {canConfirmSelected ? "采用并确认" : "采用并标记待审核"}
                    </button>
                  ) : (
                    <button
                      className="primary-button"
                      disabled={
                        !ready || locked || !!pending || refreshRequired
                      }
                      onClick={() => void previewAdoption()}
                    >
                      预览采用影响
                    </button>
                  ))}
                {selected &&
                  selected.id === artifact?.adoptedRevisionId &&
                  selected.id !== artifact?.confirmedRevisionId && (
                    <button
                      className="primary-button"
                      disabled={
                        disabled || !canConfirmSelected || refreshRequired
                      }
                      onClick={() => void confirmSelected()}
                    >
                      确认当前采用版本
                    </button>
                  )}
                {impact && (
                  <button
                    disabled={!ready || locked || !!pending}
                    onClick={() => {
                      setImpact(null);
                      setMessage("已放弃本次采用；当前作品没有改变。");
                    }}
                  >
                    放弃这次候选
                  </button>
                )}
                {lastAdoptionId && (
                  <button disabled={disabled} onClick={() => void undoLatest()}>
                    撤销最近一次采用
                  </button>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
