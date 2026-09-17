import { app, BrowserWindow, protocol, session } from "electron";
import { readFile, readdir } from "node:fs/promises";
import { join, resolve, extname } from "node:path";
import { RuntimeSupervisor } from "./runtime/supervisor";
import { launchBackend } from "./runtime/launch";
import { installIpc } from "./ipc";
import { allowedPage, productionCsp, developmentCsp } from "./security";
import { confirmRendererLeave, createQuitGuard } from "./draft-flush";

protocol.registerSchemesAsPrivileged([
  {
    scheme: "app",
    privileges: { standard: true, secure: true, supportFetchAPI: true },
  },
  {
    scheme: "avi-media",
    privileges: { standard: true, secure: true, stream: true },
  },
]);
app.setName("AI Video Integration");
const development =
  !app.isPackaged &&
  process.env.ELECTRON_RENDERER_URL === "http://127.0.0.1:5173";
const offscreenForTests = process.env.AVI_E2E_OFFSCREEN_WINDOW === "1";
const root = resolve(__dirname, "../../..");
let window: BrowserWindow | undefined;
let supervisor: RuntimeSupervisor | undefined;
const quitGuard = createQuitGuard({
  confirm: () =>
    window ? confirmRendererLeave(window, development) : Promise.resolve(true),
  stop: () => supervisor?.stop("app_exit") ?? Promise.resolve(),
  quit: () => app.quit(),
});

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", () => {
    if (window) {
      if (window.isMinimized()) window.restore();
      if (!offscreenForTests) {
        window.show();
        window.focus();
      }
    }
  });
  app.on("before-quit", quitGuard.beforeQuit);
  app.on("window-all-closed", () => app.quit());
  void app
    .whenReady()
    .then(async () => {
      const rendererRoot = join(__dirname, "../renderer");
      const resources = new Map<string, string>();
      async function collect(directory: string, prefix: string) {
        for (const entry of await readdir(directory, { withFileTypes: true })) {
          if (entry.isDirectory())
            await collect(
              join(directory, entry.name),
              prefix + entry.name + "/",
            );
          else if (entry.isFile())
            resources.set(prefix + entry.name, join(directory, entry.name));
        }
      }
      if (!development) {
        await collect(rendererRoot, "/");
        resources.set("/", join(rendererRoot, "index.html"));
        protocol.handle("app", async (request) => {
          const url = new URL(request.url);
          const file = resources.get(url.pathname);
          if (
            url.host !== "ui" ||
            url.username ||
            url.password ||
            url.search ||
            request.method !== "GET" ||
            !file
          )
            return new Response(null, { status: 404 });
          const mime: Record<string, string> = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
          };
          try {
            return new Response(await readFile(file), {
              headers: {
                "Content-Type":
                  mime[extname(file)] ?? "application/octet-stream",
                "Content-Security-Policy": productionCsp,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
              },
            });
          } catch {
            return new Response(null, { status: 404 });
          }
        });
      }
      const activeSession = session.defaultSession;
      activeSession.setPermissionRequestHandler((_wc, _permission, callback) =>
        callback(false),
      );
      activeSession.setPermissionCheckHandler(() => false);
      activeSession.on("will-download", (event) => event.preventDefault());
      activeSession.webRequest.onBeforeRequest((details, callback) => {
        const url = new URL(details.url);
        callback({
          cancel:
            !(url.protocol === "app:" && url.host === "ui") &&
            !(url.protocol === "avi-media:" && url.host === "local") &&
            !(
              development &&
              ["http:", "ws:"].includes(url.protocol) &&
              url.host === "127.0.0.1:5173"
            ),
        });
      });
      if (development)
        activeSession.webRequest.onHeadersReceived((details, callback) =>
          callback({
            responseHeaders: {
              ...details.responseHeaders,
              "Content-Security-Policy": [developmentCsp],
            },
          }),
        );
      window = new BrowserWindow({
        ...(offscreenForTests ? { x: -32000, y: -32000 } : {}),
        width: 1280,
        height: 800,
        minWidth: 960,
        minHeight: 640,
        show: false,
        backgroundColor: "#f5f9fe",
        title: "AI 短剧工作台",
        autoHideMenuBar: true,
        webPreferences: {
          preload: join(__dirname, "../preload/index.js"),
          sandbox: true,
          contextIsolation: true,
          nodeIntegration: false,
          webSecurity: true,
          webviewTag: false,
        },
      });
      window.removeMenu();
      window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
      window.webContents.on("will-navigate", (event, url) => {
        if (!allowedPage(url, development)) event.preventDefault();
      });
      window.webContents.on("will-redirect", (event) => event.preventDefault());
      window.webContents.on("will-attach-webview", (event) =>
        event.preventDefault(),
      );
      window.on("close", quitGuard.beforeClose);
      supervisor = new RuntimeSupervisor({
        launch: () =>
          launchBackend(root, process.resourcesPath, app.isPackaged),
        appDataDir: app.getPath("userData"),
        version: app.getVersion(),
        mode: app.isPackaged ? "production" : "development",
      });
      const dispose = installIpc(window, supervisor, development);
      window.on("closed", () => {
        dispose();
        window = undefined;
      });
      await window.loadURL(
        development ? "http://127.0.0.1:5173/" : "app://ui/",
      );
      if (offscreenForTests) window.showInactive();
      else window.show();
      await supervisor.start();
    })
    .catch(() => {
      process.stderr.write("DESKTOP_START_FAILED\n");
      app.quit();
    });
}
