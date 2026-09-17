import { useEffect, useState } from "react";
import type {
  DesktopBridge,
  RuntimeSnapshot,
} from "../../electron/shared/runtime";
import { safeError } from "../../electron/shared/runtime";
import { Sidebar, type MainPage } from "../components/layout/Sidebar";
import type { AssetKind } from "../features/assets/asset-model";
import { AssetsPage } from "../pages/assets/AssetsPage";
import { AiConfigPage } from "../pages/ai-config/AiConfigPage";
import { ProjectsPage } from "../pages/projects/ProjectsPage";

declare global {
  interface Window {
    desktop: DesktopBridge;
  }
}

const statusText: Record<RuntimeSnapshot["state"], string> = {
  stopped: "本地服务已停止",
  starting: "正在启动本地服务",
  ready: "本地服务已连接",
  disconnected: "本地服务连接中断",
  stopping: "正在关闭本地服务",
  failed: "本地服务启动或停止失败",
  incompatible: "应用与本地服务版本不匹配",
};

export function App() {
  const [page, setPage] = useState<MainPage>("projects");
  const [kind, setKind] = useState<AssetKind>("character");
  const [projectView, setProjectView] = useState<"list" | "detail" | "episode">(
    "list",
  );
  const [runtime, setRuntime] = useState<RuntimeSnapshot | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    if (!window.desktop) {
      setMessage("桌面连接未能载入，请关闭应用并重新打开。");
      return;
    }
    const accept = (snapshot: RuntimeSnapshot) => {
      if (active)
        setRuntime((previous) =>
          !previous || snapshot.revision > previous.revision
            ? snapshot
            : previous,
        );
    };
    const unsubscribe = window.desktop.onRuntimeStateChanged(accept);
    void window.desktop.getRuntimeState().then((result) => {
      if (!active) return;
      if (result.ok) accept(result.data);
      else setMessage(result.error.message);
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  const state = runtime?.state ?? "starting";
  async function restart() {
    if (!runtime?.canRestart || busy) return;
    setBusy(true);
    try {
      const result = await window.desktop.restartBackend({
        expectedGeneration: runtime.generation,
      });
      if (!result.ok) setMessage(result.error.message);
    } finally {
      setBusy(false);
    }
  }
  function select(next: MainPage, nextKind?: AssetKind) {
    setPage(next);
    if (nextKind) setKind(nextKind);
    setProjectView("list");
  }
  const detail = page === "projects" && projectView !== "list";
  return (
    <div
      className={
        detail ? `studio studio-detail studio-${projectView}` : "studio"
      }
    >
      <a className="skip-link" href="#main">
        跳到主内容
      </a>
      {!detail && <Sidebar page={page} kind={kind} onSelect={select} />}
      <div className="studio-content">
        {!detail && (
          <header className="studio-topbar">
            <span>AI 短剧工作台</span>
            <span
              className={`connection ${state}`}
              data-testid="runtime-status"
            >
              <i aria-hidden="true" />
              {statusText[state]}
            </span>
          </header>
        )}
        <main id="main" tabIndex={-1} className="studio-main">
          {message && (
            <p className="notice" role="alert">
              {message}
            </p>
          )}
          {state !== "ready" && (
            <div className="studio-runtime" role="status">
              <div>
                <strong>{statusText[state]}</strong>
                <p>
                  {runtime?.errorCode
                    ? safeError(runtime.errorCode).message
                    : "项目服务启动后即可创建或打开项目。"}
                </p>
              </div>
              <button
                disabled={!runtime?.canRestart || busy}
                onClick={() => void restart()}
              >
                重启本地服务
              </button>
            </div>
          )}
          <div hidden={page !== "projects"} className="studio-projects">
            <ProjectsPage
              ready={state === "ready"}
              runtimeId={runtime?.runtimeId ?? null}
              view={projectView}
              onEnter={() => {
                setPage("projects");
                setProjectView("detail");
              }}
              onExit={() => {
                setProjectView("list");
              }}
              onEpisode={() => setProjectView("episode")}
              onEpisodeBack={() => setProjectView("detail")}
            />
          </div>
          {page === "assets" && <AssetsPage kind={kind} />}
          {page === "ai" && <AiConfigPage />}
        </main>
      </div>
    </div>
  );
}
