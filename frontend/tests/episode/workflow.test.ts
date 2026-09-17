import { describe, expect, it } from "vitest";

import {
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
});
