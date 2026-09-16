import type {
  Draft,
  DraftsBridge,
  SaveDraft,
} from "../../electron/shared/drafts";
import { projectError } from "../../electron/shared/projects";

type Content = Draft["content"]["content"];
export interface DraftSaveState {
  content: Content;
  status: "saved" | "dirty" | "saving" | "unknown" | "error" | "conflict";
  savedAt: string | null;
  message: string;
  remote: Content | null;
}
export class DraftAutosave {
  snapshot: DraftSaveState;
  private sequence = 0;
  private committed = 0;
  private pending: { input: SaveDraft; sequence: number } | null = null;
  private running: Promise<boolean> | null = null;
  private timer?: ReturnType<typeof setTimeout>;
  private listeners = new Set<() => void>();
  private disposed = false;
  private paused = false;
  private conflictRevision: number | null = null;
  constructor(
    private bridge: DraftsBridge,
    private projectId: string,
    private draft: Draft,
    private revision: number,
    savedAt: string | null,
  ) {
    this.snapshot = {
      content: structuredClone(draft.content.content),
      status: "saved",
      savedAt,
      message: "",
      remote: null,
    };
  }
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private update(change: Partial<DraftSaveState>) {
    this.snapshot = { ...this.snapshot, ...change };
    for (const listener of this.listeners) listener();
  }
  edit(content: Content) {
    this.sequence++;
    this.update({
      content: structuredClone(content),
      status:
        this.snapshot.status === "conflict"
          ? "conflict"
          : this.pending
            ? "unknown"
            : "dirty",
      message: "",
    });
    clearTimeout(this.timer);
    if (!this.paused && this.snapshot.status !== "conflict")
      this.timer = setTimeout(() => {
        void this.flush();
      }, 800);
  }
  setPaused(paused: boolean) {
    this.paused = paused;
    if (paused) clearTimeout(this.timer);
  }
  advanceProjectRevision(
    expectedRevision: number,
    committedRevision: number,
  ): boolean {
    if (
      this.disposed ||
      this.running ||
      this.pending ||
      this.snapshot.status !== "saved" ||
      this.sequence !== this.committed ||
      this.conflictRevision !== null ||
      this.revision !== expectedRevision ||
      committedRevision !== expectedRevision + 1
    )
      return false;
    this.revision = committedRevision;
    return true;
  }
  flush(): Promise<boolean> {
    clearTimeout(this.timer);
    if (this.running) return this.running;
    if (this.snapshot.status === "conflict") return Promise.resolve(false);
    if (this.sequence === this.committed && !this.pending)
      return Promise.resolve(true);
    if (this.paused || this.disposed) return Promise.resolve(false);
    this.running = this.drain().finally(() => {
      this.running = null;
    });
    return this.running;
  }
  private async drain(): Promise<boolean> {
    while (this.sequence !== this.committed || this.pending) {
      if (this.paused || this.disposed) return false;
      const querying = !!this.pending;
      if (!this.pending) {
        const content = structuredClone(this.snapshot.content);
        if (
          (typeof content.sourceText === "string" &&
            Array.from(content.sourceText).length > 100000) ||
          (typeof content.brief === "string" &&
            Array.from(content.brief).length > 10000)
        ) {
          this.update({
            status: "error",
            message:
              "原文最多 100,000 字符，简报最多 10,000 字符。输入已完整保留，请调整后保存。",
          });
          return false;
        }
        // The backend hashes the exact current text, including empty strings/newlines.
        if (this.draft.content.kind === "story") delete content.sourceHash;
        this.pending = {
          sequence: this.sequence,
          input: {
            projectId: this.projectId,
            command: {
              clientOperationId: crypto.randomUUID(),
              expectedRevision: this.revision,
              payload: {
                draftId: this.draft.id,
                artifactId: this.draft.artifactId,
                baseRevisionId: this.draft.baseRevisionId,
                content: { kind: this.draft.content.kind, content },
              },
            },
          },
        };
      }
      const pending = this.pending;
      this.update({ status: "saving", message: "" });
      try {
        let result;
        if (querying) {
          const queried = await this.bridge.operation({
            projectId: this.projectId,
            operationId: pending.input.command.clientOperationId,
          });
          if (queried.ok)
            result = { ok: true as const, data: queried.data.receipt };
          else if (queried.error.code === "OBJECT_NOT_FOUND")
            result = await this.bridge.save(pending.input);
          else result = queried;
        } else result = await this.bridge.save(pending.input);
        if (!result.ok) {
          if (result.error.code === "REVISION_CONFLICT") {
            this.pending = null;
            this.update({
              status: "conflict",
              message: "项目已有新版本。请比较后选择要保留的内容。",
            });
            await this.loadConflict();
          } else if (
            [
              "REQUEST_INVALID",
              "VALIDATION_FAILED",
              "PROJECT_READ_ONLY",
              "OPERATION_ID_REUSED",
            ].includes(result.error.code)
          ) {
            this.pending = null;
            this.update({ status: "error", message: result.error.message });
          } else
            this.update({
              status: "unknown",
              message: "保存结果待核对。输入已保留，恢复连接后请重试。",
            });
          return false;
        }
        if (
          result.data.operationId !== pending.input.command.clientOperationId ||
          result.data.resourceId !== this.draft.id
        ) {
          this.update({
            status: "unknown",
            message: "保存回执不匹配，请重新核对。",
          });
          return false;
        }
        this.revision = result.data.committedRevision;
        this.committed = pending.sequence;
        this.pending = null;
        let savedAt: string | null = null;
        try {
          const project = await this.bridge.project({
            projectId: this.projectId,
          });
          if (project.ok && project.data.revision === this.revision)
            savedAt = project.data.savedAt;
        } catch {
          /* Receipt already proves persistence; a failed clock lookup changes no content. */
        }
        this.update({
          status: this.sequence === this.committed ? "saved" : "dirty",
          savedAt,
          message: "",
        });
      } catch {
        this.update({
          status: "unknown",
          message: projectError("BACKEND_UNAVAILABLE").message,
        });
        return false;
      }
    }
    return true;
  }
  private async loadConflict() {
    try {
      // Read revision first; a concurrent later edit remains protected by the next CAS.
      const project = await this.bridge.project({ projectId: this.projectId });
      const remote = await this.bridge.get({
        projectId: this.projectId,
        draftId: this.draft.id,
      });
      if (
        project.ok &&
        (remote.ok || remote.error.code === "OBJECT_NOT_FOUND")
      ) {
        this.conflictRevision = project.data.revision;
        this.update({
          remote: remote.ok ? remote.data.content.content : {},
          savedAt: project.data.savedAt,
        });
      }
    } catch {
      /* Keep both local input and unresolved conflict. */
    }
  }
  async resolveConflict(choice: "local" | "saved"): Promise<boolean> {
    if (this.snapshot.status !== "conflict") return false;
    if (this.conflictRevision === null) await this.loadConflict();
    if (this.conflictRevision === null || this.snapshot.remote === null)
      return false;
    this.revision = this.conflictRevision;
    this.conflictRevision = null;
    if (choice === "saved") {
      this.committed = this.sequence;
      this.update({
        content: structuredClone(this.snapshot.remote),
        status: "saved",
        remote: null,
        message: "",
      });
      return true;
    }
    this.update({ status: "dirty", remote: null, message: "" });
    return this.flush();
  }
  dispose() {
    this.disposed = true;
    clearTimeout(this.timer);
    this.listeners.clear();
  }
}
