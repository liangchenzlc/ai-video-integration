import { useEffect, useMemo, useRef, useState } from "react";
import type {
  AssetKind,
  AssetVisualRef,
  GlobalAsset,
} from "../../../features/assets/asset-model";
import {
  DEMO_MODELS,
  sampleImage,
} from "../../../features/projects/episode-demo";
import { ImagePreview } from "./ImagePreview";
import { AssetControls } from "./AssetControls";
import {
  editAsset,
  assetText,
  removeAsset,
  type AssetItem,
  type EpisodeWorkflow,
  type MediaRef,
} from "../../../features/projects/episode-workflow";
import {
  importProjectMedia,
  listUsableMedia,
  type ListedMedia,
} from "../../../features/projects/episode-media";
import {
  readProjectResources,
  saveProjectResources,
} from "../../../features/projects/project-detail-model";

type ShareChoice = "link" | "create";
type ShareInput = AssetItem;
export type ShareResult =
  | { ok: true; linkedResourceId: string; resources: GlobalAsset[] }
  | { ok: false; reason: "invalid" }
  | { ok: false; reason: "choice_required"; matches: GlobalAsset[] };

const kindLabel: Record<AssetKind, string> = {
  character: "角色",
  scene: "场景",
  prop: "道具",
};

export function shareAsset(
  asset: ShareInput,
  resources: GlobalAsset[],
  choice?: ShareChoice,
  visualRef?: AssetVisualRef,
  mediaItems: readonly ListedMedia[] = [],
): ShareResult {
  const selected = selectedRef(asset);
  if (
    !asset.name.trim() ||
    !asset.description.trim() ||
    asset.review !== "confirmed" ||
    !selected ||
    !["demo-image", "project-image"].includes(selected.kind) ||
    (selected.kind === "project-image" &&
      !canBindImportedImage(mediaItems, selected.id))
  )
    return { ok: false, reason: "invalid" };
  visualRef ??= {
    kind: selected.kind as AssetVisualRef["kind"],
    id: selected.id,
  };
  const linked = resources.find((item) => item.id === asset.linkedResourceId);
  const matches = resources.filter(
    (item) =>
      item.kind === asset.kind &&
      item.name.trim().toLocaleLowerCase() ===
        asset.name.trim().toLocaleLowerCase(),
  );
  if (!choice && !linked && matches.length)
    return { ok: false, reason: "choice_required", matches };
  const target =
    choice === "create"
      ? undefined
      : (linked ?? (choice === "link" ? matches[0] : undefined));
  if (target) {
    const next = {
      ...target,
      name: asset.name.trim(),
      description: asset.description.trim(),
      ...(visualRef ? { visualRef } : {}),
    };
    return {
      ok: true,
      linkedResourceId: target.id,
      resources: resources.map((item) => (item.id === target.id ? next : item)),
    };
  }
  const created: GlobalAsset = {
    id: crypto.randomUUID(),
    kind: asset.kind,
    name: asset.name.trim(),
    description: asset.description.trim(),
    category: "",
    tags: [],
    createdAt: new Date().toISOString(),
    ...(visualRef ? { visualRef } : {}),
  };
  return {
    ok: true,
    linkedResourceId: created.id,
    resources: [...resources, created],
  };
}

function selectedRef(asset: AssetItem): MediaRef | null {
  return (
    asset.imageCandidates.find((item) => item.id === asset.selectedImageId)
      ?.value ?? null
  );
}

export function canBindImportedImage(
  items: readonly { id: string; mime: string; availability: string }[],
  mediaId: string,
) {
  return items.some(
    (item) =>
      item.id === mediaId &&
      item.availability === "available" &&
      item.mime.startsWith("image/"),
  );
}

function addAssetImageCandidate(
  value: EpisodeWorkflow,
  assetId: string,
  candidate: AssetItem["imageCandidates"][number],
): EpisodeWorkflow {
  const stale = editAsset(value, assetId, {});
  return {
    ...stale,
    assets: stale.assets.map((item) =>
      item.id === assetId
        ? { ...item, imageCandidates: [...item.imageCandidates, candidate] }
        : item,
    ),
  };
}

/** Adoption records the candidate itself; a demo never becomes project media. */
export function adoptAssetImage(
  value: EpisodeWorkflow,
  assetId: string,
  candidateId: string,
): EpisodeWorkflow {
  const asset = value.assets.find((item) => item.id === assetId);
  if (!asset?.imageCandidates.some((item) => item.id === candidateId))
    return value;
  const stale = editAsset(value, assetId, {});
  return {
    ...stale,
    assets: stale.assets.map((item) =>
      item.id === assetId
        ? { ...item, selectedImageId: candidateId, review: "review" }
        : item,
    ),
  };
}

export function AssetsStage({
  value,
  readOnly,
  ready,
  projectId,
  onChange,
  onApply,
}: {
  value: EpisodeWorkflow;
  readOnly: boolean;
  ready: boolean;
  projectId: string;
  onChange: (next: EpisodeWorkflow) => void;
  onApply?: (change: (current: EpisodeWorkflow) => EpisodeWorkflow) => void;
}) {
  const latest = useRef(value);
  latest.current = value;
  const lifetime = useRef({ active: true });
  useEffect(() => {
    const token = { active: true };
    lifetime.current = token;
    return () => {
      token.active = false;
    };
  }, [projectId, readOnly, ready]);
  const [resources, setResources] = useState(() =>
    readProjectResources(projectId),
  );
  const [usableImages, setUsableImages] = useState<
    Awaited<ReturnType<typeof listUsableMedia>>
  >([]);
  const [message, setMessage] = useState(
    ready ? "" : "本地媒体服务尚未就绪，无法读取或导入项目图片。 ",
  );
  const [choiceFor, setChoiceFor] = useState<string | null>(null);
  const [importing, setImporting] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setResources(readProjectResources(projectId));
    setChoiceFor(null);
    if (!ready) return setUsableImages([]);
    void listUsableMedia(projectId, "image/").then((items) => {
      if (active) setUsableImages(items);
    });
    return () => {
      active = false;
    };
  }, [projectId, ready]);

  const groups = useMemo(
    () =>
      (["character", "scene", "prop"] as const).map(
        (kind) =>
          [kind, value.assets.filter((asset) => asset.kind === kind)] as const,
      ),
    [value.assets],
  );
  function update(next: EpisodeWorkflow) {
    onChange(next);
  }
  function select(asset: AssetItem, candidateId: string) {
    update(adoptAssetImage(value, asset.id, candidateId));
  }
  function confirm(asset: AssetItem) {
    if (!canConfirm(asset)) return;
    const nextAssets = value.assets.map((item) =>
      item.id === asset.id
        ? {
            ...item,
            approvedText: assetText(item),
            review: "confirmed" as const,
          }
        : item,
    );
    update({
      ...value,
      assets: nextAssets,
      reviews: {
        ...value.reviews,
        assets: nextAssets.every((item) => item.review === "confirmed")
          ? "confirmed"
          : "review",
      },
    });
  }
  function share(asset: AssetItem, choice?: ShareChoice) {
    if (readOnly || !canConfirm(asset) || asset.review !== "confirmed") return;
    const chosen = selectedRef(asset);
    const visualRef: AssetVisualRef | undefined =
      chosen?.kind === "project-image" || chosen?.kind === "demo-image"
        ? { kind: chosen.kind, id: chosen.id }
        : undefined;
    const result = shareAsset(
      asset,
      resources,
      choice,
      visualRef,
      usableImages,
    );
    if (!result.ok) {
      if (result.reason === "choice_required") setChoiceFor(asset.id);
      else setMessage("请先补全素材名称和描述，选图并确认素材可用。");
      return;
    }
    try {
      saveProjectResources(projectId, result.resources);
    } catch {
      setMessage("资源库未能保存，请检查本地空间后重试；原关联已保留。");
      return;
    }
    setResources(result.resources);
    setChoiceFor(null);
    update({
      ...value,
      assets: value.assets.map((item) =>
        item.id === asset.id
          ? { ...item, linkedResourceId: result.linkedResourceId }
          : item,
      ),
    });
    setMessage("已更新项目资源库。 ");
  }
  async function importImage(asset: AssetItem) {
    if (readOnly || !ready) return;
    const token = lifetime.current;
    setImporting(asset.id);
    const result = await importProjectMedia(projectId, "reference");
    if (!token.active) return;
    setImporting(null);
    if (!result.ok) {
      setMessage(
        result.reason === "cancelled"
          ? "未选择图片。"
          : result.reason === "uncertain"
            ? "导入结果仍待核对；没有再次提交导入。"
            : (result.message ?? "图片导入失败。 "),
      );
      return;
    }
    const latestImages = await listUsableMedia(projectId, "image/");
    if (!token.active) return;
    setUsableImages(latestImages);
    if (!canBindImportedImage(latestImages, result.mediaId)) {
      setMessage(
        "导入结果不是可用图片，未添加为候选。请在项目媒体库核对导入或重新定位原文件。 ",
      );
      return;
    }
    const candidate = {
      id: crypto.randomUUID(),
      source: "import" as const,
      value: { kind: "project-image" as const, id: result.mediaId },
      usableForVideo: true,
    };
    const apply = (current: EpisodeWorkflow) =>
      current.assets.some((item) => item.id === asset.id)
        ? adoptAssetImage(
            addAssetImageCandidate(current, asset.id, candidate),
            asset.id,
            candidate.id,
          )
        : current;
    if (onApply) onApply(apply);
    else {
      latest.current = apply(latest.current);
      update(latest.current);
    }
    setMessage("图片已导入，等待你确认采用。 ");
  }
  function canConfirm(asset: AssetItem) {
    const ref = selectedRef(asset);
    return (
      !!asset.name.trim() &&
      !!asset.description.trim() &&
      !!ref &&
      (ref.kind === "demo-image" ||
        (ref.kind === "project-image" &&
          canBindImportedImage(usableImages, ref.id)))
    );
  }
  function addExisting(asset: AssetItem, mediaId: string) {
    if (
      asset.imageCandidates.some(
        (candidate) =>
          candidate.value.kind === "project-image" &&
          candidate.value.id === mediaId,
      )
    )
      return;
    const candidate = {
      id: crypto.randomUUID(),
      source: "import" as const,
      value: { kind: "project-image" as const, id: mediaId },
      usableForVideo: true,
    };
    update(addAssetImageCandidate(value, asset.id, candidate));
  }

  return (
    <>
      <div className="episode-stage-heading">
        <div>
          <h2>素材图片</h2>
          <p>
            编辑并审核角色、场景和道具。演示图片不会连接到本地媒体；项目图片仅在可用时可采用。
          </p>
        </div>
        <label>
          素材图片演示模型
          <select
            value={value.models.assetImage}
            disabled={readOnly}
            onChange={(event) =>
              update({
                ...value,
                models: { ...value.models, assetImage: event.target.value },
              })
            }
          >
            <option value={value.models.assetImage}>
              {value.models.assetImage}
            </option>
            {DEMO_MODELS.assetImage
              .filter((model) => model.value !== value.models.assetImage)
              .map((model) => (
                <option key={model.value} value={model.value}>
                  {model.label}
                </option>
              ))}
          </select>
        </label>
      </div>
      <AssetControls value={value} readOnly={readOnly} onChange={update} />
      {message && (
        <p className="episode-help" role="status">
          {message}
        </p>
      )}
      {!value.assets.length && (
        <p className="episode-help">
          请先在“剧本确认与素材拆解”中演示分析素材，再在此处审核图片。
        </p>
      )}
      {groups.map(([kind, assets]) =>
        assets.length ? (
          <section className="episode-assets-group" key={kind}>
            <h3>{kindLabel[kind]}</h3>
            <div className="episode-asset-list">
              {assets.map((asset) => {
                const adopted = selectedRef(asset);
                return (
                  <article
                    key={asset.id}
                    className="episode-candidate episode-asset-card"
                  >
                    {asset.approvedText && (
                      <details className="episode-source-compare">
                        <summary>对照上次确认素材</summary>
                        <pre>
                          {asset.approvedText.name}
                          {"\n"}
                          {asset.approvedText.description}
                        </pre>
                      </details>
                    )}
                    <label>
                      名称
                      <input
                        value={asset.name}
                        readOnly={readOnly}
                        onChange={(event) =>
                          update(
                            editAsset(value, asset.id, {
                              name: event.target.value,
                            }),
                          )
                        }
                      />
                    </label>
                    <label>
                      描述
                      <textarea
                        rows={3}
                        value={asset.description}
                        readOnly={readOnly}
                        onChange={(event) =>
                          update(
                            editAsset(value, asset.id, {
                              description: event.target.value,
                            }),
                          )
                        }
                      />
                    </label>
                    <div className="episode-asset-preview">
                      <ImagePreview
                        media={adopted}
                        label={`${asset.name}已采用图片`}
                        projectId={projectId}
                        mediaItems={usableImages}
                        kind={asset.kind}
                      />
                    </div>
                    <div className="episode-asset-actions">
                      <button
                        type="button"
                        disabled={readOnly}
                        onClick={() => {
                          const ref = sampleImage(
                            `${asset.id}-${asset.imageCandidates.length}`,
                          );
                          const candidate = {
                            id: crypto.randomUUID(),
                            source: "demo" as const,
                            value: ref,
                            usableForVideo: true,
                          };
                          update(
                            addAssetImageCandidate(value, asset.id, candidate),
                          );
                        }}
                      >
                        生成演示图片
                      </button>
                      <button
                        type="button"
                        disabled={readOnly || !ready || importing === asset.id}
                        onClick={() => void importImage(asset)}
                      >
                        {importing === asset.id ? "正在导入…" : "导入项目图片"}
                      </button>
                    </div>
                    {ready && (
                      <label>
                        选择已可用项目图片
                        <select
                          value=""
                          disabled={readOnly}
                          onChange={(event) => {
                            if (event.target.value)
                              addExisting(asset, event.target.value);
                          }}
                        >
                          <option value="">从项目媒体库添加</option>
                          {usableImages.map((image) => (
                            <option key={image.id} value={image.id}>
                              {image.id.slice(0, 8)}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    {asset.imageCandidates.length > 0 && (
                      <div
                        className="episode-image-candidates"
                        role="list"
                        aria-label={`${asset.name}图片候选`}
                      >
                        {asset.imageCandidates.map((candidate) => (
                          <button
                            type="button"
                            role="listitem"
                            key={candidate.id}
                            className={
                              candidate.id === asset.selectedImageId
                                ? "selected"
                                : ""
                            }
                            disabled={readOnly}
                            onClick={() => select(asset, candidate.id)}
                          >
                            <ImagePreview
                              media={candidate.value}
                              label={`${asset.name}候选`}
                              projectId={projectId}
                              mediaItems={usableImages}
                              kind={asset.kind}
                            />
                            {candidate.value.kind === "demo-image"
                              ? "演示图片"
                              : candidate.value.kind === "project-image"
                                ? "项目图片"
                                : "不可用于素材图片"}
                          </button>
                        ))}
                      </div>
                    )}
                    <div className="episode-asset-actions">
                      <button
                        className="episode-primary-action"
                        type="button"
                        disabled={
                          readOnly ||
                          !canConfirm(asset) ||
                          (adopted?.kind === "project-image" &&
                            !usableImages.some(
                              (item) => item.id === adopted.id,
                            ))
                        }
                        onClick={() => confirm(asset)}
                      >
                        确认采用
                      </button>
                      <button
                        type="button"
                        disabled={
                          readOnly ||
                          asset.review !== "confirmed" ||
                          !canConfirm(asset)
                        }
                        onClick={() => share(asset)}
                      >
                        共享到项目资源库
                      </button>
                      <button
                        type="button"
                        disabled={readOnly}
                        onClick={() => update(removeAsset(value, asset.id))}
                      >
                        删除素材
                      </button>
                    </div>
                    {!canConfirm(asset) && (
                      <p className="episode-help">
                        请补全名称和描述，并选择可用素材图片后确认。
                      </p>
                    )}
                    {choiceFor === asset.id && (
                      <div
                        className="episode-share-choice"
                        role="group"
                        aria-label="重复素材处理"
                      >
                        <p>
                          项目资源库中已有同名{kindLabel[asset.kind]}
                          。请选择链接已有资源或另建资源。
                        </p>
                        <button
                          type="button"
                          disabled={readOnly}
                          onClick={() => share(asset, "link")}
                        >
                          链接已有资源
                        </button>
                        <button
                          type="button"
                          disabled={readOnly}
                          onClick={() => share(asset, "create")}
                        >
                          另建资源
                        </button>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          </section>
        ) : null,
      )}
    </>
  );
}
