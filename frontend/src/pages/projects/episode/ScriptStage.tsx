import React from "react";
import { AssetControls } from "./AssetControls";
import {
  DEMO_MODELS,
  sampleAssets,
} from "../../../features/projects/episode-demo";
import {
  editAsset,
  editScript,
  removeAsset,
  staleFrameReviews,
  type EpisodeWorkflow,
} from "../../../features/projects/episode-workflow";

export function ScriptStage({
  value,
  readOnly,
  onChange,
  projectAspect,
}: {
  value: EpisodeWorkflow;
  readOnly: boolean;
  onChange: (next: EpisodeWorkflow) => void;
  projectAspect?: "16:9" | "9:16";
}) {
  const currentSnapshot =
    value.reviews.script === "confirmed" &&
    value.approvedScript?.text === value.scriptDraft &&
    value.approvedScript.aspect === value.aspect &&
    value.approvedScript.style === value.style;
  function changeVisual(
    patch: Partial<Pick<EpisodeWorkflow, "aspect" | "style">>,
  ) {
    const hasAssetImages = value.assets.some(
      (item) => item.imageCandidates.length,
    );
    const hasFrames =
      value.shots.some(
        (shot) => shot.firstFrames.length || shot.endFrames.length,
      ) ||
      value.gridBatches.some((batch) => batch.cells.some((cell) => cell.ref));
    const hasVideos = value.shots.some((shot) => shot.videos.length);
    onChange({
      ...value,
      ...patch,
      assets: value.assets.map((asset) =>
        asset.imageCandidates.length ? { ...asset, review: "stale" } : asset,
      ),
      shots: value.shots.map((shot) => ({
        ...shot,
        ...staleFrameReviews(shot),
        frameReview:
          shot.firstFrames.length || shot.endFrames.length
            ? "stale"
            : shot.frameReview,
        videoReview: shot.videos.length ? "stale" : shot.videoReview,
      })),
      gridBatches: value.gridBatches.map((batch) => ({
        ...batch,
        cells: batch.cells.map((cell) =>
          cell.ref ? { ...cell, review: "stale" } : cell,
        ),
      })),
      reviews: {
        ...value.reviews,
        script: "review",
        assets: hasAssetImages ? "stale" : value.reviews.assets,
        storyboard: hasFrames ? "stale" : value.reviews.storyboard,
        video: hasVideos ? "stale" : value.reviews.video,
      },
    });
  }
  function confirmScript() {
    if (!value.scriptDraft.trim()) return;
    onChange({
      ...value,
      approvedScript: {
        text: value.scriptDraft,
        aspect: value.aspect,
        style: value.style,
      },
      reviews: { ...value.reviews, script: "confirmed" },
    });
  }
  function analyze() {
    if (!currentSnapshot) return;
    const existing = new Set(
      value.assets.map((asset) => `${asset.kind}:${asset.name}`),
    );
    const additions = sampleAssets().filter(
      (asset) => !existing.has(`${asset.kind}:${asset.name}`),
    );
    onChange({
      ...value,
      assets: [
        ...value.assets,
        ...additions.map((asset) => ({ ...asset, id: crypto.randomUUID() })),
      ],
      reviews: { ...value.reviews, assets: "review" },
    });
  }
  return (
    <>
      <div className="episode-stage-heading">
        <div>
          <h2>剧本确认与素材拆解</h2>
          <p>
            校对剧本与原文，再确认当前文字、画幅和风格；素材仅生成演示占位候选。
          </p>
        </div>
        <span>
          {currentSnapshot
            ? "当前版本已确认"
            : value.reviews.script === "stale"
              ? "需复核原文变更"
              : value.approvedScript
                ? "有待确认修改"
                : "待确认"}
        </span>
      </div>
      <details className="episode-source-compare">
        <summary>对照小说原文</summary>
        <pre>{value.novel || "尚未填写本集小说。"}</pre>
      </details>
      {value.approvedScript && (
        <details className="episode-source-compare">
          <summary>查看已确认剧本快照</summary>
          <pre>{value.approvedScript.text}</pre>
        </details>
      )}
      <label className="episode-editor-label">
        本集剧本
        <textarea
          rows={14}
          value={value.scriptDraft}
          readOnly={readOnly}
          placeholder="直接粘贴已有剧本，或选用上一阶段的演示候选"
          onChange={(event) => onChange(editScript(value, event.target.value))}
        />
      </label>
      <div className="episode-script-settings">
        <label>
          画幅比例
          <select
            value={value.aspect}
            disabled={readOnly}
            onChange={(event) =>
              changeVisual({ aspect: event.target.value as "16:9" | "9:16" })
            }
          >
            <option value="16:9">16:9 横屏</option>
            <option value="9:16">9:16 竖屏</option>
          </select>
        </label>
        <label>
          视觉风格
          <input
            value={value.style}
            readOnly={readOnly}
            placeholder="例如：写实、国风"
            onChange={(event) => changeVisual({ style: event.target.value })}
          />
        </label>
        <label>
          素材分析模型
          <select
            value={value.models.analysis}
            disabled={readOnly}
            onChange={(event) =>
              onChange({
                ...value,
                models: { ...value.models, analysis: event.target.value },
              })
            }
          >
            <option
              value={value.models.analysis}
              hidden={
                !DEMO_MODELS.analysis.some(
                  (item) => item.value === value.models.analysis,
                )
              }
            >
              {value.models.analysis}
            </option>
            {DEMO_MODELS.analysis
              .filter((item) => item.value !== value.models.analysis)
              .map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
          </select>
        </label>
      </div>
      {projectAspect && projectAspect !== value.aspect && (
        <p className="episode-help">
          本集画幅与项目设置不同；后续画面需保持本集画幅一致。
        </p>
      )}
      <div className="episode-stage-controls">
        {!currentSnapshot ? (
          <button
            className="episode-primary-action"
            type="button"
            disabled={readOnly || !value.scriptDraft.trim()}
            onClick={confirmScript}
          >
            确认剧本
          </button>
        ) : (
          <button
            className="episode-primary-action"
            type="button"
            disabled={readOnly}
            onClick={analyze}
          >
            演示分析素材
          </button>
        )}
      </div>
      <AssetControls value={value} readOnly={readOnly} onChange={onChange} />
      {value.assets.length > 0 && (
        <div className="episode-candidates">
          <h3>素材候选 · 请人工核对</h3>
          <div className="episode-asset-list">
            {value.assets.map((asset) => (
              <article key={asset.id} className="episode-candidate">
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
                <button
                  type="button"
                  disabled={readOnly}
                  onClick={() => onChange(removeAsset(value, asset.id))}
                >
                  删除素材
                </button>
                <span>
                  {
                    (
                      {
                        character: "角色",
                        scene: "场景",
                        prop: "道具",
                      } as const
                    )[asset.kind]
                  }{" "}
                  · {asset.review === "stale" ? "需复核" : "演示候选"}
                </span>
                <label>
                  名称
                  <input
                    value={asset.name}
                    readOnly={readOnly}
                    onChange={(event) =>
                      onChange(
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
                      onChange(
                        editAsset(value, asset.id, {
                          description: event.target.value,
                        }),
                      )
                    }
                  />
                </label>
              </article>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
