import { Button } from "antd";
import {
  editShot,
  editShotVideoPrompt,
  type EpisodeWorkflow,
  type ShotItem,
} from "../../../features/projects/episode-workflow";
import {
  hasAvailableMedia,
  mediaUrl,
  type ListedMedia,
} from "../../../features/projects/episode-media";
import { ImagePreview } from "./ImagePreview";

export function ShotProductionTable({
  value,
  shot,
  readOnly,
  onChange,
  projectId,
  mediaItems,
}: {
  value: EpisodeWorkflow;
  shot: ShotItem;
  readOnly: boolean;
  onChange: (next: EpisodeWorkflow) => void;
  projectId?: string;
  mediaItems: readonly ListedMedia[];
}) {
  const frame = shot.firstFrames.find(
    (item) => item.id === shot.selectedFirstId,
  );
  const video = shot.videos.find((item) => item.id === shot.selectedVideoId);
  const videoSrc =
    projectId &&
    video?.value.kind === "project-video" &&
    hasAvailableMedia(mediaItems, video.value.id, "video/mp4")
      ? mediaUrl(projectId, video.value.id)
      : null;
  const update = (next: EpisodeWorkflow) => {
    if (!readOnly) onChange(next);
  };
  return (
    <table
      className="storyboard-production-table"
      aria-label={shot.title + "图片与视频制作"}
    >
      <tbody>
        <tr>
          <td className="storyboard-prompt">
            <label htmlFor={"storyboard-prompt-" + shot.id}>图片提示词</label>
            <textarea
              id={"storyboard-prompt-" + shot.id}
              value={shot.imagePrompt ?? ""}
              readOnly={readOnly}
              placeholder="描述画面主体、构图、光线与风格…"
              onChange={(event) =>
                update(
                  editShot(value, shot.id, { imagePrompt: event.target.value }),
                )
              }
            />
            <div className="storyboard-generation-actions">
              <Button
                type="primary"
                disabled
                aria-describedby={"storyboard-image-note-" + shot.id}
              >
                生成分镜图
              </Button>
              <p id={"storyboard-image-note-" + shot.id}>
                {readOnly ? "当前项目为只读模式" : "图片生成暂未开放"}
              </p>
            </div>
          </td>
          <td className="storyboard-output">
            <h3>分镜图</h3>
            <div
              className={
                "storyboard-image-placeholder" +
                (value.aspect === "9:16" ? " is-portrait" : "")
              }
              role={frame ? undefined : "img"}
              aria-label={frame ? undefined : "分镜图空白展示区"}
            >
              {frame && (
                <ImagePreview
                  media={frame.value}
                  label={shot.title + "分镜图"}
                  projectId={projectId}
                  mediaItems={mediaItems}
                />
              )}
            </div>
          </td>
        </tr>
        <tr>
          <td className="storyboard-prompt">
            <label htmlFor={"storyboard-video-prompt-" + shot.id}>
              视频提示词
            </label>
            <textarea
              id={"storyboard-video-prompt-" + shot.id}
              value={shot.videoPrompt ?? ""}
              readOnly={readOnly}
              placeholder="描述人物动作、镜头运动与节奏…"
              onChange={(event) =>
                update(editShotVideoPrompt(value, shot.id, event.target.value))
              }
            />
            <div className="storyboard-generation-actions">
              <Button
                type="primary"
                disabled
                aria-describedby={"storyboard-video-note-" + shot.id}
              >
                生成视频
              </Button>
              <p id={"storyboard-video-note-" + shot.id}>
                {readOnly
                  ? "当前项目为只读模式"
                  : "视频生成暂未开放，后续将使用本镜分镜图。"}
              </p>
            </div>
          </td>
          <td className="storyboard-output">
            <h3>分镜视频</h3>
            <div
              className={
                "storyboard-video-placeholder" +
                (value.aspect === "9:16" ? " is-portrait" : "")
              }
              role={video ? undefined : "img"}
              aria-label={video ? undefined : "分镜视频空白展示区"}
            >
              {videoSrc ? (
                <video
                  controls
                  preload="metadata"
                  src={videoSrc}
                  aria-label={shot.title + "分镜视频"}
                />
              ) : video ? (
                <p className="storyboard-retained-media-note">
                  {video.value.kind === "demo-motion"
                    ? "已保留旧版演示动效记录（非视频文件）"
                    : "已保留视频记录，当前媒体不可用"}
                </p>
              ) : null}
            </div>
            {video && shot.videoReview === "stale" && (
              <p className="storyboard-result-note">
                制作内容已修改，当前视频需重新核对。
              </p>
            )}
          </td>
        </tr>
      </tbody>
    </table>
  );
}
