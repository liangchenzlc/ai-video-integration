// Internal packaging fixture; never used as the product entrypoint.
const { app, BrowserWindow } = require("electron");
const { spawn } = require("node:child_process");
const { writeFileSync } = require("node:fs");
const path = require("node:path");

let child;
let window;
let completed = false;
const reportPath = path.join(
  path.dirname(process.execPath),
  "probe-result.json",
);
const report = { kind: "T01-A desktop packaging probe", passed: false };
app.setPath(
  "userData",
  path.join(path.dirname(process.execPath), "probe-profile"),
);

function finish(error) {
  if (completed) return;
  completed = true;
  clearTimeout(deadline);
  if (child && child.exitCode === null) child.kill();
  report.passed = !error;
  if (error) report.error = String(error.message || error).slice(0, 500);
  writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  app.exit(error ? 1 : 0);
}

const deadline = setTimeout(
  () => finish(new Error("Probe exceeded 20 seconds")),
  20000,
);
app.on("window-all-closed", () => {});
app
  .whenReady()
  .then(async () => {
    report.electron = process.versions.electron;
    report.packaged = app.isPackaged;
    report.resourcesPath = process.resourcesPath;
    if (!app.isPackaged)
      throw new Error("This fixture must run from its directory package");
    window = new BrowserWindow({
      show: false,
      webPreferences: {
        sandbox: true,
        contextIsolation: true,
        nodeIntegration: false,
      },
    });
    await window.loadURL(
      'data:text/html,<meta http-equiv="Content-Security-Policy" content="default-src %27none%27"><p>T01-A packaging probe</p>',
    );
    report.rendererLoaded = true;
    const environment = {};
    for (const [key, value] of Object.entries(process.env)) {
      if (
        [
          "SYSTEMROOT",
          "WINDIR",
          "TEMP",
          "TMP",
          "USERPROFILE",
          "LOCALAPPDATA",
          "APPDATA",
        ].includes(key.toUpperCase())
      ) {
        environment[key] = value;
      }
    }
    const executable = path.join(
      process.resourcesPath,
      "backend",
      "avi_probe.exe",
    );
    child = spawn(executable, ["--role=supervisor"], {
      cwd: path.dirname(executable),
      env: environment,
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    });
    report.spawnedPid = child.pid;
    let pending = Buffer.alloc(0);
    let frames = 0;
    let stderrBytes = 0;
    child.on("error", finish);
    child.stderr.on("data", (data) => {
      stderrBytes += data.length;
      if (stderrBytes > 1024) finish(new Error("Probe stderr exceeded limit"));
    });
    child.stdin.on("error", finish);
    child.stdout.on("data", (data) => {
      try {
        pending = Buffer.concat([pending, data]);
        if (pending.length > 1024)
          throw new Error("Probe stdout exceeded limit");
        let end;
        while ((end = pending.indexOf(10)) >= 0) {
          const frame = JSON.parse(pending.subarray(0, end).toString("utf8"));
          pending = pending.subarray(end + 1);
          frames++;
          if (frames === 1) {
            if (
              frame.supervisorPid !== child.pid ||
              !Number.isInteger(frame.apiPid) ||
              frame.streams !== true
            ) {
              throw new Error(
                "Packaged process identity or standard streams mismatch",
              );
            }
            report.supervisorPid = frame.supervisorPid;
            report.apiPid = frame.apiPid;
            report.streams = frame.streams;
            child.stdin.end("STOP\n");
          } else if (
            frames === 2 &&
            frame.stopped === true &&
            frame.activeJobProcesses === 0
          ) {
            report.stopped = true;
            report.activeJobProcesses = 0;
          } else {
            throw new Error("Unexpected probe frame");
          }
        }
      } catch (error) {
        finish(error);
      }
    });
    child.on("close", (code) => {
      report.backendExitCode = code;
      if (code !== 0 || frames !== 2 || pending.length || !stderrBytes) {
        finish(new Error("Probe did not complete cleanly"));
      } else {
        finish();
      }
    });
  })
  .catch(finish);
