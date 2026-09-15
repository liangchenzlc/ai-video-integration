import { contextBridge, ipcRenderer } from "electron";
import { z } from "zod";
import {
  snapshotSchema,
  capabilitySchema,
  bridgeErrorSchema,
  restartSchema,
  helpSchema,
} from "../shared/bridge-schema";
import {
  safeError,
  type BridgeResult,
  type DesktopBridge,
} from "../shared/runtime";

async function invoke<T>(
  channel: string,
  schema: z.ZodType<T>,
  args: unknown[] = [],
): Promise<BridgeResult<T>> {
  try {
    const result: unknown = await ipcRenderer.invoke(channel, ...args);
    const success = z
      .strictObject({ ok: z.literal(true), data: schema })
      .safeParse(result);
    if (success.success) return success.data;
    const failure = bridgeErrorSchema.safeParse(result);
    if (failure.success)
      return { ok: false, error: safeError(failure.data.error.code) };
  } catch {
    /* The bridge never forwards transport errors or Electron objects. */
  }
  return { ok: false, error: safeError("BACKEND_UNAVAILABLE") };
}
const bridge: DesktopBridge = {
  getRuntimeState: () => invoke("runtime:state", snapshotSchema),
  getCapabilities: () => invoke("runtime:capabilities", capabilitySchema),
  restartBackend: (input) => {
    const parsed = restartSchema.safeParse(input);
    return parsed.success
      ? invoke("runtime:restart", snapshotSchema, [parsed.data])
      : Promise.resolve({ ok: false, error: safeError("REQUEST_INVALID") });
  },
  openHelpLink: (input) => {
    const parsed = helpSchema.safeParse(input);
    return parsed.success
      ? invoke("runtime:help", z.strictObject({ opened: z.literal(true) }), [
          parsed.data,
        ])
      : Promise.resolve({ ok: false, error: safeError("REQUEST_INVALID") });
  },
  onRuntimeStateChanged: (listener) => {
    if (typeof listener !== "function") return () => {};
    const handler = (_event: unknown, value: unknown) => {
      const parsed = snapshotSchema.safeParse(value);
      if (parsed.success) listener(parsed.data);
    };
    ipcRenderer.on("runtime:changed", handler);
    return () => {
      ipcRenderer.removeListener("runtime:changed", handler);
    };
  },
};
contextBridge.exposeInMainWorld("desktop", Object.freeze(bridge));
