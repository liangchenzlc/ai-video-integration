import { afterEach, describe, expect, it, vi } from "vitest";
import {
  importProjectMedia,
  listUsableMediaResult,
  mediaUrl,
  hasAvailableMedia,
  listUsableMedia,
} from "../../src/features/projects/episode-media";

const projectId = "11111111-1111-4111-8111-111111111111";
const mediaId = "22222222-2222-4222-8222-222222222222";

afterEach(() => vi.unstubAllGlobals());

describe("episode media", () => {
  it("finds available imported images and MP4s beyond the first 200 media entries", async () => {
    const imageId = "33333333-3333-4333-8333-333333333333";
    const firstPage = Array.from({ length: 200 }, (_, index) => ({
      id: `00000000-0000-4000-8000-${(index + 1).toString(16).padStart(12, "0")}`,
      mime: "image/png",
      availability: "available",
    }));
    const list = vi.fn().mockImplementation(async ({ cursor }: { cursor?: string }) => ({ ok: true, data: cursor
      ? { items: [
          { id: imageId, mime: "image/jpeg", availability: "available" },
          { id: mediaId, mime: "video/mp4", availability: "available" },
        ], nextCursor: null }
      : { items: firstPage, nextCursor: firstPage[199]!.id },
    }));
    vi.stubGlobal("desktop", { projects: { media: { list } } });

    await expect(listUsableMedia(projectId, "video/")).resolves.toMatchObject([
      { id: mediaId, mime: "video/mp4", availability: "available" },
    ]);
    expect((await listUsableMedia(projectId, "image/")).some((item) => item.id === imageId)).toBe(true);
    expect(list).toHaveBeenCalledTimes(4);
    expect(list).toHaveBeenNthCalledWith(2, { projectId, limit: 200, cursor: firstPage[199]!.id });
    expect(list).toHaveBeenNthCalledWith(4, { projectId, limit: 200, cursor: firstPage[199]!.id });
  });

  it("fails closed if a later media page cannot be read", async () => {
    const list = vi.fn().mockResolvedValueOnce({ ok: true, data: {
      items: [{ id: mediaId, mime: "image/png", availability: "available" }], nextCursor: mediaId,
    }}).mockRejectedValueOnce(new Error("offline"));
    vi.stubGlobal("desktop", { projects: { media: { list } } });
    await expect(listUsableMedia(projectId, "image/")).resolves.toEqual([]);
  });
  it("rechecks exact media ID, availability and image/video MIME", () => {
    const items = [{ id: mediaId, mime: "image/png" as const, availability: "available" as const }];
    expect(hasAvailableMedia(items, mediaId, "image/")).toBe(true);
    expect(hasAvailableMedia(items, mediaId, "video/mp4")).toBe(false);
    expect(hasAvailableMedia(items, projectId, "image/")).toBe(false);
    expect(hasAvailableMedia([{ ...items[0]!, availability: "missing" }], mediaId, "image/")).toBe(false);
  });
  it("only returns available media of the requested mime family", () => {
    expect(
      listUsableMediaResult(
        [
          { id: mediaId, mime: "video/mp4", availability: "available" },
          { id: projectId, mime: "image/png", availability: "missing" },
          { id: projectId, mime: "image/jpeg", availability: "available" },
        ],
        "image/",
      ),
    ).toEqual([
      { id: projectId, mime: "image/jpeg", availability: "available" },
    ]);
  });

  it("constructs local media urls only for validated UUIDs", () => {
    expect(mediaUrl(projectId, mediaId)).toBe(
      `avi-media://local/${projectId}/${mediaId}`,
    );
    expect(mediaUrl("not-a-project", mediaId)).toBeNull();
    expect(mediaUrl(projectId, "not-a-media-id")).toBeNull();
  });

  it("queries an uncertain import instead of submitting it a second time", async () => {
    const importMedia = vi.fn().mockResolvedValue({
      ok: false,
      error: { code: "BACKEND_UNAVAILABLE", message: "offline" },
    });
    const operation = vi.fn().mockResolvedValue({
      ok: false,
      error: { code: "BACKEND_UNAVAILABLE", message: "offline" },
    });
    vi.stubGlobal("desktop", {
      projects: {
        media: {
          chooseFile: vi.fn().mockResolvedValue({
            ok: true,
            data: { grantId: mediaId, name: "reference.png" },
          }),
          import: importMedia,
        },
        drafts: {
          project: vi
            .fn()
            .mockResolvedValue({ ok: true, data: { revision: 3 } }),
          operation,
        },
      },
    });

    await expect(importProjectMedia(projectId, "reference")).resolves.toEqual({
      ok: false,
      reason: "uncertain",
    });
    expect(importMedia).toHaveBeenCalledOnce();
    expect(operation).toHaveBeenCalledOnce();
  });

  it("maps a file-picker transport rejection to a typed failure", async () => {
    vi.stubGlobal("desktop", {
      projects: {
        media: { chooseFile: vi.fn().mockRejectedValue(new Error("offline")) },
      },
    });
    await expect(
      importProjectMedia(projectId, "reference"),
    ).resolves.toMatchObject({
      ok: false,
      reason: "failure",
    });
  });

  it("maps a revision-read transport rejection to a typed failure", async () => {
    vi.stubGlobal("desktop", {
      projects: {
        media: {
          chooseFile: vi.fn().mockResolvedValue({
            ok: true,
            data: { grantId: mediaId, name: "reference.png" },
          }),
        },
        drafts: { project: vi.fn().mockRejectedValue(new Error("offline")) },
      },
    });
    await expect(
      importProjectMedia(projectId, "reference"),
    ).resolves.toMatchObject({
      ok: false,
      reason: "failure",
    });
  });
});
