import { describe, expect, it } from "vitest";

import {
  bindGridCell,
  createGridBatches,
  groupShotIds,
} from "../../src/features/projects/episode-grid";

describe("nine-grid batches", () => {
  it("groups ten stable shot IDs into batches of nine and one", () => {
    expect(
      groupShotIds(Array.from({ length: 10 }, (_, i) => `s${i}`)).map(
        (group) => group.length,
      ),
    ).toEqual([9, 1]);
  });

  it("keeps the tenth shot in its own fixed batch", () => {
    const sheet = { kind: "demo-image" as const, id: "demo-image-sheet" };
    const batches = createGridBatches(
      Array.from({ length: 10 }, (_, index) => `shot-${index + 1}`),
      () => sheet,
    );

    expect(batches).toHaveLength(2);
    expect(batches[1]?.cells.map((cell) => cell.shotId)).toEqual(["shot-10"]);
  });

  it("does not create duplicate cells when input repeats a shot ID", () => {
    expect(groupShotIds(["shot-a", "shot-b", "shot-a"])).toEqual([
      ["shot-a", "shot-b"],
    ]);
  });

  it("captures stable shot identity at generation time despite later reordering", () => {
    const batches = createGridBatches(["shot-a", "shot-b"], (index) => ({
      kind: "demo-image",
      id: `demo-image-sheet-${index}`,
    }));

    expect(
      ["shot-b", "shot-a"].map(() => batches[0]?.cells[0]?.shotId),
    ).toEqual(["shot-a", "shot-a"]);
    expect(batches[0]?.cells.map((cell) => cell.index)).toEqual([0, 1]);
  });

  it("retains the original cell label when the shot list is reordered", () => {
    const batches = createGridBatches(["shot-a", "shot-b", "shot-c"], () => ({
      kind: "demo-image",
      id: "demo-image-sheet-1",
    }));
    const reorderedShotIds = ["shot-c", "shot-a", "shot-b"];

    expect(reorderedShotIds).toEqual(["shot-c", "shot-a", "shot-b"]);
    expect(batches[0]?.cells.map((cell) => cell.shotId)).toEqual([
      "shot-a",
      "shot-b",
      "shot-c",
    ]);
  });

  it("does not bind a grid cell to a shot outside its batch", () => {
    const batch = createGridBatches(["shot-a"], () => ({
      kind: "demo-image",
      id: "demo-image-sheet-1",
    }))[0]!;
    const ref = { kind: "demo-image" as const, id: "demo-image-cell-1" };

    expect(bindGridCell(batch, 0, "not-in-batch", ref)).toEqual(batch);
  });

  it.each([0, 9, 10])(
    "keeps every grid batch within the zero-to-nine boundary for %i shots",
    (count) => {
      const batches = createGridBatches(
        Array.from({ length: count }, (_, index) => `s${index}`),
        (index) => ({ kind: "demo-image", id: `demo-image-sheet-${index}` }),
      );

      expect(
        batches.flatMap((batch) => batch.cells).map((cell) => cell.shotId),
      ).toEqual(Array.from({ length: count }, (_, index) => `s${index}`));
      expect(batches.every((batch) => batch.cells.length <= 9)).toBe(true);
    },
  );
});
