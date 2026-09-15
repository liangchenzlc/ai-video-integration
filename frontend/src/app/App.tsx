import { useEffect, useState } from "react";
import type {
  DesktopBridge,
  RuntimeSnapshot,
  CapabilitiesData,
} from "../../electron/shared/runtime";
import { safeError } from "../../electron/shared/runtime";
declare global {
  interface Window {
    desktop: DesktopBridge;
  }
}

const pages = [
  {
    name: "故事",
    summary: "从一个想法开始，整理故事、人物与场景。",
    next: "故事编辑与确认",
    step: "构思",
  },
  {
    name: "视觉与分镜",
    summary: "确定角色与场景的视觉，再把故事拆成可制作的镜头。",
    next: "视觉资产、分镜与参考管理",
    step: "规划",
  },
  {
    name: "镜头制作",
    summary: "逐镜准备关键帧、生成视频，并选择要采用的结果。",
    next: "关键帧与单镜头视频生成",
    step: "制作",
  },
  {
    name: "声音与剪辑",
    summary: "安排配音、字幕与镜头节奏，完成基础声音混合。",
    next: "配音、预演、时间线与混音",
    step: "剪辑",
  },
  {
    name: "检查与导出",
    summary: "检查素材与成片问题，确认后导出 MP4。",
    next: "成片检查、修订与正式导出",
    step: "交付",
  },
  {
    name: "项目工具",
    summary: "管理本地项目、素材、版本与制作费用。",
    next: "项目创建、保存与恢复",
    step: "管理",
  },
];
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
  const [page, setPage] = useState("首页");
  const [runtime, setRuntime] = useState<RuntimeSnapshot | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilitiesData | null>(
    null,
  );
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    if (!window.desktop) {
      setMessage("桌面连接未能载入，请关闭应用并重新打开。");
      return;
    }
    const accept = (s: RuntimeSnapshot) => {
      if (active)
        setRuntime((old) => (!old || s.revision > old.revision ? s : old));
    };
    const unsubscribe = window.desktop.onRuntimeStateChanged(accept);
    void window.desktop.getRuntimeState().then((r) => {
      if (!active) return;
      if (r.ok) accept(r.data);
      else setMessage(r.error.message);
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);
  useEffect(() => {
    let active = true;
    setCapabilities(null);
    if (runtime?.state === "ready")
      void window.desktop.getCapabilities().then((result) => {
        if (
          active &&
          result.ok &&
          result.data.runtimeId === runtime.runtimeId &&
          result.data.generation === runtime.generation
        )
          setCapabilities(result.data);
        else if (active && !result.ok) setMessage(result.error.message);
      });
    return () => {
      active = false;
    };
  }, [runtime?.state, runtime?.runtimeId, runtime?.generation]);
  async function restart() {
    if (!runtime?.canRestart || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await window.desktop.restartBackend({
        expectedGeneration: runtime.generation,
      });
      if (!result.ok) setMessage(result.error.message);
    } finally {
      setBusy(false);
    }
  }
  const current = pages.find((p) => p.name === page);
  const state = runtime?.state ?? "starting";
  const help = async () => {
    const result = await window.desktop.openHelpLink({
      helpId: "runtime-help",
    });
    if (!result.ok) setMessage(result.error.message);
  };
  return (
    <div className="workspace">
      <a className="skip-link" href="#main">
        跳到主内容
      </a>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ▰
          </span>
          <div>
            AI 短剧工作台<small>本地创作空间</small>
          </div>
        </div>
        <nav aria-label="主导航">
          <button
            className={page === "首页" ? "nav-item selected" : "nav-item"}
            aria-current={page === "首页" ? "page" : undefined}
            onClick={() => setPage("首页")}
          >
            首页
          </button>
          <p className="nav-label">创作流程</p>
          {pages.map((p) => (
            <button
              key={p.name}
              className={page === p.name ? "nav-item selected" : "nav-item"}
              aria-current={page === p.name ? "page" : undefined}
              onClick={() => setPage(p.name)}
            >
              {p.name}
              <span className="nav-dot" aria-hidden="true" />
            </button>
          ))}
          <button
            className={
              page === "设置"
                ? "nav-item settings selected"
                : "nav-item settings"
            }
            aria-current={page === "设置" ? "page" : undefined}
            onClick={() => setPage("设置")}
          >
            设置
          </button>
        </nav>
        <div className="sidebar-foot">
          文件留在本机
          <br />
          <span>生成时使用你配置的服务</span>
        </div>
      </aside>
      <div className="content">
        <header className="topbar">
          <span>{page}</span>
          <span className={`connection ${state}`}>
            <i aria-hidden="true" />
            {statusText[state]}
          </span>
        </header>
        <main id="main" tabIndex={-1}>
          <section
            className={`runtime-panel ${state}`}
            aria-label="本地服务状态"
            aria-live="polite"
          >
            <div>
              <h2 data-testid="runtime-status">{statusText[state]}</h2>
              <p>
                {runtime?.errorCode
                  ? safeError(runtime.errorCode).message
                  : state === "ready"
                    ? "桌面连接已就绪。创作功能将随后续版本开放。"
                    : state === "stopping"
                      ? "正在等待服务和所属进程退出，请稍候。"
                      : "启动期间可以浏览各个工作区。"}
              </p>
            </div>
            <button
              onClick={() => void restart()}
              disabled={!runtime?.canRestart || busy}
            >
              {busy || state === "stopping" ? "请稍候" : "重启本地服务"}
            </button>
          </section>
          {message && (
            <p className="notice" role="alert">
              {message}
            </p>
          )}
          {page === "首页" ? (
            <>
              <div className="intro">
                <span className="edition">创作工作台预览版</span>
                <h1>把故事，一镜一镜做出来。</h1>
                <p>
                  从故事到成片，每一步都可以查看、修改，再决定采用。
                  <br />
                  当前版本已提供本地服务连接，项目与生成功能尚未开放。
                </p>
              </div>
              <section className="workflow" aria-labelledby="workflow-title">
                <div className="section-heading">
                  <h2 id="workflow-title">你的创作路径</h2>
                  <span>按阶段准备，逐镜推进</span>
                </div>
                <ol>
                  {pages.slice(0, 5).map((p, i) => (
                    <li key={p.name}>
                      <span className="step-index">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <div>
                        <button
                          className="step-button"
                          onClick={() => setPage(p.name)}
                        >
                          {p.name}
                        </button>
                        <p>{p.summary}</p>
                      </div>
                      <span className="availability">尚未开放</span>
                    </li>
                  ))}
                </ol>
              </section>
              <div className="project-note">
                <h2>下一步，从保存第一个项目开始</h2>
                <p>
                  项目管理开放后，你可以创建本地项目、导入素材，并在关闭后继续创作。
                </p>
                <button
                  className="text-button"
                  onClick={() => setPage("项目工具")}
                >
                  查看项目工具
                </button>
              </div>
            </>
          ) : page === "设置" ? (
            <>
              <div className="intro">
                <h1>设置</h1>
                <p>查看当前连接信息，处理本地服务问题。</p>
              </div>
              <section className="settings-panel">
                <h2>运行信息</h2>
                <dl>
                  <dt>应用版本</dt>
                  <dd>{runtime?.frontendVersion ?? "正在读取"}</dd>
                  <dt>本地服务版本</dt>
                  <dd>{runtime?.backendVersion ?? "尚未验证"}</dd>
                  <dt>连接状态</dt>
                  <dd>{statusText[state]}</dd>
                  <dt>可用功能</dt>
                  <dd>{capabilities ? "本地服务连接" : "等待服务验证"}</dd>
                </dl>
              </section>
              <section className="settings-panel">
                <h2>模型与密钥</h2>
                <p>
                  尚未开放。后续可配置自己的服务商和密钥；当前版本不会发起模型调用或产生生成费用。
                </p>
              </section>
              <details className="settings-panel">
                <summary>连接问题与帮助</summary>
                <p>
                  连接中断时，应用会观察当前服务是否恢复。认证失效时请点击“重启本地服务”。版本不匹配需重新安装同一版本；无法确认退出时请关闭应用后重新打开。
                </p>
                <button className="text-button" onClick={() => void help()}>
                  后端框架资料（在浏览器中打开）
                </button>
              </details>
            </>
          ) : current ? (
            <>
              <div className="intro">
                <span className="edition">{current.step}</span>
                <h1>{current.name}</h1>
                <p>{current.summary}</p>
              </div>
              <section className="empty-state">
                <div className="empty-frame" aria-hidden="true">
                  <span />
                </div>
                <h2>这个工作区尚未开放</h2>
                <p>
                  后续将提供{current.next}。<br />
                  当前可以浏览创作流程，或在设置中检查本地服务。
                </p>
                <button onClick={() => setPage("首页")}>返回首页</button>
              </section>
            </>
          ) : null}
        </main>
        <footer>
          当前版本仅开放本地服务连接<span>不发起生成，不产生模型费用</span>
        </footer>
      </div>
    </div>
  );
}
