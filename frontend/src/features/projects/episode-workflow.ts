import {
  readEpisodeDraft,
  readProjectDetails,
} from "./project-detail-model";

export type StageId = "source" | "script" | "assets" | "storyboard" | "video";
export type Review = "not_started" | "review" | "confirmed" | "stale";
export type DemoRun = "idle" | "preparing" | "running" | "failed";
export type MediaRef = {
  kind: "demo-image" | "demo-motion" | "project-image" | "project-video";
  id: string;
};
export type Candidate<T> = {
  id: string;
  value: T;
  source: "demo" | "manual" | "import";
  usableForVideo?: boolean;
};
export type AssetItem = {
  id: string;
  kind: "character" | "scene" | "prop";
  name: string;
  description: string;
  linkedResourceId: string | null;
  imageCandidates: Candidate<MediaRef>[];
  selectedImageId: string | null;
  review: Review;
};
export type ShotItem = {
  id: string;
  title: string;
  description: string;
  action: string;
  dialogue: string;
  plannedMs: number;
  assetIds: string[];
  review: Review;
  firstFrames: Candidate<MediaRef>[];
  selectedFirstId: string | null;
  endFrames: Candidate<MediaRef>[];
  selectedEndId: string | null;
  videos: Candidate<MediaRef>[];
  selectedVideoId: string | null;
  frameReview: Review;
  videoReview: Review;
};
export type GridBatch = {
  id: string;
  sheet: MediaRef;
  cells: { index: number; shotId: string; ref: MediaRef | null; review: Review }[];
};
export type EpisodeWorkflow = {
  version: 2;
  novel: string;
  scriptDraft: string;
  scriptCandidates: Candidate<string>[];
  approvedScript: { text: string; aspect: "16:9" | "9:16"; style: string } | null;
  aspect: "16:9" | "9:16";
  style: string;
  models: {
    script: string;
    analysis: string;
    assetImage: string;
    storyboardText: string;
    storyboardImage: string;
    video: string;
  };
  assets: AssetItem[];
  shots: ShotItem[];
  gridBatches: GridBatch[];
  storyboardMode: "frames" | "grid";
  reviews: Record<StageId, Review>;
  legacyNotes: {
    characters: string;
    props: string;
    scenes: string;
    imagePrompt: string;
    videoPrompt: string;
  };
};

type ReadStore = Pick<Storage, "getItem">;
type WriteStore = Pick<Storage, "setItem">;
export type WorkflowDefaults = {
  aspect?: "16:9" | "9:16";
  style?: string;
};

const workflowKey = (projectId: string, episodeId: string) =>
  `avi-episode-workflow-v2-${projectId}-${episodeId}`;
const reviews = (): Record<StageId, Review> => ({
  source: "not_started",
  script: "not_started",
  assets: "not_started",
  storyboard: "not_started",
  video: "not_started",
});
const models = () => ({
  script: "演示剧本模型",
  analysis: "演示素材分析模型",
  assetImage: "演示素材图片模型",
  storyboardText: "演示分镜脚本模型",
  storyboardImage: "演示分镜图片模型",
  video: "演示分镜视频模型",
});

function resolvedDefaults(
  projectId: string,
  defaults: WorkflowDefaults,
  storage: ReadStore,
) {
  const project = readProjectDetails(projectId, storage);
  return {
    aspect: defaults.aspect ?? project.aspect ?? "16:9",
    style: defaults.style ?? project.style,
  };
}

export function emptyWorkflow(defaults: WorkflowDefaults): EpisodeWorkflow {
  return {
    version: 2,
    novel: "",
    scriptDraft: "",
    scriptCandidates: [],
    approvedScript: null,
    aspect: defaults.aspect ?? "16:9",
    style: defaults.style ?? "",
    models: models(),
    assets: [],
    shots: [],
    gridBatches: [],
    storyboardMode: "frames",
    reviews: reviews(),
    legacyNotes: {
      characters: "",
      props: "",
      scenes: "",
      imagePrompt: "",
      videoPrompt: "",
    },
  };
}

function parseWorkflow(storage: ReadStore, key: string): unknown {
  try {
    return JSON.parse(storage.getItem(key) ?? "null");
  } catch {
    return null;
  }
}

function isReview(value: unknown): value is Review {
  return ["not_started", "review", "confirmed", "stale"].includes(
    value as string,
  );
}

function isAspect(value: unknown): value is "16:9" | "9:16" {
  return value === "16:9" || value === "9:16";
}

function isMediaRef(value: unknown): value is MediaRef {
  if (!value || typeof value !== "object") return false;
  const media = value as Partial<MediaRef>;
  return (
    typeof media.id === "string" &&
    ["demo-image", "demo-motion", "project-image", "project-video"].includes(
      media.kind ?? "",
    )
  );
}

function isCandidate(value: unknown, validValue: (value: unknown) => boolean) {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<Candidate<unknown>>;
  return (
    typeof candidate.id === "string" &&
    validValue(candidate.value) &&
    ["demo", "manual", "import"].includes(candidate.source ?? "") &&
    (candidate.usableForVideo === undefined ||
      typeof candidate.usableForVideo === "boolean")
  );
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isAsset(value: unknown): value is AssetItem {
  if (!value || typeof value !== "object") return false;
  const asset = value as Partial<AssetItem>;
  return (
    typeof asset.id === "string" &&
    ["character", "scene", "prop"].includes(asset.kind ?? "") &&
    typeof asset.name === "string" &&
    typeof asset.description === "string" &&
    (asset.linkedResourceId === null || typeof asset.linkedResourceId === "string") &&
    Array.isArray(asset.imageCandidates) &&
    asset.imageCandidates.every((item) => isCandidate(item, isMediaRef)) &&
    (asset.selectedImageId === null || typeof asset.selectedImageId === "string") &&
    isReview(asset.review)
  );
}

function isShot(value: unknown): value is ShotItem {
  if (!value || typeof value !== "object") return false;
  const shot = value as Partial<ShotItem>;
  const images = (candidates: unknown) =>
    Array.isArray(candidates) &&
    candidates.every((item) => isCandidate(item, isMediaRef));
  return (
    typeof shot.id === "string" &&
    typeof shot.title === "string" &&
    typeof shot.description === "string" &&
    typeof shot.action === "string" &&
    typeof shot.dialogue === "string" &&
    typeof shot.plannedMs === "number" &&
    Number.isFinite(shot.plannedMs) &&
    isStringArray(shot.assetIds) &&
    isReview(shot.review) &&
    images(shot.firstFrames) &&
    (shot.selectedFirstId === null || typeof shot.selectedFirstId === "string") &&
    images(shot.endFrames) &&
    (shot.selectedEndId === null || typeof shot.selectedEndId === "string") &&
    images(shot.videos) &&
    (shot.selectedVideoId === null || typeof shot.selectedVideoId === "string") &&
    isReview(shot.frameReview) &&
    isReview(shot.videoReview)
  );
}

function isGridBatch(value: unknown): value is GridBatch {
  if (!value || typeof value !== "object") return false;
  const batch = value as Partial<GridBatch>;
  return (
    typeof batch.id === "string" &&
    isMediaRef(batch.sheet) &&
    Array.isArray(batch.cells) &&
    batch.cells.every(
      (cell) =>
        typeof cell?.index === "number" &&
        Number.isInteger(cell.index) &&
        typeof cell.shotId === "string" &&
        (cell.ref === null || isMediaRef(cell.ref)) &&
        isReview(cell.review),
    )
  );
}

function hasModels(value: unknown): value is EpisodeWorkflow["models"] {
  if (!value || typeof value !== "object") return false;
  const models = value as Partial<EpisodeWorkflow["models"]>;
  return [
    models.script,
    models.analysis,
    models.assetImage,
    models.storyboardText,
    models.storyboardImage,
    models.video,
  ].every((model) => typeof model === "string");
}

function isWorkflow(value: unknown): value is EpisodeWorkflow {
  if (!value || typeof value !== "object") return false;
  const state = value as Partial<EpisodeWorkflow>;
  return (
    state.version === 2 &&
    typeof state.novel === "string" &&
    typeof state.scriptDraft === "string" &&
    Array.isArray(state.scriptCandidates) &&
    state.scriptCandidates.every((item) => isCandidate(item, (v) => typeof v === "string")) &&
    (state.approvedScript === null ||
      (typeof state.approvedScript === "object" &&
        typeof state.approvedScript.text === "string" &&
        isAspect(state.approvedScript.aspect) &&
        typeof state.approvedScript.style === "string")) &&
    isAspect(state.aspect) &&
    typeof state.style === "string" &&
    hasModels(state.models) &&
    Array.isArray(state.assets) &&
    state.assets.every(isAsset) &&
    Array.isArray(state.shots) &&
    state.shots.every(isShot) &&
    Array.isArray(state.gridBatches) &&
    state.gridBatches.every(isGridBatch) &&
    (state.storyboardMode === "frames" || state.storyboardMode === "grid") &&
    state.reviews !== undefined &&
    (Object.keys(reviews()) as StageId[]).every((stage) => isReview(state.reviews?.[stage])) &&
    state.legacyNotes !== undefined &&
    typeof state.legacyNotes.characters === "string" &&
    typeof state.legacyNotes.props === "string" &&
    typeof state.legacyNotes.scenes === "string" &&
    typeof state.legacyNotes.imagePrompt === "string" &&
    typeof state.legacyNotes.videoPrompt === "string"
  );
}

function freshWorkflow(state: EpisodeWorkflow): EpisodeWorkflow {
  return JSON.parse(JSON.stringify(state)) as EpisodeWorkflow;
}

export function readWorkflow(
  projectId: string,
  episodeId: string,
  defaults: WorkflowDefaults,
  storage: ReadStore = localStorage,
): EpisodeWorkflow {
  const saved = parseWorkflow(storage, workflowKey(projectId, episodeId));
  if (isWorkflow(saved)) return freshWorkflow(saved);

  const resolved = resolvedDefaults(projectId, defaults, storage);
  const legacy = readEpisodeDraft(projectId, episodeId, storage);
  const state = emptyWorkflow(resolved);
  return {
    ...state,
    scriptDraft: legacy.script,
    shots: legacy.shots.map((shot) => ({
      id: shot.id,
      title: shot.title,
      description: shot.description,
      action: "",
      dialogue: "",
      plannedMs: 0,
      assetIds: [],
      review: "not_started",
      firstFrames: [],
      selectedFirstId: null,
      endFrames: [],
      selectedEndId: null,
      videos: [],
      selectedVideoId: null,
      frameReview: "not_started",
      videoReview: "not_started",
    })),
    legacyNotes: {
      characters: legacy.characters,
      props: legacy.props,
      scenes: legacy.scenes,
      imagePrompt: legacy.imagePrompt,
      videoPrompt: legacy.videoPrompt,
    },
  };
}

export function saveWorkflow(
  projectId: string,
  episodeId: string,
  value: EpisodeWorkflow,
  storage: WriteStore = localStorage,
) {
  try {
    storage.setItem(workflowKey(projectId, episodeId), JSON.stringify(value));
    return { ok: true } as const;
  } catch {
    return { ok: false, error: "本集内容未能保存，请检查本地空间。" } as const;
  }
}
