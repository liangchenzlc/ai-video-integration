import { useEffect, useState } from "react";
import { productionRoutes } from "../../electron/shared/production";

type Pending = {
  operationId: string;
  projectId: string | null;
  includeProject: boolean;
  includeContent: boolean;
  targetGrantId: string;
};
const pendingKey = "diagnostic-pending";
const jobKey = "diagnostic-job";
const jobStateNames: Record<string, string> = {
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export function DiagnosticsPanel({
  ready,
  projectId,
  active = true,
}: {
  ready: boolean;
  projectId?: string;
  active?: boolean;
}) {
  const [includeProject, setIncludeProject] = useState(false);
  const [includeContent, setIncludeContent] = useState(false);
  const [files, setFiles] = useState<{ name: string; description: string }[]>(
    [],
  );
  const [choice, setChoice] = useState<{
    grantId: string;
    name: string;
    exists: boolean;
  } | null>(null);
  const [pending, setPending] = useState<Pending | null>(() => {
    try {
      const item = JSON.parse(
        localStorage.getItem(pendingKey) ?? "null",
      ) as Pending | null;
      return item && typeof item.operationId === "string"
        ? {
            ...item,
            projectId:
              typeof item.projectId === "string" ? item.projectId : null,
          }
        : null;
    } catch {
      return null;
    }
  });
  const [jobId, setJobId] = useState(() => localStorage.getItem(jobKey) ?? "");
  const [jobState, setJobState] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (pending) localStorage.setItem(pendingKey, JSON.stringify(pending));
    else localStorage.removeItem(pendingKey);
    window.dispatchEvent(new Event("diagnostic-state-updated"));
  }, [pending]);
  useEffect(() => {
    if (jobId) localStorage.setItem(jobKey, jobId);
    else localStorage.removeItem(jobKey);
    window.dispatchEvent(new Event("diagnostic-state-updated"));
  }, [jobId]);
  useEffect(() => {
    setJobState("");
  }, [jobId]);
  useEffect(() => {
    setFiles([]);
    setChoice(null);
    if (!projectId) {
      setIncludeProject(false);
      setIncludeContent(false);
    }
  }, [projectId]);
  useEffect(() => {
    if (
      !ready ||
      !active ||
      !jobId ||
      ["succeeded", "failed", "cancelled"].includes(jobState)
    )
      return;
    let alive = true;
    async function refreshJob() {
      const result = await window.desktop.settings.job({ jobId });
      if (alive && result.ok) setJobState(result.data.state);
    }
    void refreshJob();
    const timer = setInterval(() => {
      void refreshJob();
    }, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [ready, active, jobId, jobState]);
  useEffect(() => {
    const sync = () => {
      const stored = localStorage.getItem(pendingKey);
      try {
        setPending((current) =>
          JSON.stringify(current) === (stored ?? "null")
            ? current
            : (JSON.parse(stored ?? "null") as Pending | null),
        );
      } catch {
        setPending(null);
      }
      setJobId((current) => {
        const storedJob = localStorage.getItem(jobKey) ?? "";
        return current === storedJob ? current : storedJob;
      });
    };
    window.addEventListener("diagnostic-state-updated", sync);
    return () => window.removeEventListener("diagnostic-state-updated", sync);
  }, []);
  async function run(work: () => Promise<void>) {
    if (!ready || busy) return;
    setBusy(true);
    setMessage("");
    try {
      await work();
    } catch {
      setMessage("结果暂未确认。请用原操作编号查询或重试。");
    } finally {
      setBusy(false);
    }
  }
  async function preview() {
    await run(async () => {
      const result = await window.desktop.production.diagnosticPreview({
        includeProject: includeProject && !!projectId,
        includeContent,
        projectId: includeProject && projectId ? projectId : null,
      });
      if (result.ok) setFiles(result.data.files);
      else setMessage(result.error.message);
    });
  }
  async function choose() {
    await run(async () => {
      const result = await window.desktop.production.chooseTarget({
        purpose: "diagnostic",
      });
      if (result.ok) setChoice(result.data);
      else setMessage(result.error.message);
    });
  }
  async function submit(item: Pending) {
    const input = productionRoutes.diagnostic.input.safeParse({
      command: {
        clientOperationId: item.operationId,
        expectedRevision: 0,
        payload: {
          includeProject: item.includeProject,
          includeContent: item.includeContent,
          projectId: item.projectId,
          targetGrantId: item.targetGrantId,
        },
      },
    });
    if (!input.success) {
      setMessage("原诊断命令无效，请重新预览。");
      setPending(null);
      return;
    }
    const result = await window.desktop.production.diagnostic(input.data);
    if (!result.ok) {
      setMessage(result.error.message);
      if (
        [
          "VALIDATION_FAILED",
          "REQUEST_INVALID",
          "OBJECT_NOT_FOUND",
          "OPERATION_ID_REUSED",
          "GRANT_REJECTED",
          "TARGET_EXISTS",
          "DIAGNOSTIC_CONTENT_LIMIT",
        ].includes(result.error.code)
      ) {
        setPending(null);
        setChoice(null);
        setFiles([]);
      }
      return;
    }
    if (
      result.data.operationId !== item.operationId ||
      result.data.committedRevision !== 0
    )
      return setMessage("回执不匹配，请查询原操作。");
    accept(item.operationId, result.data.resourceId);
  }
  function accept(operationId: string, resourceId: string) {
    if (pending?.operationId && pending.operationId !== operationId) return;
    setPending(null);
    setJobId(resourceId);
    setJobState("running");
    setMessage("诊断包作业已登记。文件只保存在所选本机位置，不会自动发送。");
  }
  async function query() {
    if (!pending) return;
    await run(async () => {
      const result = await window.desktop.projects.operation({
        operationId: pending.operationId,
      });
      if (!result.ok) return setMessage(result.error.message);
      if (
        result.data.receipt.operationId !== pending.operationId ||
        result.data.receipt.committedRevision !== 0
      )
        return setMessage("原操作回执不匹配。");
      accept(pending.operationId, result.data.receipt.resourceId);
    });
  }
  async function poll() {
    if (!jobId) return;
    await run(async () => {
      const result = await window.desktop.settings.job({ jobId });
      if (result.ok) setJobState(result.data.state);
      else setMessage(result.error.message);
    });
  }
  return (
    <section className="production-command" aria-label="本地诊断包">
      <h3>本地诊断包</h3>
      <p>
        默认只含运行环境版本，可选择加入项目状态计数。项目无法打开时也可生成基础诊断包。
      </p>
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      <label className="check-option">
        <input
          type="checkbox"
          checked={includeProject}
          disabled={!projectId || busy || !!pending}
          onChange={(e) => {
            setIncludeProject(e.target.checked);
            if (!e.target.checked) setIncludeContent(false);
            setFiles([]);
            setChoice(null);
          }}
        />
        包含当前项目状态
      </label>
      <label className="check-option">
        <input
          type="checkbox"
          checked={includeContent}
          disabled={!projectId || busy || !!pending}
          onChange={(e) => {
            setIncludeContent(e.target.checked);
            if (e.target.checked) setIncludeProject(true);
            setFiles([]);
            setChoice(null);
          }}
        />
        包含创作正文（仍做脱敏）
      </label>
      <button
        type="button"
        disabled={!ready || busy || !!pending}
        onClick={() => void preview()}
      >
        预览文件清单
      </button>
      {files.length > 0 && (
        <div className="production-preview">
          <h4>将包含的文件</h4>
          <ul>
            {files.map((f) => (
              <li key={f.name}>
                {f.name}：{f.description}
              </li>
            ))}
          </ul>
          <button
            type="button"
            disabled={!ready || busy || !!pending}
            onClick={() => void choose()}
          >
            选择本机保存位置
          </button>
          <span>{choice?.name ?? "尚未选择目标"}</span>
          {choice?.exists && (
            <p className="notice">目标已存在，请选择未使用的诊断包文件名。</p>
          )}
          <button
            type="button"
            disabled={!ready || busy || !!pending || !choice || choice.exists}
            onClick={() =>
              void run(async () => {
                if (!choice) return;
                const item = {
                  operationId: crypto.randomUUID(),
                  projectId: includeProject && projectId ? projectId : null,
                  includeProject: includeProject && !!projectId,
                  includeContent,
                  targetGrantId: choice.grantId,
                };
                setPending(item);
                await submit(item);
              })
            }
          >
            生成并保存诊断包
          </button>
        </div>
      )}
      {pending && (
        <div className="notice">
          <p>原操作结果待核对。操作编号 {pending.operationId}</p>
          <button
            type="button"
            disabled={!ready || busy}
            onClick={() => void query()}
          >
            查询原操作
          </button>
          <button
            type="button"
            disabled={
              !ready || busy || (pending.includeProject && !pending.projectId)
            }
            onClick={() => void run(() => submit(pending))}
          >
            用原编号重试
          </button>
        </div>
      )}
      {jobId && (
        <div className="production-preview">
          <p>
            本地作业 {jobId.slice(0, 8)}：{jobStateNames[jobState] ?? "待查询"}
          </p>
          <button
            type="button"
            disabled={!ready || busy}
            onClick={() => void poll()}
          >
            刷新保存状态
          </button>
        </div>
      )}
    </section>
  );
}
