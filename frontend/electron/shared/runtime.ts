import type { components } from "../../src/api/runtime-types";

export type CapabilitiesData = components["schemas"]["CapabilitiesData"];
export type HealthData = components["schemas"]["HealthData"];
export type RecoveryAction = components["schemas"]["RecoveryAction"];
export interface RuntimeSnapshot {
  state:
    | "stopped"
    | "starting"
    | "ready"
    | "disconnected"
    | "stopping"
    | "failed"
    | "incompatible";
  runtimeId: string | null;
  generation: number;
  revision: number;
  frontendVersion: string;
  backendVersion: string | null;
  errorCode: string | null;
  recoverableAction: RecoveryAction;
  canRestart: boolean;
}
export interface SafeError {
  code: string;
  message: string;
  recoverableAction: RecoveryAction;
}
export type BridgeResult<T> =
  { ok: true; data: T } | { ok: false; error: SafeError };
export interface DesktopBridge {
  getRuntimeState(): Promise<BridgeResult<RuntimeSnapshot>>;
  getCapabilities(): Promise<BridgeResult<CapabilitiesData>>;
  restartBackend(input: {
    expectedGeneration: number;
  }): Promise<BridgeResult<RuntimeSnapshot>>;
  openHelpLink(input: {
    helpId: "runtime-help";
  }): Promise<BridgeResult<{ opened: true }>>;
  onRuntimeStateChanged(
    listener: (snapshot: RuntimeSnapshot) => void,
  ): () => void;
}
const messages: Record<string, string> = {
  SPAWN_FAILED: "本地服务无法启动，请检查安装文件和访问权限。",
  START_TIMEOUT: "本地服务启动超时，可以尝试重启。",
  STOP_TIMEOUT: "未能确认服务已完全关闭，请退出应用后重新打开。",
  VERSION_MISMATCH: "应用与本地服务版本不匹配，请重新安装同一版本。",
  PROTOCOL_INVALID: "本地服务返回了无法识别的数据，请重启或修复安装。",
  BACKEND_ALREADY_RUNNING: "已有本地服务正在运行，请关闭另一实例后重试。",
  AUTH_INVALID: "本地服务连接认证失效，请重启服务。",
  AUTH_REQUIRED: "本地服务连接认证失效，请重启服务。",
  BACKEND_NOT_READY: "本地服务暂未就绪。",
  BACKEND_UNAVAILABLE: "本地服务连接中断，请检查状态或重启服务。",
  API_EXITED: "本地服务意外退出，可以尝试重启。",
  STALE_RUNTIME: "服务状态已更新，请根据当前状态重试。",
  RUNTIME_BUSY: "服务正在启动或关闭，请稍候。",
  SOURCE_REJECTED: "无法执行来自此页面的请求。",
  REQUEST_INVALID: "请求参数无效。",
};
export function safeError(code: string): SafeError {
  return {
    code: Object.hasOwn(messages, code) ? code : "BACKEND_UNAVAILABLE",
    message: messages[code] ?? messages.BACKEND_UNAVAILABLE,
    recoverableAction:
      code === "VERSION_MISMATCH"
        ? "repair_installation"
        : [
              "STOP_TIMEOUT",
              "SOURCE_REJECTED",
              "REQUEST_INVALID",
              "RUNTIME_BUSY",
              "STALE_RUNTIME",
            ].includes(code)
          ? "none"
          : "restart_backend",
  };
}
export class RuntimeError extends Error {
  constructor(readonly code: string) {
    super(safeError(code).message);
  }
}
