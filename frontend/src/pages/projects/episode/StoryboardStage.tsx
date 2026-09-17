import {
  DEMO_MODELS,
  sampleImage,
  sampleShots,
} from "../../../features/projects/episode-demo";
import {
  bindGridCell,
  createGridBatches,
} from "../../../features/projects/episode-grid";
import {
  adoptFrame,
  editShot,
  isScriptCurrent,
  frameRoleReview,
  shotText,
  type EpisodeWorkflow,
  type GridBatch,
  type MediaRef,
  type ShotItem,
} from "../../../features/projects/episode-workflow";
import {
  storyboardReady,
  shotTextReady,
} from "../../../features/projects/episode-review";
import {
  type ListedMedia,
  hasAvailableMedia,
} from "../../../features/projects/episode-media";
import { ImagePreview } from "./ImagePreview";

export function confirmShotText(
  value: EpisodeWorkflow,
  shotId: string,
): EpisodeWorkflow {
  const shot = value.shots.find((item) => item.id === shotId);
  if (!shot || !shotTextReady(value, { ...shot, review: "confirmed" }))
    return value;
  return {
    ...value,
    shots: value.shots.map((item) =>
      item.id === shotId
        ? { ...item, approvedText: shotText(item), review: "confirmed" }
        : item,
    ),
    reviews: { ...value.reviews, storyboard: "review" },
  };
}
export function confirmStoryboard(
  value: EpisodeWorkflow,
  media: readonly ListedMedia[] = [],
): EpisodeWorkflow {
  return storyboardReady(value, media)
    ? { ...value, reviews: { ...value.reviews, storyboard: "confirmed" } }
    : value;
}

const sameMedia = (left: MediaRef, right: MediaRef) =>
  left.kind === right.kind && left.id === right.id;

export function reorderStoryboardShots(
  value: EpisodeWorkflow,
  shotIds: readonly string[],
): EpisodeWorkflow {
  if (
    shotIds.length !== value.shots.length ||
    new Set(shotIds).size !== value.shots.length
  )
    return value;
  const byId = new Map(value.shots.map((shot) => [shot.id, shot]));
  const shots = shotIds.map((id) => byId.get(id));
  return shots.some((shot) => shot === undefined)
    ? value
    : { ...value, shots: shots as ShotItem[] };
}

export function addStoryboardShot(value: EpisodeWorkflow): EpisodeWorkflow {
  const shot: ShotItem = {
    id: crypto.randomUUID(),
    title: `镜头 ${value.shots.length + 1}`,
    description: "",
    action: "",
    dialogue: "",
    plannedMs: 3000,
    assetIds: [],
    review: "review",
    firstFrames: [],
    selectedFirstId: null,
    endFrames: [],
    selectedEndId: null,
    videos: [],
    selectedVideoId: null,
    frameReview: "not_started",
    videoReview: "not_started",
  };
  return {
    ...value,
    shots: [...value.shots, shot],
    reviews: {
      ...value.reviews,
      storyboard: "review",
      video:
        value.reviews.video === "confirmed" ? "review" : value.reviews.video,
    },
  };
}

export function removeStoryboardShot(
  value: EpisodeWorkflow,
  shotId: string,
): EpisodeWorkflow {
  if (!value.shots.some((shot) => shot.id === shotId)) return value;
  const shots = value.shots.filter((shot) => shot.id !== shotId);
  return {
    ...value,
    shots,
    gridBatches: value.gridBatches.map((batch) => ({
      ...batch,
      cells: batch.cells.filter((cell) => cell.shotId !== shotId),
    })),
    reviews: {
      ...value.reviews,
      storyboard: "review",
      video:
        shots.length > 0 &&
        shots.every((shot) => shot.videoReview === "confirmed")
          ? "confirmed"
          : "review",
    },
  };
}

export function createStoryboardGrids(value: EpisodeWorkflow): EpisodeWorkflow {
  const boundIds = new Set(
    value.gridBatches.flatMap((batch) =>
      batch.cells.map((cell) => cell.shotId),
    ),
  );
  const unboundIds = value.shots
    .map((shot) => shot.id)
    .filter((id) => !boundIds.has(id));
  if (!unboundIds.length) return value;
  const usedBatchIds = new Set(value.gridBatches.map((batch) => batch.id));
  let nextIndex = 1;
  const additions = createGridBatches(unboundIds, (_, ids) =>
    sampleImage(`grid-sheet-${ids.join("-")}`),
  ).map((batch) => {
    while (usedBatchIds.has(`grid-${nextIndex}`)) nextIndex += 1;
    const id = `grid-${nextIndex++}`;
    usedBatchIds.add(id);
    return {
      ...batch,
      id,
      sheet: sampleImage(
        `grid-sheet-${id}-${batch.cells.map((cell) => cell.shotId).join("-")}`,
      ),
    };
  });
  return {
    ...value,
    gridBatches: [...value.gridBatches, ...additions],
    reviews: { ...value.reviews, storyboard: "review" },
  };
}

export function bindStoryboardGridCell(
  value: EpisodeWorkflow,
  batchId: string,
  index: number,
  shotId: string,
  ref: MediaRef | null,
): EpisodeWorkflow {
  const batch = value.gridBatches.find((item) => item.id === batchId);
  if (!batch || (ref !== null && sameMedia(ref, batch.sheet))) return value;
  const nextBatch = bindGridCell(batch, index, shotId, ref);
  if (nextBatch === batch) return value;
  return {
    ...value,
    gridBatches: value.gridBatches.map((item) =>
      item.id === batchId ? nextBatch : item,
    ),
    reviews: { ...value.reviews, storyboard: "review" },
  };
}

export function confirmStoryboardGridCell(
  value: EpisodeWorkflow,
  batchId: string,
  index: number,
  shotId: string,
): EpisodeWorkflow {
  const batch = value.gridBatches.find((item) => item.id === batchId);
  const cell = batch?.cells.find(
    (item) => item.index === index && item.shotId === shotId,
  );
  if (!batch || !cell?.ref) return value;
  return {
    ...value,
    gridBatches: value.gridBatches.map((item) =>
      item.id !== batchId
        ? item
        : {
            ...item,
            cells: item.cells.map((candidate) =>
              candidate.index === index
                ? { ...candidate, review: "confirmed" as const }
                : candidate,
            ),
          },
    ),
  };
}

/** A confirmed crop becomes a shot-owned candidate; the sheet can never be adopted. */
export function adoptGridCellAsFirstFrame(
  value: EpisodeWorkflow,
  batchId: string,
  index: number,
  shotId: string,
): EpisodeWorkflow {
  const batch = value.gridBatches.find((item) => item.id === batchId);
  const cell = batch?.cells.find(
    (item) => item.index === index && item.shotId === shotId,
  );
  if (
    !batch ||
    !cell?.ref ||
    cell.review !== "confirmed" ||
    sameMedia(cell.ref, batch.sheet) ||
    cell.ref.kind === "project-image"
  )
    return value;

  const ref = cell.ref;
  const candidateId = `grid-${batchId}-cell-${index}-${ref.kind}-${ref.id}`;
  const withCandidate = {
    ...value,
    shots: value.shots.map((shot) =>
      shot.id !== shotId
        ? shot
        : {
            ...shot,
            firstFrames: shot.firstFrames.some(
              (candidate) => candidate.id === candidateId,
            )
              ? shot.firstFrames
              : [
                  ...shot.firstFrames,
                  {
                    id: candidateId,
                    value: ref,
                    source:
                      ref.kind === "demo-image"
                        ? ("demo" as const)
                        : ("import" as const),
                    usableForVideo: true,
                  },
                ],
          },
    ),
  };
  return adoptFrame(withCandidate, shotId, "first", candidateId);
}

function addFrameCandidate(
  value: EpisodeWorkflow,
  shotId: string,
  role: "first" | "end",
): EpisodeWorkflow {
  const shot = value.shots.find((item) => item.id === shotId);
  if (!shot || !shotTextReady(value, shot)) return value;
  const list = role === "first" ? shot.firstFrames : shot.endFrames;
  const candidate = {
    id: `demo-${role}-${shot.id}-${list.length + 1}`,
    value: sampleImage(`${role}-${shot.id}-${list.length + 1}`),
    source: "demo" as const,
    usableForVideo: true,
  };
  return {
    ...value,
    shots: value.shots.map((item) =>
      item.id !== shotId
        ? item
        : role === "first"
          ? {
              ...item,
              firstFrames: [...item.firstFrames, candidate],
            }
          : {
              ...item,
              endFrames: [...item.endFrames, candidate],
            },
    ),
    reviews: { ...value.reviews, storyboard: "review" },
  };
}

function frameName(ref: MediaRef) {
  return ref.kind === "project-image" ? "项目图片" : "演示图片";
}

function selectedFirstFrame(shot: ShotItem) {
  return shot.firstFrames.find((item) => item.id === shot.selectedFirstId);
}

export function StoryboardStage({
  value,
  readOnly,
  onChange,
  onReorder,
  onCreateGrid,
  onBindCell,
  projectId,
  mediaItems = [],
}: {
  value: EpisodeWorkflow;
  readOnly: boolean;
  onChange: (next: EpisodeWorkflow) => void;
  projectId?: string;
  mediaItems?: readonly ListedMedia[];
  onReorder?: (shotIds: string[]) => void;
  onCreateGrid?: () => void;
  onBindCell?: (
    batchId: string,
    index: number,
    shotId: string,
    ref: MediaRef | null,
  ) => void;
}) {
  const update = (next: EpisodeWorkflow) => {
    if (!readOnly) onChange(next);
  };
  const moveShot = (index: number, offset: -1 | 1) => {
    if (readOnly) return;
    const nextIndex = index + offset;
    if (nextIndex < 0 || nextIndex >= value.shots.length) return;
    const ids = value.shots.map((shot) => shot.id);
    [ids[index], ids[nextIndex]] = [ids[nextIndex]!, ids[index]!];
    onReorder?.(ids);
    update(reorderStoryboardShots(value, ids));
  };
  const createGrid = () => {
    if (readOnly) return;
    onCreateGrid?.();
    update(createStoryboardGrids(value));
  };
  const boundGridShots = new Set(
    value.gridBatches.flatMap((batch) =>
      batch.cells.map((cell) => cell.shotId),
    ),
  );
  const hasUnboundGridShots = value.shots.some(
    (shot) => !boundGridShots.has(shot.id),
  );
  const bindCell = (
    batch: GridBatch,
    index: number,
    shotId: string,
    ref: MediaRef | null,
  ) => {
    if (readOnly) return;
    onBindCell?.(batch.id, index, shotId, ref);
    update(bindStoryboardGridCell(value, batch.id, index, shotId, ref));
  };

  return (
    <>
      <div className="episode-stage-heading">
        <div>
          <h2>分镜脚本与分镜图</h2>
          <p>逐镜校对动作、对白与时长，再为每个镜头确认可用的首尾画面。</p>
        </div>
        <span>{value.models.storyboardText}</span>
      </div>

      {value.shots.length > 0 && (
        <button
          type="button"
          disabled={readOnly}
          className="episode-add-shot"
          onClick={() => update(addStoryboardShot(value))}
        >
          添加镜头
        </button>
      )}
      <div className="episode-stage-controls">
        <label>
          分镜脚本模型
          <select
            value={value.models.storyboardText}
            disabled={readOnly}
            onChange={(event) =>
              update({
                ...value,
                models: { ...value.models, storyboardText: event.target.value },
              })
            }
          >
            {DEMO_MODELS.storyboardText.map((model) => (
              <option key={model.value} value={model.value}>
                {model.label}
              </option>
            ))}
          </select>
        </label>
        {!value.shots.length && (
          <button
            className="episode-primary-action"
            type="button"
            disabled={readOnly || !isScriptCurrent(value)}
            onClick={() =>
              update({
                ...value,
                shots: isScriptCurrent(value)
                  ? sampleShots(value.approvedScript!.text)
                  : value.shots,
                reviews: { ...value.reviews, storyboard: "review" },
              })
            }
          >
            生成演示分镜脚本
          </button>
        )}
      </div>

      {!value.shots.length ? (
        <p className="episode-help">
          请先确认剧本，再生成或保留已有的演示分镜脚本。
        </p>
      ) : (
        <div className="episode-shot-list" aria-label="镜头脚本">
          {value.shots.map((shot, index) => (
            <article
              className="episode-shot-card episode-storyboard-shot"
              key={shot.id}
            >
              <div className="episode-shot-number">
                {String(index + 1).padStart(2, "0")}
              </div>
              <button
                type="button"
                className="episode-shot-remove"
                disabled={readOnly}
                aria-label={`删除${shot.title}`}
                onClick={() => update(removeStoryboardShot(value, shot.id))}
              >
                删除镜头
              </button>
              <div className="episode-shot-fields">
                {shot.approvedText && (
                  <details className="episode-source-compare">
                    <summary>对照上次确认分镜</summary>
                    <pre>
                      {shot.approvedText.title}
                      {"\n"}
                      {shot.approvedText.description}
                      {"\n"}
                      {shot.approvedText.action}
                      {"\n"}
                      {shot.approvedText.dialogue}
                      {"\n"}计划 {shot.approvedText.plannedMs} ms · 素材{" "}
                      {shot.approvedText.assetIds.join("、") || "无"}
                    </pre>
                  </details>
                )}
                <label>
                  镜头标题
                  <input
                    value={shot.title}
                    readOnly={readOnly}
                    onChange={(event) =>
                      update(
                        editShot(value, shot.id, { title: event.target.value }),
                      )
                    }
                  />
                </label>
                <label>
                  时长（毫秒）
                  <input
                    type="number"
                    min="0"
                    value={shot.plannedMs}
                    readOnly={readOnly}
                    onChange={(event) =>
                      update(
                        editShot(value, shot.id, {
                          plannedMs: Math.max(
                            0,
                            Number(event.target.value) || 0,
                          ),
                        }),
                      )
                    }
                  />
                </label>
                <label>
                  构图说明
                  <textarea
                    rows={2}
                    value={shot.description}
                    readOnly={readOnly}
                    onChange={(event) =>
                      update(
                        editShot(value, shot.id, {
                          description: event.target.value,
                        }),
                      )
                    }
                  />
                </label>
                <label>
                  动作
                  <textarea
                    rows={2}
                    value={shot.action}
                    readOnly={readOnly}
                    onChange={(event) =>
                      update(
                        editShot(value, shot.id, {
                          action: event.target.value,
                        }),
                      )
                    }
                  />
                </label>
                <label>
                  对白
                  <textarea
                    rows={2}
                    value={shot.dialogue}
                    readOnly={readOnly}
                    onChange={(event) =>
                      update(
                        editShot(value, shot.id, {
                          dialogue: event.target.value,
                        }),
                      )
                    }
                  />
                </label>
                <fieldset className="episode-shot-assets" disabled={readOnly}>
                  <legend>关联素材</legend>
                  {value.assets.length ? (
                    value.assets.map((asset) => (
                      <label key={asset.id}>
                        <input
                          type="checkbox"
                          checked={shot.assetIds.includes(asset.id)}
                          onChange={(event) =>
                            update(
                              editShot(value, shot.id, {
                                assetIds: event.target.checked
                                  ? [...shot.assetIds, asset.id]
                                  : shot.assetIds.filter(
                                      (id) => id !== asset.id,
                                    ),
                              }),
                            )
                          }
                        />
                        {asset.name}
                      </label>
                    ))
                  ) : (
                    <span>尚无已拆解素材</span>
                  )}
                </fieldset>
                <button
                  type="button"
                  disabled={
                    readOnly ||
                    !shotTextReady(value, { ...shot, review: "confirmed" })
                  }
                  onClick={() => update(confirmShotText(value, shot.id))}
                >
                  确认本镜文字
                </button>
                <span>
                  {shot.review === "confirmed"
                    ? "文字已确认"
                    : shot.review === "stale"
                      ? "文字需复核"
                      : "文字待核对"}
                </span>
                {!shotTextReady(value, { ...shot, review: "confirmed" }) && (
                  <p className="episode-help">
                    请确认当前剧本，并补全镜头标题、构图、动作与正数时长。
                  </p>
                )}
              </div>
              <div
                className="episode-reorder-actions"
                aria-label={`${shot.title}排序`}
              >
                <button
                  type="button"
                  disabled={readOnly || index === 0}
                  onClick={() => moveShot(index, -1)}
                >
                  上移
                </button>
                <button
                  type="button"
                  disabled={readOnly || index === value.shots.length - 1}
                  onClick={() => moveShot(index, 1)}
                >
                  下移
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      {value.shots.length > 0 && (
        <>
          <div className="episode-storyboard-tools">
            <label>
              分镜图片模型
              <select
                value={value.models.storyboardImage}
                disabled={readOnly}
                onChange={(event) =>
                  update({
                    ...value,
                    models: {
                      ...value.models,
                      storyboardImage: event.target.value,
                    },
                  })
                }
              >
                {DEMO_MODELS.storyboardImage.map((model) => (
                  <option key={model.value} value={model.value}>
                    {model.label}
                  </option>
                ))}
              </select>
            </label>
            <div
              className="episode-mode-switch"
              role="group"
              aria-label="分镜图片方式"
            >
              <button
                type="button"
                aria-pressed={value.storyboardMode === "frames"}
                disabled={readOnly}
                onClick={() => update({ ...value, storyboardMode: "frames" })}
              >
                首尾帧
              </button>
              <button
                type="button"
                aria-pressed={value.storyboardMode === "grid"}
                disabled={readOnly}
                onClick={() => update({ ...value, storyboardMode: "grid" })}
              >
                九宫格分镜
              </button>
            </div>
          </div>

          {value.storyboardMode === "frames" ? (
            <div className="episode-frame-candidates">
              {value.shots.map((shot) => (
                <article className="episode-frame-row" key={shot.id}>
                  <header>
                    <strong>{shot.title}</strong>
                    <span>{shot.plannedMs} ms</span>
                  </header>
                  {(["first", "end"] as const).map((role) => {
                    const candidates =
                      role === "first" ? shot.firstFrames : shot.endFrames;
                    const selectedId =
                      role === "first"
                        ? shot.selectedFirstId
                        : shot.selectedEndId;
                    return (
                      <section className="episode-frame-role" key={role}>
                        <h3>{role === "first" ? "首帧" : "尾帧"}</h3>
                        <button
                          type="button"
                          disabled={readOnly || !shotTextReady(value, shot)}
                          onClick={() =>
                            update(addFrameCandidate(value, shot.id, role))
                          }
                        >
                          生成演示{role === "first" ? "首帧" : "尾帧"}
                        </button>
                        {candidates.map((candidate) => (
                          <button
                            type="button"
                            className={
                              candidate.id === selectedId ? "selected" : ""
                            }
                            disabled={
                              readOnly ||
                              !shotTextReady(value, shot) ||
                              (candidate.value.kind === "project-image" &&
                                !hasAvailableMedia(
                                  mediaItems,
                                  candidate.value.id,
                                  "image/",
                                ))
                            }
                            key={candidate.id}
                            onClick={() =>
                              update(
                                adoptFrame(value, shot.id, role, candidate.id),
                              )
                            }
                          >
                            <ImagePreview
                              media={candidate.value}
                              label={`${shot.title}${role === "first" ? "首帧" : "尾帧"}候选`}
                              projectId={projectId}
                              mediaItems={mediaItems}
                            />
                            {frameName(candidate.value)}{" "}
                            {candidate.id === selectedId ? "已采用" : "采用"}
                          </button>
                        ))}
                        <small>
                          {frameRoleReview(shot, role) === "confirmed"
                            ? "已确认"
                            : frameRoleReview(shot, role) === "stale"
                              ? "需复核"
                              : "待核对"}
                        </small>
                      </section>
                    );
                  })}
                  <p className="episode-tail-note">
                    不支持尾帧的视频模型会将其视为仅供审核参考。
                  </p>
                </article>
              ))}
            </div>
          ) : (
            <div className="episode-grid-area">
              {hasUnboundGridShots && (
                <button
                  className="episode-primary-action"
                  type="button"
                  disabled={
                    readOnly ||
                    !value.shots.every((shot) => shotTextReady(value, shot))
                  }
                  onClick={createGrid}
                >
                  {value.gridBatches.length
                    ? "为新增镜头生成九宫格"
                    : "生成演示九宫格"}
                </button>
              )}
              {value.gridBatches.map((batch) => (
                <section className="episode-grid-batch" key={batch.id}>
                  <header>
                    <div>
                      <h3>九宫格 {batch.id.replace("grid-", "")}</h3>
                      <p>
                        每格固定对应一个镜头；整张分镜表不会作为单镜头视频输入。
                      </p>
                    </div>
                    <span className="episode-review-only">仅供分镜参考</span>
                  </header>
                  <div
                    className="episode-grid-sheet"
                    aria-label="整张九宫格演示参考"
                  >
                    <p>整张九宫格演示参考 · 固定镜头顺序</p>
                    {batch.sheet.kind === "project-image" ? (
                      <ImagePreview
                        media={batch.sheet}
                        label="整张九宫格参考"
                        projectId={projectId}
                        mediaItems={mediaItems}
                      />
                    ) : (
                      <div className="episode-nine-grid">
                        {batch.cells.map((cell) => (
                          <ImagePreview
                            key={cell.index}
                            media={sampleImage(
                              `${batch.id}-${cell.index}-${cell.shotId}`,
                            )}
                            label={`第 ${cell.index + 1} 格 ${cell.shotId}`}
                            projectId={projectId}
                            mediaItems={mediaItems}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                  <div
                    className="episode-nine-grid"
                    aria-label={`${batch.id}九宫格`}
                  >
                    {batch.cells.map((cell) => {
                      const shot = value.shots.find(
                        (item) => item.id === cell.shotId,
                      );
                      return (
                        <article className="episode-grid-cell" key={cell.index}>
                          <div className="episode-grid-thumb">
                            <ImagePreview
                              media={
                                cell.ref ??
                                sampleImage(
                                  `${batch.id}-${cell.index}-${cell.shotId}`,
                                )
                              }
                              label={`第 ${cell.index + 1} 格 ${shot?.title ?? cell.shotId}`}
                              projectId={projectId}
                              mediaItems={mediaItems}
                            />
                          </div>
                          <strong>{shot?.title || cell.shotId}</strong>
                          <small>固定 ID：{cell.shotId}</small>
                          {cell.ref?.kind === "project-image" && (
                            <span className="episode-review-only">
                              仅供分镜参考
                            </span>
                          )}
                          <div>
                            <button
                              type="button"
                              disabled={
                                readOnly || !shot || !shotTextReady(value, shot)
                              }
                              onClick={() =>
                                bindCell(
                                  batch,
                                  cell.index,
                                  cell.shotId,
                                  sampleImage(
                                    `${batch.id}-${cell.index}-${cell.shotId}`,
                                  ),
                                )
                              }
                            >
                              生成演示单格
                            </button>
                            <button
                              type="button"
                              disabled={
                                readOnly ||
                                !cell.ref ||
                                !shot ||
                                !shotTextReady(value, shot)
                              }
                              onClick={() =>
                                update(
                                  confirmStoryboardGridCell(
                                    value,
                                    batch.id,
                                    cell.index,
                                    cell.shotId,
                                  ),
                                )
                              }
                            >
                              确认单格
                            </button>
                            <button
                              className="episode-primary-action"
                              type="button"
                              disabled={
                                readOnly ||
                                !shot ||
                                !shotTextReady(value, shot) ||
                                cell.review !== "confirmed" ||
                                !cell.ref ||
                                cell.ref.kind === "project-image"
                              }
                              onClick={() =>
                                update(
                                  adoptGridCellAsFirstFrame(
                                    value,
                                    batch.id,
                                    cell.index,
                                    cell.shotId,
                                  ),
                                )
                              }
                            >
                              采用为首帧
                            </button>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          )}

          <section className="episode-static-preview" aria-label="静态预览">
            <header>
              <h3>静态预览</h3>
              <p>按镜头顺序展示已采用首帧与计划时长，不生成或预告视频。</p>
            </header>
            <ol>
              {value.shots.map((shot) => {
                const frame = selectedFirstFrame(shot);
                return (
                  <li key={shot.id}>
                    <ImagePreview
                      media={frame?.value}
                      label={`${shot.title}静态首帧`}
                      projectId={projectId}
                      mediaItems={mediaItems}
                    />
                    <strong>{shot.title}</strong>
                    <p>
                      {shot.description} {shot.action}
                    </p>
                    <small>{shot.plannedMs} ms</small>
                  </li>
                );
              })}
            </ol>
          </section>
          <button
            className="episode-primary-action"
            type="button"
            disabled={readOnly || !storyboardReady(value, mediaItems)}
            onClick={() => update(confirmStoryboard(value, mediaItems))}
          >
            确认分镜阶段
          </button>
          {!storyboardReady(value, mediaItems) && (
            <p className="episode-help">
              请逐镜确认文字与首帧，并确认引用素材图片可用。
            </p>
          )}
        </>
      )}
    </>
  );
}
