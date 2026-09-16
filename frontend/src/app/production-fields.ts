import type { Draft } from "../../electron/shared/drafts";

export type ProductionKind = "speech" | "subtitle" | "timeline" | "observation";
export type Content = Draft["content"]["content"];
export type Row = Record<string, unknown>;
export const uid = () => crypto.randomUUID();
export const word = (value: unknown) =>
  typeof value === "string" ? value : "";
export const number = (value: unknown, fallback = 0) =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;
export const rows = (value: unknown): Row[] =>
  Array.isArray(value)
    ? value.filter(
        (item): item is Row =>
          !!item && typeof item === "object" && !Array.isArray(item),
      )
    : [];
export const ids = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
export const patch = (list: Row[], index: number, change: Row) =>
  list.map((item, i) => (i === index ? { ...item, ...change } : item));

export function blank(kind: ProductionKind): Draft {
  const content: Content =
    kind === "speech"
      ? {
          text: "",
          timingMethod: "manual",
          voicedRanges: [],
          pronunciationNotes: "",
        }
      : kind === "subtitle"
        ? { audioRevisionId: null, timingMethod: "manual", cues: [] }
        : kind === "timeline"
          ? {
              width: 1920,
              height: 1080,
              fps: { numerator: 24, denominator: 1 },
              durationMs: 30000,
              tracks: [],
              clips: [],
              transitions: [],
              burnSubtitles: true,
            }
          : {
              method: "human",
              observed: [],
              usable: [],
              problems: [],
              limitations: "",
            };
  return {
    id: uid(),
    artifactId: uid(),
    baseRevisionId: null,
    content: { kind, content },
  };
}

export function newTrack(kind: string, order: number): Row {
  return { id: uid(), kind, order, muted: false };
}

export function newClip(trackId: string, durationMs: number): Row {
  return {
    id: uid(),
    trackId,
    shotId: null,
    mediaId: null,
    contentRevisionId: null,
    startMs: 0,
    inMs: 0,
    outMs: durationMs,
    durationMs,
    gainDb: 0,
    linkedClipIds: [],
    keyframes: [],
  };
}

export function duplicateMusicClip(clip: Row): Row {
  return {
    ...clip,
    id: uid(),
    startMs: number(clip.startMs) + number(clip.durationMs),
    linkedClipIds: [],
  };
}
