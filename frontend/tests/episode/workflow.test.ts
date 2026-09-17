import { describe, expect, it } from "vitest";

import {
  emptyWorkflow,
  readWorkflow,
  saveWorkflow,
} from "../../src/features/projects/episode-workflow";

class MemoryStorage {
  readonly values = new Map<string, string>();

  getItem(key: string) {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
}

describe("episode workflow persistence", () => {
  it("migrates a legacy draft without changing its stored value", () => {
    const storage = new MemoryStorage();
    const legacyKey = "avi-episode-draft-p-e";
    const legacyDraft = {
      script: "旧剧本",
      shots: [{ id: "shot-1", title: "街口", description: "街口" }],
      characters: "阿遥",
      props: "雨伞",
      scenes: "雨夜街口",
      imagePrompt: "雨夜",
      videoPrompt: "镜头缓慢推进",
    };
    storage.setItem(legacyKey, JSON.stringify(legacyDraft));

    expect(
      readWorkflow("p", "e", { aspect: "16:9", style: "写实" }, storage),
    ).toMatchObject({
      version: 2,
      scriptDraft: "旧剧本",
      shots: [{ id: "shot-1", description: "街口" }],
      legacyNotes: { characters: "阿遥", imagePrompt: "雨夜" },
    });
    expect(storage.getItem(legacyKey)).toBe(JSON.stringify(legacyDraft));
  });

  it("reports a save failure when local storage is full", () => {
    const storage = new MemoryStorage();
    const state = readWorkflow(
      "p",
      "e",
      { aspect: "16:9", style: "写实" },
      storage,
    );
    const throwingStorage = {
      setItem() {
        throw new DOMException("quota exceeded", "QuotaExceededError");
      },
    };

    expect(saveWorkflow("p", "e", state, throwingStorage)).toEqual({
      ok: false,
      error: "本集内容未能保存，请检查本地空间。",
    });
  });

  it("rejects a persisted grid batch with more than nine cells", () => {
    const storage = new MemoryStorage();
    const state = emptyWorkflow({ aspect: "16:9", style: "写实" });
    state.scriptDraft = "不应采用的 V2 内容";
    state.gridBatches = [
      {
        id: "grid-1",
        sheet: { kind: "demo-image", id: "demo-image-sheet-1" },
        cells: Array.from({ length: 10 }, (_, index) => ({
          index,
          shotId: `shot-${index}`,
          ref: { kind: "demo-image" as const, id: `demo-image-${index}` },
          review: "review" as const,
        })),
      },
    ];
    storage.setItem("avi-episode-workflow-v2-p-e", JSON.stringify(state));

    expect(readWorkflow("p", "e", { aspect: "16:9", style: "写实" }, storage).scriptDraft).toBe("");
  });

  it("rejects a persisted grid batch that binds a shot more than once", () => {
    const storage = new MemoryStorage();
    const state = emptyWorkflow({ aspect: "16:9", style: "写实" });
    state.scriptDraft = "不应采用的 V2 内容";
    state.gridBatches = [
      {
        id: "grid-1",
        sheet: { kind: "demo-image", id: "demo-image-sheet-1" },
        cells: [
          { index: 0, shotId: "shot-1", ref: null, review: "review" },
          { index: 1, shotId: "shot-1", ref: null, review: "review" },
        ],
      },
    ];
    storage.setItem("avi-episode-workflow-v2-p-e", JSON.stringify(state));

    expect(readWorkflow("p", "e", { aspect: "16:9", style: "写实" }, storage).scriptDraft).toBe("");
  });

  it.each([
    "data:image/png;base64,not-media-id",
    "C:\\Users\\snow\\image.png",
    "sk-secret-token",
  ])("rejects persisted media refs that contain unsafe value %s", (id) => {
    const storage = new MemoryStorage();
    const state = emptyWorkflow({ aspect: "16:9", style: "写实" });
    state.scriptDraft = "不应采用的 V2 内容";
    state.assets = [
      {
        id: "asset-1",
        kind: "character",
        name: "阿遥",
        description: "雨夜的旅人",
        linkedResourceId: null,
        imageCandidates: [
          { id: "candidate-1", source: "import", value: { kind: "project-image", id } },
        ],
        selectedImageId: null,
        review: "review",
      },
    ];
    storage.setItem("avi-episode-workflow-v2-p-e", JSON.stringify(state));

    expect(readWorkflow("p", "e", { aspect: "16:9", style: "写实" }, storage).scriptDraft).toBe("");
  });

  it("refuses to save a workflow containing an unsafe media reference", () => {
    const storage = new MemoryStorage();
    const state = emptyWorkflow({ aspect: "16:9", style: "写实" });
    state.assets = [
      {
        id: "asset-1",
        kind: "character",
        name: "阿遥",
        description: "雨夜的旅人",
        linkedResourceId: null,
        imageCandidates: [
          {
            id: "candidate-1",
            source: "import",
            value: { kind: "project-image", id: "data:image/png;base64,binary" },
          },
        ],
        selectedImageId: null,
        review: "review",
      },
    ];

    expect(saveWorkflow("p", "e", state, storage)).toMatchObject({ ok: false });
    expect(storage.values).toHaveLength(0);
  });

  it("refuses to save a workflow with an oversized grid batch", () => {
    const storage = new MemoryStorage();
    const state = emptyWorkflow({ aspect: "16:9", style: "写实" });
    state.gridBatches = [
      {
        id: "grid-1",
        sheet: { kind: "demo-image", id: "demo-image-sheet-1" },
        cells: Array.from({ length: 10 }, (_, index) => ({
          index,
          shotId: `shot-${index}`,
          ref: null,
          review: "review" as const,
        })),
      },
    ];

    expect(saveWorkflow("p", "e", state, storage)).toMatchObject({ ok: false });
    expect(storage.values).toHaveLength(0);
  });
});
