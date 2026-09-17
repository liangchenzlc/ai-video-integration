import type { Media } from "../../electron/shared/media";
import type { Draft } from "../../electron/shared/drafts";
import {
  duplicateMusicClip,
  ids,
  newClip,
  newTrack,
  number,
  patch,
  rows,
  uid,
  word,
  type Content,
  type ProductionKind,
  type Row,
} from "./production-fields";

type Option = { id: string; label: string };
type Props = {
  kind: ProductionKind;
  projectId: string;
  content: Content;
  disabled: boolean;
  media: Media[];
  dialogues: Option[];
  speeches: Option[];
  shots: Option[];
  onEdit: (content: Draft["content"]["content"]) => void;
  onTimelinePreview: (
    action: "move" | "split" | "trim",
    clipId: string,
    change: Row,
  ) => void;
};
const trackNames: Record<string, string> = {
  image: "画面",
  video: "视频",
  voice: "对白",
  music: "音乐",
  sfx: "音效",
  subtitle: "字幕",
};
const mediaLabel = (item: Media) =>
  `${item.mime.startsWith("audio") ? "声音" : item.mime.startsWith("video") ? "视频" : "图片"} · ${item.id.slice(0, 8)}${item.durationMs ? ` · ${(item.durationMs / 1000).toFixed(1)}秒` : ""}`;

function N({
  label,
  value,
  min = 0,
  max,
  onChange,
  disabled,
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  onChange: (next: number) => void;
  disabled: boolean;
}) {
  return (
    <label>
      {label}
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        disabled={disabled}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (
            Number.isSafeInteger(next) &&
            next >= min &&
            (max === undefined || next <= max)
          )
            onChange(next);
        }}
      />
    </label>
  );
}

function Select({
  label,
  value,
  options,
  onChange,
  disabled,
  empty = "请选择",
}: {
  label: string;
  value: string;
  options: Option[];
  empty?: string;
  onChange: (next: string) => void;
  disabled: boolean;
}) {
  return (
    <label>
      {label}
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{empty}</option>
        {options.map((item) => (
          <option key={item.id} value={item.id}>
            {item.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function timeRangeFields(
  list: Row[],
  disabled: boolean,
  update: (next: Row[]) => void,
  name: string,
) {
  return (
    <div className="production-range-list">
      {list.map((range, i) => (
        <div className="form-row" key={i}>
          <N
            label={`${name}开始（毫秒）`}
            value={number(range.startMs)}
            disabled={disabled}
            onChange={(next) => update(patch(list, i, { startMs: next }))}
          />
          <N
            label={`${name}结束（毫秒）`}
            value={number(range.endMs, 1000)}
            min={1}
            disabled={disabled}
            onChange={(next) => update(patch(list, i, { endMs: next }))}
          />
          <button
            type="button"
            disabled={disabled}
            onClick={() => update(list.filter((_, j) => i !== j))}
          >
            移除
          </button>
        </div>
      ))}
      <button
        type="button"
        disabled={disabled}
        onClick={() => update([...list, { startMs: 0, endMs: 1000 }])}
      >
        添加区间
      </button>
    </div>
  );
}

export function ProductionFields(props: Props) {
  const {
    kind,
    content,
    disabled,
    media,
    dialogues,
    speeches,
    shots,
    onEdit,
    onTimelinePreview,
  } = props;
  const edit = (key: string, value: unknown) =>
    onEdit({ ...content, [key]: value } as Content);
  const available = media.filter((m) => m.availability === "available");
  const mediaOptions = available.map((m) => ({
    id: m.id,
    label: mediaLabel(m),
  }));
  const audio = available
    .filter((m) => m.mime.startsWith("audio/"))
    .map((m) => ({ id: m.id, label: mediaLabel(m) }));
  if (kind === "speech")
    return (
      <div className="production-fields">
        <p className="muted">
          台词和音频分开保存；容量以录音全长计算，发声区间只定位嘴型与字幕。
        </p>
        <div className="form-row">
          <Select
            label="对应对白"
            value={word(content.dialogueId)}
            options={dialogues}
            disabled={disabled}
            onChange={(value) => edit("dialogueId", value || undefined)}
          />
          <Select
            label="已导入的录音"
            value={word(content.mediaId)}
            options={audio}
            disabled={disabled}
            onChange={(value) => {
              const selected = media.find((m) => m.id === value);
              onEdit({
                ...content,
                mediaId: value || undefined,
                measuredMs: selected?.durationMs ?? undefined,
              } as Content);
            }}
          />
        </div>
        <label>
          原台词
          <input
            value={word(content.text)}
            maxLength={2000}
            disabled={disabled}
            onChange={(e) => edit("text", e.target.value)}
          />
        </label>
        <div className="form-row">
          <N
            label="实测录音全长（毫秒）"
            value={number(content.measuredMs)}
            min={1}
            disabled={disabled}
            onChange={(value) => edit("measuredMs", value)}
          />
          <label>
            时间依据
            <select
              value={word(content.timingMethod) || "manual"}
              disabled={disabled}
              onChange={(e) => edit("timingMethod", e.target.value)}
            >
              <option value="manual">手动校准</option>
              <option value="provider_sentence">句级时间</option>
              <option value="provider_word">词级时间（仅有证据时）</option>
              <option value="estimated">估算，不能代替实测</option>
            </select>
          </label>
        </div>
        <div className="form-row">
          <label>
            音色预设
            <input
              value={word(content.voicePreset)}
              maxLength={200}
              disabled={disabled}
              onChange={(e) => edit("voicePreset", e.target.value)}
            />
          </label>
          <label>
            发音与停顿说明
            <input
              value={word(content.pronunciationNotes)}
              maxLength={2000}
              disabled={disabled}
              onChange={(e) => edit("pronunciationNotes", e.target.value)}
            />
          </label>
        </div>
        <h4>实际发声区间</h4>
        {timeRangeFields(
          rows(content.voicedRanges),
          disabled,
          (value) => edit("voicedRanges", value),
          "发声",
        )}
      </div>
    );

  if (kind === "subtitle") {
    const cues = rows(content.cues);
    return (
      <div className="production-fields">
        <p className="muted">
          字幕可独立改字；改字不会回写配音原句。没有可靠词级时间时选择手动或句级。
        </p>
        <div className="form-row">
          <Select
            label="对应已采用录音版本"
            value={word(content.audioRevisionId)}
            options={speeches}
            disabled={disabled}
            onChange={(value) => edit("audioRevisionId", value || null)}
          />
          <label>
            字幕定位依据
            <select
              value={word(content.timingMethod) || "manual"}
              disabled={disabled}
              onChange={(e) => edit("timingMethod", e.target.value)}
            >
              <option value="manual">手动</option>
              <option value="provider_sentence">句级</option>
              <option value="provider_word">词级</option>
              <option value="estimated">估算</option>
            </select>
          </label>
        </div>
        <h4>字幕句段</h4>
        {cues.map((cue, i) => {
          const time =
            cue.time && typeof cue.time === "object" ? (cue.time as Row) : {};
          return (
            <div className="production-cue" key={word(cue.id) || i}>
              <div className="form-row">
                <Select
                  label={`句段 ${i + 1} 对白`}
                  value={word(cue.dialogueId)}
                  options={dialogues}
                  disabled={disabled}
                  onChange={(value) =>
                    edit("cues", patch(cues, i, { dialogueId: value || null }))
                  }
                />
                <label>
                  字幕文字
                  <input
                    value={word(cue.text)}
                    maxLength={500}
                    disabled={disabled}
                    onChange={(e) =>
                      edit("cues", patch(cues, i, { text: e.target.value }))
                    }
                  />
                </label>
              </div>
              <div className="form-row">
                <N
                  label="入点（毫秒）"
                  value={number(time.startMs)}
                  disabled={disabled}
                  onChange={(v) =>
                    edit(
                      "cues",
                      patch(cues, i, { time: { ...time, startMs: v } }),
                    )
                  }
                />
                <N
                  label="出点（毫秒）"
                  value={number(time.endMs, 1000)}
                  min={1}
                  disabled={disabled}
                  onChange={(v) =>
                    edit(
                      "cues",
                      patch(cues, i, { time: { ...time, endMs: v } }),
                    )
                  }
                />
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() =>
                    edit(
                      "cues",
                      cues.filter((_, j) => j !== i),
                    )
                  }
                >
                  移除句段
                </button>
              </div>
              <label className="check-option">
                <input
                  type="checkbox"
                  disabled={disabled}
                  checked={cue.differsFromDialogue === true}
                  onChange={(e) =>
                    edit(
                      "cues",
                      patch(cues, i, { differsFromDialogue: e.target.checked }),
                    )
                  }
                />
                与原台词不同，需核对
              </label>
            </div>
          );
        })}
        <button
          type="button"
          disabled={disabled}
          onClick={() =>
            edit("cues", [
              ...cues,
              {
                id: uid(),
                dialogueId: null,
                text: "",
                time: { startMs: 0, endMs: 1000 },
                differsFromDialogue: false,
              },
            ])
          }
        >
          添加字幕句段
        </button>
      </div>
    );
  }

  if (kind === "observation") {
    const problems = rows(content.problems);
    return (
      <div className="production-fields">
        <p className="muted">
          标出真正看过和可用的原片区间；只看抽帧不能把整段标为通过。
        </p>
        <Select
          label="原片视频"
          value={word(content.mediaId)}
          options={available
            .filter((m) => m.mime === "video/mp4")
            .map((m) => ({ id: m.id, label: mediaLabel(m) }))}
          disabled={disabled}
          onChange={(value) => {
            const selected = media.find((m) => m.id === value);
            onEdit({
              ...content,
              mediaId: value || undefined,
              mediaHash: selected?.sha256 ?? undefined,
            } as Content);
          }}
        />
        {!!word(content.mediaId) && (
          <video
            controls
            preload="metadata"
            src={`avi-media://local/${props.projectId}/${word(content.mediaId)}`}
          />
        )}
        <h4>实际观看区间</h4>
        {timeRangeFields(
          rows(content.observed),
          disabled,
          (v) => edit("observed", v),
          "观看",
        )}
        <h4>可用区间</h4>
        {timeRangeFields(
          rows(content.usable),
          disabled,
          (v) => edit("usable", v),
          "可用",
        )}
        <h4>发现的问题</h4>
        {problems.map((item, i) => (
          <div className="production-cue" key={i}>
            <label>
              问题说明
              <input
                value={word(item.text)}
                maxLength={2000}
                disabled={disabled}
                onChange={(e) =>
                  edit("problems", patch(problems, i, { text: e.target.value }))
                }
              />
            </label>
            {timeRangeFields(
              item.time && typeof item.time === "object"
                ? [item.time as Row]
                : [],
              disabled,
              (v) => edit("problems", patch(problems, i, { time: v[0] })),
              "问题",
            )}
            <button
              type="button"
              disabled={disabled}
              onClick={() =>
                edit(
                  "problems",
                  problems.filter((_, j) => i !== j),
                )
              }
            >
              移除问题
            </button>
          </div>
        ))}
        <button
          type="button"
          disabled={disabled}
          onClick={() =>
            edit("problems", [
              ...problems,
              { time: { startMs: 0, endMs: 1000 }, text: "" },
            ])
          }
        >
          记录问题
        </button>
        <label>
          未检查范围与限制
          <textarea
            value={word(content.limitations)}
            maxLength={4000}
            disabled={disabled}
            onChange={(e) => edit("limitations", e.target.value)}
          />
        </label>
      </div>
    );
  }

  const tracks = rows(content.tracks);
  const clips = rows(content.clips);
  const transitions = rows(content.transitions);
  const fps =
    content.fps && typeof content.fps === "object" ? (content.fps as Row) : {};
  return (
    <div className="production-fields production-timeline">
      <div className="form-row">
        <label>
          画幅
          <select
            value={`${number(content.width, 1920)}x${number(content.height, 1080)}`}
            disabled={disabled}
            onChange={(e) => {
              const [width, height] = e.target.value.split("x").map(Number);
              onEdit({ ...content, width, height } as Content);
            }}
          >
            <option value="1920x1080">横屏 1080p</option>
            <option value="1080x1920">竖屏 1080p</option>
            <option value="1280x720">横屏 720p</option>
            <option value="720x1280">竖屏 720p</option>
          </select>
        </label>
        <label>
          帧率
          <select
            value={number(fps.numerator, 24)}
            disabled={disabled}
            onChange={(e) =>
              edit("fps", { numerator: Number(e.target.value), denominator: 1 })
            }
          >
            {[24, 25, 30].map((rate) => (
              <option key={rate} value={rate}>
                {rate} 帧/秒
              </option>
            ))}
          </select>
        </label>
        <N
          label="项目时长（毫秒）"
          value={number(content.durationMs, 30000)}
          min={1}
          disabled={disabled}
          onChange={(v) => edit("durationMs", v)}
        />
        <label className="check-option">
          <input
            type="checkbox"
            disabled={disabled}
            checked={content.burnSubtitles !== false}
            onChange={(e) => edit("burnSubtitles", e.target.checked)}
          />
          烧录后期字幕
        </label>
      </div>
      <div className="production-track-add">
        <h4>轨道与片段</h4>
        <label>
          添加轨道
          <select
            id="production-track-kind"
            defaultValue="video"
            disabled={disabled}
          >
            {Object.entries(trackNames).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={disabled || tracks.length >= 100}
          onClick={() => {
            const kind = (
              document.getElementById(
                "production-track-kind",
              ) as HTMLSelectElement
            ).value;
            edit("tracks", [...tracks, newTrack(kind, tracks.length)]);
          }}
        >
          添加轨道
        </button>
      </div>
      {tracks.map((track, t) => (
        <section className="production-track" key={word(track.id) || t}>
          <div className="section-heading">
            <h5>
              {trackNames[word(track.kind)] || "轨道"} · {t + 1}
            </h5>
            <label className="check-option">
              <input
                type="checkbox"
                disabled={disabled}
                checked={track.muted === true}
                onChange={(e) =>
                  edit("tracks", patch(tracks, t, { muted: e.target.checked }))
                }
              />
              静音
            </label>
            <button
              type="button"
              disabled={
                disabled || clips.some((clip) => clip.trackId === track.id)
              }
              onClick={() =>
                edit(
                  "tracks",
                  tracks.filter((_, i) => i !== t),
                )
              }
            >
              移除空轨道
            </button>
          </div>
          {clips.map((clip, i) =>
            clip.trackId !== track.id ? null : (
              <ClipRow
                key={word(clip.id) || i}
                clip={clip}
                index={i}
                clips={clips}
                disabled={disabled}
                media={mediaOptions}
                shots={shots}
                onUpdate={(change) => edit("clips", patch(clips, i, change))}
                onRemove={() =>
                  edit(
                    "clips",
                    clips.filter((_, j) => i !== j),
                  )
                }
                onPreview={(action, change) =>
                  onTimelinePreview(action, word(clip.id), change)
                }
                onLoop={
                  word(track.kind) !== "music"
                    ? undefined
                    : () => edit("clips", [...clips, duplicateMusicClip(clip)])
                }
              />
            ),
          )}
          <button
            type="button"
            disabled={disabled || clips.length >= 5000}
            onClick={() =>
              edit("clips", [...clips, newClip(word(track.id), 3000)])
            }
          >
            添加片段
          </button>
        </section>
      ))}
      <h4>转场</h4>
      {transitions.map((transition, i) => (
        <div className="form-row" key={word(transition.id) || i}>
          <Select
            label="前一片段"
            value={word(transition.fromClipId)}
            options={clips.map((c, n) => ({
              id: word(c.id),
              label: `片段 ${n + 1}`,
            }))}
            disabled={disabled}
            onChange={(v) =>
              edit("transitions", patch(transitions, i, { fromClipId: v }))
            }
          />
          <Select
            label="后一片段"
            value={word(transition.toClipId)}
            options={clips.map((c, n) => ({
              id: word(c.id),
              label: `片段 ${n + 1}`,
            }))}
            disabled={disabled}
            onChange={(v) =>
              edit("transitions", patch(transitions, i, { toClipId: v }))
            }
          />
          <label>
            方式
            <select
              value={word(transition.type) || "cut"}
              disabled={disabled}
              onChange={(e) =>
                edit(
                  "transitions",
                  patch(transitions, i, { type: e.target.value }),
                )
              }
            >
              <option value="cut">硬切</option>
              <option value="dissolve">叠化</option>
              <option value="fade">淡入淡出</option>
            </select>
          </label>
          <N
            label="时长（毫秒）"
            value={number(transition.durationMs)}
            disabled={disabled}
            onChange={(v) =>
              edit("transitions", patch(transitions, i, { durationMs: v }))
            }
          />
          <button
            type="button"
            disabled={disabled}
            onClick={() =>
              edit(
                "transitions",
                transitions.filter((_, j) => i !== j),
              )
            }
          >
            移除
          </button>
        </div>
      ))}
      <button
        type="button"
        disabled={disabled || clips.length < 2}
        onClick={() =>
          edit("transitions", [
            ...transitions,
            {
              id: uid(),
              fromClipId: word(clips[0].id),
              toClipId: word(clips[1].id),
              type: "cut",
              durationMs: 0,
            },
          ])
        }
      >
        添加转场
      </button>
    </div>
  );
}

function ClipRow({
  clip,
  index,
  clips,
  disabled,
  media,
  shots,
  onUpdate,
  onRemove,
  onPreview,
  onLoop,
}: {
  clip: Row;
  index: number;
  clips: Row[];
  disabled: boolean;
  media: Option[];
  shots: Option[];
  onUpdate: (change: Row) => void;
  onRemove: () => void;
  onPreview: (action: "move" | "split" | "trim", change: Row) => void;
  onLoop?: () => void;
}) {
  const keys = rows(clip.keyframes);
  return (
    <div className="production-clip">
      <div className="section-heading">
        <h6>片段 {index + 1}</h6>
        <span>{word(clip.id).slice(0, 8)}</span>
        <button type="button" disabled={disabled} onClick={onRemove}>
          移除片段
        </button>
      </div>
      <div className="form-row">
        <Select
          label="镜头"
          value={word(clip.shotId)}
          options={shots}
          disabled={disabled}
          onChange={(v) => onUpdate({ shotId: v || null })}
        />
        <Select
          label="素材"
          value={word(clip.mediaId)}
          options={media}
          disabled={disabled}
          onChange={(v) => onUpdate({ mediaId: v || null })}
        />
        <N
          label="时间线起点"
          value={number(clip.startMs)}
          disabled={disabled}
          onChange={(v) => onUpdate({ startMs: v })}
        />
        <N
          label="显示时长"
          value={number(clip.durationMs, 3000)}
          min={1}
          disabled={disabled}
          onChange={(v) => onUpdate({ durationMs: v })}
        />
      </div>
      <div className="form-row">
        <N
          label="原件入点"
          value={number(clip.inMs)}
          disabled={disabled}
          onChange={(v) => onUpdate({ inMs: v })}
        />
        <N
          label="原件出点"
          value={number(clip.outMs, 3000)}
          min={1}
          disabled={disabled}
          onChange={(v) => onUpdate({ outMs: v })}
        />
        <N
          label="轨道增益 dB"
          value={number(clip.gainDb)}
          min={-96}
          max={12}
          disabled={disabled}
          onChange={(v) => onUpdate({ gainDb: v })}
        />
        <button
          type="button"
          disabled={disabled}
          onClick={() => onPreview("move", { startMs: number(clip.startMs) })}
        >
          预览移动影响
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={() =>
            onPreview("trim", {
              inMs: number(clip.inMs),
              outMs: number(clip.outMs),
              durationMs: number(clip.durationMs),
            })
          }
        >
          预览裁切影响
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={() =>
            onPreview("split", {
              splitMs:
                number(clip.startMs) + Math.floor(number(clip.durationMs) / 2),
            })
          }
        >
          预览从中间分割
        </button>
        {onLoop && (
          <button type="button" disabled={disabled} onClick={onLoop}>
            显式复制音乐循环
          </button>
        )}
      </div>
      <details>
        <summary>关联片段与关键帧</summary>
        {clips
          .filter((c) => c.id !== clip.id)
          .map((other, i) => (
            <label className="check-option" key={word(other.id) || i}>
              <input
                type="checkbox"
                disabled={disabled}
                checked={ids(clip.linkedClipIds).includes(word(other.id))}
                onChange={(e) =>
                  onUpdate({
                    linkedClipIds: e.target.checked
                      ? [...ids(clip.linkedClipIds), word(other.id)]
                      : ids(clip.linkedClipIds).filter((id) => id !== other.id),
                  })
                }
              />
              关联片段 {clips.indexOf(other) + 1}
            </label>
          ))}
        {keys.map((key, i) => (
          <div className="form-row" key={i}>
            <label>
              属性
              <select
                value={word(key.property) || "opacity"}
                disabled={disabled}
                onChange={(e) =>
                  onUpdate({
                    keyframes: patch(keys, i, { property: e.target.value }),
                  })
                }
              >
                {["x", "y", "scale", "opacity", "volume"].map((p) => (
                  <option value={p} key={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
            <N
              label="片段内时间"
              value={number(key.timeMs)}
              disabled={disabled}
              onChange={(v) =>
                onUpdate({ keyframes: patch(keys, i, { timeMs: v }) })
              }
            />
            <N
              label="数值"
              value={number(key.value, 1)}
              min={-10000}
              max={10000}
              disabled={disabled}
              onChange={(v) =>
                onUpdate({ keyframes: patch(keys, i, { value: v }) })
              }
            />
            <label>
              插值
              <select
                value={word(key.interpolation) || "linear"}
                disabled={disabled}
                onChange={(e) =>
                  onUpdate({
                    keyframes: patch(keys, i, {
                      interpolation: e.target.value,
                    }),
                  })
                }
              >
                <option value="linear">线性</option>
                <option value="hold">保持</option>
              </select>
            </label>
            <button
              type="button"
              disabled={disabled}
              onClick={() =>
                onUpdate({ keyframes: keys.filter((_, j) => j !== i) })
              }
            >
              移除
            </button>
          </div>
        ))}
        <button
          type="button"
          disabled={disabled}
          onClick={() =>
            onUpdate({
              keyframes: [
                ...keys,
                {
                  timeMs: 0,
                  property: "opacity",
                  value: 1,
                  interpolation: "linear",
                },
              ],
            })
          }
        >
          添加关键帧
        </button>
      </details>
    </div>
  );
}
