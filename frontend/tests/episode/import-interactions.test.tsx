import React, { type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  emptyWorkflow,
  type EpisodeWorkflow,
} from "../../src/features/projects/episode-workflow";
import {
  sampleAssets,
  sampleShots,
} from "../../src/features/projects/episode-demo";
import { AssetsStage } from "../../src/pages/projects/episode/AssetsStage";
import { VideoStage } from "../../src/pages/projects/episode/VideoStage";
import * as media from "../../src/features/projects/episode-media";
import * as resources from "../../src/features/projects/project-detail-model";

// Node-only event harness. The external bridge/storage is mocked; real component
// handlers and state transitions run, with hooks retained between explicit renders.
const hooks = vi.hoisted(() => ({
  values: [] as unknown[],
  index: 0,
  cleanups: [] as (() => void)[],
  effects: [] as (() => void)[],
}));
vi.mock("react", async (importOriginal) => {
  const original = await importOriginal<typeof import("react")>();
  return {
    ...original,
    useState: (initial: unknown) => {
      const i = hooks.index++;
      if (!(i in hooks.values))
        hooks.values[i] = typeof initial === "function" ? initial() : initial;
      return [
        hooks.values[i],
        (next: unknown) => {
          hooks.values[i] =
            typeof next === "function" ? next(hooks.values[i]) : next;
        },
      ];
    },
    useRef: (initial: unknown) => {
      const i = hooks.index++;
      return (hooks.values[i] ??= { current: initial });
    },
    useMemo: (fn: () => unknown) => fn(),
    useEffect: (fn: () => void | (() => void), deps: unknown[]) => {
      const i = hooks.index++;
      const old = hooks.values[i] as unknown[] | undefined;
      if (!old || deps.some((v, j) => v !== old[j])) {
        hooks.values[i] = deps;
        hooks.effects.push(() => {
          const cleanup = fn();
          if (cleanup) hooks.cleanups.push(cleanup);
        });
      }
    },
  };
});

function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (React.isValidElement<{ children?: ReactNode }>(node))
    return textOf(node.props.children);
  return "";
}
function buttons(
  node: ReactNode,
  name: string,
): { props: { onClick: () => unknown; disabled?: boolean } }[] {
  if (Array.isArray(node)) return node.flatMap((child) => buttons(child, name));
  if (React.isValidElement<{ children?: ReactNode }>(node)) {
    if (node.type === "button" && textOf(node.props.children) === name)
      return [node as never];
    return buttons(node.props.children, name);
  }
  return [];
}
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};
const tick = async () => {
  for (let i = 0; i < 12; i++) await Promise.resolve();
};
const projectId = "11111111-1111-4111-8111-111111111111";
const idA = "22222222-2222-4222-8222-222222222222";
const idB = "33333333-3333-4333-8333-333333333333";

beforeEach(() => {
  hooks.cleanups.forEach((fn) => fn());
  hooks.values = [];
  hooks.index = 0;
  hooks.effects = [];
  hooks.cleanups = [];
  vi.restoreAllMocks();
  vi.spyOn(resources, "readProjectResources").mockReturnValue([]);
});

describe("deferred import interactions", () => {
  it.each(["image", "video"] as const)(
    "merges concurrent %s imports into the latest edited state",
    async (kind) => {
      let value = emptyWorkflow({});
      value.assets = sampleAssets();
      value.shots = sampleShots("剧本");
      const first = deferred<media.MediaImportResult>(),
        second = deferred<media.MediaImportResult>();
      vi.spyOn(media, "importProjectMedia")
        .mockReturnValueOnce(first.promise)
        .mockReturnValueOnce(second.promise);
      vi.spyOn(media, "listUsableMedia").mockResolvedValue(
        [idA, idB].map((id) => ({
          id,
          mime: kind === "image" ? "image/png" : "video/mp4",
          availability: "available",
        })) as never,
      );
      const onChange = (next: EpisodeWorkflow) => {
        value = next;
        render();
      };
      const render = () => {
        hooks.index = 0;
        const node =
          kind === "image"
            ? AssetsStage({
                value,
                readOnly: false,
                ready: true,
                projectId,
                onChange,
              })
            : VideoStage({
                value,
                readOnly: false,
                ready: true,
                projectId,
                onChange,
              });
        hooks.effects.splice(0).forEach((fn) => fn());
        return node;
      };
      const node = render();
      const controls = buttons(
        node,
        kind === "image" ? "导入项目图片" : "导入项目 MP4",
      );
      controls[0]!.props.onClick();
      controls[1]!.props.onClick();
      value = { ...value, novel: "导入期间用户的新修改" };
      render();
      second.resolve({ ok: true, mediaId: idB });
      await tick();
      first.resolve({ ok: true, mediaId: idA });
      await tick();
      expect(value.novel).toBe("导入期间用户的新修改");
      const outputs =
        kind === "image"
          ? value.assets.map((item) => item.imageCandidates)
          : value.shots.map((item) => item.videos);
      expect(outputs[0]).toHaveLength(1);
      expect(outputs[1]).toHaveLength(1);
    },
  );

  it.each(["image", "video"] as const)(
    "ignores %s import after its episode component leaves",
    async (kind) => {
      let value = emptyWorkflow({});
      value.assets = sampleAssets();
      value.shots = sampleShots("剧本");
      const pending = deferred<media.MediaImportResult>();
      vi.spyOn(media, "importProjectMedia").mockReturnValue(pending.promise);
      vi.spyOn(media, "listUsableMedia").mockResolvedValue([
        {
          id: idA,
          mime: kind === "image" ? "image/png" : "video/mp4",
          availability: "available",
        },
      ] as never);
      const onChange = (next: EpisodeWorkflow) => {
        value = next;
      };
      const before = value;
      const node =
        kind === "image"
          ? AssetsStage({
              value,
              readOnly: false,
              ready: true,
              projectId,
              onChange,
            })
          : VideoStage({
              value,
              readOnly: false,
              ready: true,
              projectId,
              onChange,
            });
      hooks.effects.splice(0).forEach((fn) => fn());
      buttons(
        node,
        kind === "image" ? "导入项目图片" : "导入项目 MP4",
      )[0]!.props.onClick();
      hooks.cleanups.forEach((fn) => fn());
      pending.resolve({ ok: true, mediaId: idA });
      await tick();
      expect(value).toBe(before);
    },
  );

  it("reports failed resource storage and preserves linkage", () => {
    let value = emptyWorkflow({});
    value.assets = sampleAssets().slice(0, 1);
    value.assets[0] = {
      ...value.assets[0]!,
      linkedResourceId: "old-link",
      review: "confirmed",
      selectedImageId: "selected",
      imageCandidates: [
        {
          id: "selected",
          source: "demo",
          value: { kind: "demo-image", id: "demo-image-safe" },
        },
      ],
    };
    vi.spyOn(resources, "saveProjectResources").mockImplementation(() => {
      throw new Error("quota");
    });
    const render = () => {
      hooks.index = 0;
      return AssetsStage({
        value,
        readOnly: false,
        ready: false,
        projectId,
        onChange: (next) => {
          value = next;
        },
      });
    };
    const node = render();
    expect(() =>
      buttons(node, "共享到项目资源库")[0]!.props.onClick(),
    ).not.toThrow();
    expect(value.assets[0]!.linkedResourceId).toBe("old-link");
    expect(textOf(render())).toContain("资源库未能保存");
  });
});
