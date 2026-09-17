import { ipcRenderer } from "electron";
import { z } from "zod";

const requestSchema = z.strictObject({ requestId: z.uuid() });

export function createBeforeLeaveBridge() {
  const listeners = new Map<() => Promise<boolean>, (() => void) | undefined>();
  let activeRequest: string | null = null;
  let subscribed = false;
  let disposed = false;
  const handler = (_event: unknown, value: unknown) => {
    const parsed = requestSchema.safeParse(value);
    if (!parsed.success || disposed) return;
    activeRequest = parsed.data.requestId;
    void (async () => {
      let saved = !subscribed;
      try {
        if (listeners.size) {
          const results = await Promise.all(
            [...listeners.keys()].map((listener) => listener()),
          );
          saved = results.every((result) => result === true);
        }
      } catch {
        saved = false;
      }
      if (!disposed && activeRequest === parsed.data.requestId)
        ipcRenderer.send("draft:flush-result", {
          requestId: parsed.data.requestId,
          saved,
        });
    })();
  };
  const resume = (_event: unknown, value: unknown) => {
    const parsed = requestSchema.safeParse(value);
    if (!parsed.success || disposed || parsed.data.requestId !== activeRequest)
      return;
    activeRequest = null;
    for (const callback of listeners.values()) {
      try {
        callback?.();
      } catch {
        /* One subscriber cannot prevent others resuming. */
      }
    }
  };
  ipcRenderer.on("draft:flush-request", handler);
  ipcRenderer.on("draft:resume", resume);
  return {
    onBeforeLeave(
      listener: () => Promise<boolean>,
      onResume?: () => void,
    ): () => void {
      if (typeof listener !== "function" || disposed) return () => {};
      subscribed = true;
      listeners.set(
        listener,
        typeof onResume === "function" ? onResume : undefined,
      );
      return () => {
        listeners.delete(listener);
      };
    },
    dispose() {
      disposed = true;
      listeners.clear();
      ipcRenderer.removeListener("draft:flush-request", handler);
      ipcRenderer.removeListener("draft:resume", resume);
    },
  };
}
