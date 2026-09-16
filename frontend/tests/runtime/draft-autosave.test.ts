import { randomUUID } from "node:crypto";
import { expect, test, vi, afterEach } from "vitest";
import { DraftAutosave } from "../../src/app/draft-autosave";
import { prepareDraftMutation } from "../../src/app/ProjectsHome";
import type {
  Draft,
  DraftsBridge,
  SaveDraft,
} from "../../electron/shared/drafts";

function setup() {
  const draft: Draft = {
    id: randomUUID(),
    artifactId: randomUUID(),
    baseRevisionId: null,
    content: { kind: "story", content: { sourceText: "" } },
  };
  let revision = 0;
  const receipt = (input: SaveDraft) => ({
    operationId: input.command.clientOperationId,
    committedRevision: ++revision,
    resourceId: draft.id,
    state: "committed",
  });
  const save = vi.fn(async (input: SaveDraft) => ({
    ok: true as const,
    data: receipt(input),
  }));
  const operation = vi.fn();
  const bridge = {
    save,
    operation,
    get: vi.fn(async () => ({ ok: true, data: draft })),
    project: vi.fn(async () => ({
      ok: true,
      data: { revision, savedAt: "2026-09-16T01:00:00Z" },
    })),
  } as unknown as DraftsBridge;
  const engine = new DraftAutosave(bridge, randomUUID(), draft, 0, null);
  return {
    engine,
    save,
    operation,
    receipt,
    draft,
    bridge,
    setRevision: (value: number) => {
      revision = value;
    },
  };
}
afterEach(() => vi.useRealTimers());

test("debounces edits and persists a cleared draft", async () => {
  vi.useFakeTimers();
  const { engine, save } = setup();
  engine.edit({ sourceText: "abc" });
  await vi.advanceTimersByTimeAsync(799);
  expect(save).not.toHaveBeenCalled();
  engine.edit({ sourceText: "" });
  await vi.advanceTimersByTimeAsync(800);
  expect(save).toHaveBeenCalledTimes(1);
  expect(save.mock.calls[0][0].command.payload.content.content.sourceText).toBe(
    "",
  );
  expect(engine.snapshot.status).toBe("saved");
  engine.dispose();
});

test("edits during save queue behind its receipt revision", async () => {
  const { engine, save, receipt } = setup();
  let complete!: (value: Awaited<ReturnType<typeof save>>) => void;
  save.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        complete = resolve;
      }),
  );
  engine.edit({ sourceText: "first" });
  const flushing = engine.flush();
  engine.edit({ sourceText: "second" });
  expect(save).toHaveBeenCalledTimes(1);
  complete({ ok: true, data: receipt(save.mock.calls[0][0]) });
  expect(await flushing).toBe(true);
  expect(save).toHaveBeenCalledTimes(2);
  expect(save.mock.calls[1][0].command.expectedRevision).toBe(1);
  expect(save.mock.calls[1][0].command.payload.content.content.sourceText).toBe(
    "second",
  );
  engine.dispose();
});

test("lost response queries the original operation before writing newer text", async () => {
  const { engine, save, operation, receipt } = setup();
  save.mockImplementationOnce(async () => {
    throw new Error("transport lost");
  });
  operation.mockResolvedValue({
    ok: false,
    error: { code: "BACKEND_UNAVAILABLE", message: "offline" },
  });
  engine.edit({ sourceText: "first" });
  expect(await engine.flush()).toBe(false);
  const original = save.mock.calls[0][0];
  engine.edit({ sourceText: "second" });
  expect(await engine.flush()).toBe(false);
  expect(save).toHaveBeenCalledTimes(1);
  expect(operation.mock.calls[0][0].operationId).toBe(
    original.command.clientOperationId,
  );
  operation.mockResolvedValue({
    ok: true,
    data: {
      receipt: receipt(original),
      state: "committed",
      operationId: original.command.clientOperationId,
    },
  });
  expect(await engine.flush()).toBe(true);
  expect(save).toHaveBeenCalledTimes(2);
  expect(save.mock.calls[1][0].command.expectedRevision).toBe(1);
  expect(engine.snapshot.content.sourceText).toBe("second");
  engine.dispose();
});

test("conflict preserves input and requires an explicit choice", async () => {
  const { engine, save } = setup();
  save.mockResolvedValueOnce({
    ok: false,
    error: { code: "REVISION_CONFLICT", message: "conflict" },
  } as never);
  engine.edit({ sourceText: "my version" });
  expect(await engine.flush()).toBe(false);
  expect(engine.snapshot.status).toBe("conflict");
  expect(engine.snapshot.content.sourceText).toBe("my version");
  expect(await engine.flush()).toBe(false);
  expect(save).toHaveBeenCalledTimes(1);
  expect(await engine.resolveConflict("local")).toBe(true);
  expect(save).toHaveBeenCalledTimes(2);
  expect(save.mock.calls[1][0].command.clientOperationId).not.toBe(
    save.mock.calls[0][0].command.clientOperationId,
  );
  engine.dispose();
});

test("a known same-window project receipt advances a clean draft CAS", async () => {
  const { engine, save, setRevision } = setup();
  setRevision(1);
  expect(engine.advanceProjectRevision(0, 1)).toBe(true);
  engine.edit({ sourceText: "next candidate" });
  expect(await engine.flush()).toBe(true);
  expect(save.mock.calls[0][0].command.expectedRevision).toBe(1);
  expect(engine.snapshot.status).toBe("saved");
  engine.dispose();
});

test("a known receipt cannot advance a dirty draft or a mismatched base", () => {
  const { engine } = setup();
  engine.edit({ sourceText: "unsaved" });
  expect(engine.advanceProjectRevision(0, 1)).toBe(false);
  expect(engine.advanceProjectRevision(4, 5)).toBe(false);
  expect(engine.snapshot.status).toBe("dirty");
  engine.dispose();
});

test("project mutations wait for the draft engine while a loaded engine can flush", async () => {
  expect(await prepareDraftMutation(null)).toBe(false);
  const flush = vi.fn(async () => true);
  expect(await prepareDraftMutation({ flush })).toBe(true);
  expect(flush).toHaveBeenCalledOnce();
});
