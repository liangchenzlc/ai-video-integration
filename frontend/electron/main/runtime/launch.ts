import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { readFileSync } from "node:fs";
import { join, resolve, relative, isAbsolute } from "node:path";

export function launchBackend(
  root: string,
  resources: string,
  packaged: boolean,
): ChildProcessWithoutNullStreams {
  const env: NodeJS.ProcessEnv = {};
  for (const key of [
    "SystemRoot",
    "WINDIR",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
  ]) {
    if (process.env[key]) env[key] = process.env[key];
  }
  env.PYTHONUTF8 = "1";
  let executable = join(resources, "backend", "avi_backend.exe");
  let args = ["--role=supervisor"];
  let cwd = join(resources, "backend");
  if (!packaged) {
    const config = readFileSync(join(root, "backend/.venv/pyvenv.cfg"), "utf8");
    const home = /^home = (.+)$/m.exec(config)?.[1].trim();
    if (!home) throw new Error("Missing project interpreter");
    executable = resolve(home, "python.exe");
    const inside = relative(join(root, ".tools/python"), executable);
    if (inside.startsWith("..") || isAbsolute(inside))
      throw new Error("Invalid project interpreter");
    env.__PYVENV_LAUNCHER__ = join(root, "backend/.venv/Scripts/python.exe");
    cwd = join(root, "backend");
    args = ["-u", "-X", "utf8", "-m", "app.entrypoint", "--role=supervisor"];
  }
  return spawn(executable, args, {
    cwd,
    env,
    windowsHide: true,
    shell: false,
    stdio: "pipe",
  });
}
