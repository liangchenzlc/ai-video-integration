import { ipcMain, shell, type BrowserWindow } from "electron";
import type { RuntimeSupervisor } from "./runtime/supervisor";
import { RuntimeError, safeError } from "../shared/runtime";
import { restartSchema, helpSchema } from "../shared/bridge-schema";
import { isTrustedSender } from "./security";

export function installIpc(
  window: BrowserWindow,
  supervisor: RuntimeSupervisor,
  development: boolean,
): () => void {
  const commands = [
    "runtime:state",
    "runtime:capabilities",
    "runtime:restart",
    "runtime:help",
  ];
  for (const command of commands)
    ipcMain.handle(command, async (event, ...args: unknown[]) => {
      try {
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
          throw new RuntimeError("SOURCE_REJECTED");
        if (
          (command === "runtime:state" || command === "runtime:capabilities") &&
          args.length
        )
          throw new RuntimeError("REQUEST_INVALID");
        let data: unknown;
        if (command === "runtime:state") data = supervisor.snapshot();
        else if (command === "runtime:capabilities")
          data = await supervisor.getCapabilities();
        else if (command === "runtime:restart") {
          const parsed = restartSchema.safeParse(args[0]);
          if (args.length !== 1 || !parsed.success)
            throw new RuntimeError("REQUEST_INVALID");
          data = await supervisor.restart(parsed.data.expectedGeneration);
        } else {
          if (args.length !== 1 || !helpSchema.safeParse(args[0]).success)
            throw new RuntimeError("REQUEST_INVALID");
          await shell.openExternal("https://fastapi.tiangolo.com/");
          data = { opened: true };
        }
        return { ok: true, data };
      } catch (error) {
        return {
          ok: false,
          error: safeError(
            error instanceof RuntimeError ? error.code : "BACKEND_UNAVAILABLE",
          ),
        };
      }
    });
  const unsubscribe = supervisor.subscribe((snapshot) => {
    if (
      !window.isDestroyed() &&
      isTrustedSender(
        window.webContents.id,
        window.webContents.id,
        true,
        window.webContents.getURL(),
        development,
      )
    )
      window.webContents.send("runtime:changed", snapshot);
  });
  return () => {
    unsubscribe();
    for (const command of commands) ipcMain.removeHandler(command);
  };
}
