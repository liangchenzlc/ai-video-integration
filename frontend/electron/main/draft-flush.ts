import {
  dialog,
  ipcMain,
  type BrowserWindow,
  type IpcMainEvent,
} from "electron";
import { randomUUID } from "node:crypto";
import { z } from "zod";
import { isTrustedSender } from "./security";

const resultSchema = z.strictObject({
  requestId: z.uuid(),
  saved: z.boolean(),
});
const pending = new WeakMap<BrowserWindow, Promise<boolean>>();
const editLocks = new WeakMap<
  BrowserWindow,
  { owners: number; requestId: string }
>();

export function resumeRendererEditing(window: BrowserWindow): void {
  const lock = editLocks.get(window);
  if (!lock || --lock.owners > 0) return;
  editLocks.delete(window);
  if (!window.isDestroyed() && !window.webContents.isDestroyed()) {
    try {
      window.webContents.send("draft:resume", { requestId: lock.requestId });
    } catch {
      /* A destroyed renderer cannot accept a resume notification. */
    }
  }
}

export function requestRendererFlush(
  window: BrowserWindow,
  development: boolean,
): Promise<boolean> {
  const current = pending.get(window);
  if (current) {
    editLocks.get(window)!.owners++;
    return current;
  }
  if (window.isDestroyed() || window.webContents.isDestroyed())
    return Promise.resolve(false);
  const requestId = randomUUID();
  editLocks.set(window, {
    owners: (editLocks.get(window)?.owners ?? 0) + 1,
    requestId,
  });
  let finish!: (saved: boolean) => void;
  const promise = new Promise<boolean>((resolve) => {
    const timer = setTimeout(() => finish(false), 45_000);
    const closed = () => finish(false);
    const response = (event: IpcMainEvent, value: unknown) => {
      if (
        window.isDestroyed() ||
        !isTrustedSender(
          event.sender.id,
          window.webContents.id,
          event.senderFrame === window.webContents.mainFrame,
          event.senderFrame?.url ?? "",
          development,
        )
      )
        return;
      const parsed = resultSchema.safeParse(value);
      if (parsed.success && parsed.data.requestId === requestId)
        finish(parsed.data.saved);
    };
    finish = (saved) => {
      clearTimeout(timer);
      ipcMain.removeListener("draft:flush-result", response);
      window.removeListener("closed", closed);
      pending.delete(window);
      resolve(saved);
    };
    ipcMain.on("draft:flush-result", response);
    window.once("closed", closed);
  });
  pending.set(window, promise);
  try {
    window.webContents.send("draft:flush-request", { requestId });
  } catch {
    finish(false);
  }
  return promise;
}

export async function confirmRendererLeave(
  window: BrowserWindow,
  development: boolean,
): Promise<boolean> {
  let leaving = false;
  try {
    if (await requestRendererFlush(window, development)) {
      leaving = true;
      return true;
    }
    if (window.isDestroyed()) return false;
    const decision = await dialog.showMessageBox(window, {
      type: "warning",
      title: "修改尚未保存",
      message: "无法确认所有修改已保存。",
      detail: "可以继续编辑并重试保存，或放弃未保存的修改后退出。",
      buttons: ["继续编辑", "放弃未保存的修改"],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    });
    leaving = decision.response === 1;
    return leaving;
  } finally {
    if (!leaving) resumeRendererEditing(window);
  }
}

export function createQuitGuard(actions: {
  confirm: () => Promise<boolean>;
  stop: () => Promise<void>;
  quit: () => void;
}) {
  let state: "idle" | "deciding" | "stopping" | "permitted" = "idle";
  return {
    beforeQuit(event: { preventDefault(): void }) {
      if (state === "permitted") return;
      event.preventDefault();
      if (state !== "idle") return;
      state = "deciding";
      void (async () => {
        try {
          if (!(await actions.confirm())) {
            state = "idle";
            return;
          }
        } catch {
          state = "idle";
          return;
        }
        state = "stopping";
        try {
          await actions.stop();
        } catch {
          // The supervisor retains ownership of its bounded graceful stop.
        }
        state = "permitted";
        actions.quit();
      })();
    },
    beforeClose(event: { preventDefault(): void }) {
      if (state === "permitted") return;
      event.preventDefault();
      if (state === "idle") actions.quit();
    },
  };
}
