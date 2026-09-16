import type { DraftSaveState } from "./draft-autosave";
import type { Media } from "../../electron/shared/media";
import type { Draft } from "../../electron/shared/drafts";
import {
  entries,
  replaceAt,
  strings,
  uuid,
  value,
  type Entry,
} from "./storyboard-fields";

export function ContentFields({
  kind,
  state,
  readOnly,
  media,
  shots,
  projectId,
  options,
  onEdit,
}: {
  kind: "asset" | "shot";
  state: DraftSaveState;
  readOnly: boolean;
  media: Media[];
  shots: string[];
  projectId: string;
  options: {
    scenes: { id: string; label: string }[];
    requirements: { id: string; label: string }[];
    dialogues: { id: string; label: string }[];
    assets: { id: string; label: string }[];
  };
  onEdit: (next: Draft["content"]["content"]) => void;
}) {
  const content = state.content;
  const edit = (field: string, next: unknown) => {
    if (readOnly) return;
    const updated = { ...content, [field]: next };
    // Any content change invalidates the previous purpose assessment locally too.
    updated.references = entries(updated.references).map((reference) =>
      reference.state === "verified"
        ? { ...reference, state: "pending" }
        : reference,
    );
    onEdit(updated as Draft["content"]["content"]);
  };
  const patch = (field: string, rows: Entry[], i: number, values: Entry) =>
    edit(field, replaceAt(rows, i, { ...rows[i], ...values }));
  const refs = entries(content.references);
  const multi = (field: string, options: { id: string; label: string }[]) => (
    <fieldset>
      <legend>
        {field === "requirementIds"
          ? "承载的要求"
          : field === "assetRevisionIds"
            ? "采用的资产版本"
            : "关联对白"}
      </legend>
      {options.length ? (
        options.map((option) => (
          <label className="check-option" key={option.id}>
            <input
              type="checkbox"
              disabled={readOnly}
              checked={strings(content[field]).includes(option.id)}
              onChange={(e) =>
                edit(
                  field,
                  e.target.checked
                    ? [...strings(content[field]), option.id]
                    : strings(content[field]).filter((id) => id !== option.id),
                )
              }
            />
            {option.label}
          </label>
        ))
      ) : (
        <p className="muted">先在故事或版本区准备对应内容。</p>
      )}
    </fieldset>
  );
  return (
    <div className="content-fields">
      {kind === "asset" ? (
        <>
          <div className="form-row">
            <label>
              资产名称
              <input
                value={value(content.name)}
                readOnly={readOnly}
                onChange={(e) => edit("name", e.target.value)}
              />
            </label>
            <label>
              类别
              <select
                disabled={readOnly}
                value={value(content.assetType) || "character"}
                onChange={(e) => edit("assetType", e.target.value)}
              >
                <option value="character">角色</option>
                <option value="location">场景</option>
                <option value="prop">道具</option>
                <option value="style">风格</option>
              </select>
            </label>
          </div>
          {[
            ["identityAnchors", "身份锚点"],
            ["allowedChanges", "允许变化"],
          ].map(([field, label]) => (
            <section key={field}>
              <h4>{label}</h4>
              {strings(content[field]).map((line, i, rows) => (
                <div className="workbench-line" key={i}>
                  <input
                    aria-label={`${label} ${i + 1}`}
                    value={line}
                    readOnly={readOnly}
                    onChange={(e) =>
                      edit(field, replaceAt(rows, i, e.target.value))
                    }
                  />
                  <button
                    disabled={readOnly}
                    onClick={() =>
                      edit(
                        field,
                        rows.filter((_, n) => n !== i),
                      )
                    }
                  >
                    移除
                  </button>
                </div>
              ))}
              <button
                disabled={readOnly}
                onClick={() => edit(field, [...strings(content[field]), ""])}
              >
                添加{label}
              </button>
            </section>
          ))}
          <section>
            <h4>持续状态</h4>
            {entries(content.states).map((row, i, rows) => (
              <div className="workbench-entry" key={value(row.id) || i}>
                <label>
                  状态描述
                  <input
                    value={value(row.description)}
                    readOnly={readOnly}
                    onChange={(e) =>
                      patch("states", rows, i, { description: e.target.value })
                    }
                  />
                </label>
                <label>
                  变化原因
                  <input
                    value={value(row.reason)}
                    readOnly={readOnly}
                    onChange={(e) =>
                      patch("states", rows, i, { reason: e.target.value })
                    }
                  />
                </label>
                <div className="form-row">
                  <label>
                    从镜头
                    <select
                      disabled={readOnly}
                      value={value(row.fromShotId)}
                      onChange={(e) =>
                        patch("states", rows, i, { fromShotId: e.target.value })
                      }
                    >
                      <option value="">选择镜头</option>
                      {shots.map((id, n) => (
                        <option value={id} key={id}>
                          镜头 {n + 1}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    到镜头
                    <select
                      disabled={readOnly}
                      value={value(row.throughShotId)}
                      onChange={(e) =>
                        patch("states", rows, i, {
                          throughShotId: e.target.value,
                        })
                      }
                    >
                      <option value="">选择镜头</option>
                      {shots.map((id, n) => (
                        <option value={id} key={id}>
                          镜头 {n + 1}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <button
                  disabled={readOnly}
                  onClick={() =>
                    edit(
                      "states",
                      rows.filter((_, n) => n !== i),
                    )
                  }
                >
                  移除状态
                </button>
              </div>
            ))}
            <button
              disabled={readOnly || !shots.length}
              onClick={() =>
                edit("states", [
                  ...entries(content.states),
                  {
                    id: uuid(),
                    description: "",
                    reason: "",
                    fromShotId: shots[0],
                    throughShotId: shots[0],
                  },
                ])
              }
            >
              添加持续状态
            </button>
          </section>
        </>
      ) : (
        <>
          <label>
            观看目的
            <textarea
              value={value(content.purpose)}
              readOnly={readOnly}
              onChange={(e) => edit("purpose", e.target.value)}
            />
          </label>
          <div className="form-row">
            <label>
              所属场景
              <select
                disabled={readOnly}
                value={value(content.sceneId)}
                onChange={(e) => edit("sceneId", e.target.value)}
              >
                <option value="">选择分场</option>
                {options.scenes.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              镜头用途
              <select
                disabled={readOnly}
                value={value(content.use) || "original"}
                onChange={(e) => edit("use", e.target.value)}
              >
                <option value="original">原镜头</option>
                <option value="supplement">补拍</option>
                <option value="alternate">备选</option>
              </select>
            </label>
          </div>
          {content.use !== "original" && (
            <label>
              归属原镜
              <select
                disabled={readOnly}
                value={value(content.pickupOfShotId)}
                onChange={(e) => edit("pickupOfShotId", e.target.value || null)}
              >
                <option value="">选择原镜</option>
                {shots
                  .filter((id) => id !== content.shotId)
                  .map((id, n) => (
                    <option value={id} key={id}>
                      镜头 {n + 1}
                    </option>
                  ))}
              </select>
            </label>
          )}
          <div className="form-row">
            <label>
              起点
              <textarea
                value={value(content.startState)}
                readOnly={readOnly}
                onChange={(e) => edit("startState", e.target.value)}
              />
            </label>
            <label>
              终点
              <textarea
                value={value(content.endState)}
                readOnly={readOnly}
                onChange={(e) => edit("endState", e.target.value)}
              />
            </label>
          </div>
          <div className="form-row">
            <label>
              摄影安排
              <textarea
                value={value(content.camera)}
                readOnly={readOnly}
                onChange={(e) => edit("camera", e.target.value)}
              />
            </label>
            <label>
              主体用手
              <select
                disabled={readOnly}
                value={value(content.subjectHand) || "none"}
                onChange={(e) => edit("subjectHand", e.target.value)}
              >
                <option value="none">无</option>
                <option value="left">左手</option>
                <option value="right">右手</option>
                <option value="both">双手</option>
              </select>
            </label>
            <label>
              计划时长（秒）
              <input
                type="number"
                min="0.001"
                step="0.001"
                value={Number(content.plannedMs || 1000) / 1000}
                readOnly={readOnly}
                onChange={(e) =>
                  edit("plannedMs", Math.round(Number(e.target.value) * 1000))
                }
              />
            </label>
          </div>
          <section>
            <h4>镜头事件</h4>
            {entries(content.events).map((row, i, rows) => (
              <div className="workbench-entry" key={value(row.id) || i}>
                <label>
                  发生了什么
                  <input
                    value={value(row.text)}
                    readOnly={readOnly}
                    onChange={(e) =>
                      patch("events", rows, i, { text: e.target.value })
                    }
                  />
                </label>
                <div className="form-row">
                  <label>
                    开始（秒）
                    <input
                      type="number"
                      min="0"
                      step="0.001"
                      value={Number((row.time as Entry)?.startMs || 0) / 1000}
                      readOnly={readOnly}
                      onChange={(e) =>
                        patch("events", rows, i, {
                          time: {
                            ...(row.time as Entry),
                            startMs: Math.round(Number(e.target.value) * 1000),
                          },
                        })
                      }
                    />
                  </label>
                  <label>
                    结束（秒）
                    <input
                      type="number"
                      min="0.001"
                      step="0.001"
                      value={Number((row.time as Entry)?.endMs || 1000) / 1000}
                      readOnly={readOnly}
                      onChange={(e) =>
                        patch("events", rows, i, {
                          time: {
                            ...(row.time as Entry),
                            endMs: Math.round(Number(e.target.value) * 1000),
                          },
                        })
                      }
                    />
                  </label>
                  <label>
                    载体
                    <select
                      disabled={readOnly}
                      value={value(row.carrier) || "visual"}
                      onChange={(e) =>
                        patch("events", rows, i, { carrier: e.target.value })
                      }
                    >
                      <option value="visual">画面</option>
                      <option value="audio">声音</option>
                      <option value="subtitle">字幕</option>
                      <option value="screenText">画内文字</option>
                    </select>
                  </label>
                  <label>
                    观察方
                    <select
                      disabled={readOnly}
                      value={value(row.observer) || "audience"}
                      onChange={(e) =>
                        patch("events", rows, i, { observer: e.target.value })
                      }
                    >
                      <option value="physical">物理存在</option>
                      <option value="character">角色知道</option>
                      <option value="audience">观众看见</option>
                    </select>
                  </label>
                </div>
                <fieldset>
                  <legend>此事件承载的要求</legend>
                  {options.requirements.map((r) => (
                    <label className="check-option" key={r.id}>
                      <input
                        type="checkbox"
                        disabled={readOnly}
                        checked={strings(row.requirementIds).includes(r.id)}
                        onChange={(e) =>
                          patch("events", rows, i, {
                            requirementIds: e.target.checked
                              ? [...strings(row.requirementIds), r.id]
                              : strings(row.requirementIds).filter(
                                  (id) => id !== r.id,
                                ),
                          })
                        }
                      />
                      {r.label}
                    </label>
                  ))}
                </fieldset>
                <button
                  disabled={readOnly}
                  onClick={() =>
                    edit(
                      "events",
                      rows.filter((_, n) => n !== i),
                    )
                  }
                >
                  移除事件
                </button>
              </div>
            ))}
            <button
              disabled={readOnly}
              onClick={() =>
                edit("events", [
                  ...entries(content.events),
                  {
                    id: uuid(),
                    text: "",
                    time: { startMs: 0, endMs: 1000 },
                    requirementIds: [],
                    carrier: "visual",
                    observer: "audience",
                  },
                ])
              }
            >
              添加事件
            </button>
            <p className="muted">
              物理存在不代表观众已看见；覆盖由已采用版本与观察方共同判定。
            </p>
          </section>
          {multi("requirementIds", options.requirements)}
          {multi("dialogueIds", options.dialogues)}
          {multi("assetRevisionIds", options.assets)}
        </>
      )}
      <section>
        <h4>真实素材参考</h4>
        {refs.map((row, i) => (
          <div className="workbench-entry" key={`${value(row.mediaId)}-${i}`}>
            {media
              .find((m) => m.id === row.mediaId)
              ?.mime.startsWith("image/") && (
              <img
                className="reference-thumb"
                src={`avi-media://local/${projectId}/${value(row.mediaId)}`}
                alt="所选素材缩略图"
              />
            )}
            <div className="form-row">
              <label>
                素材
                <select
                  disabled={readOnly}
                  value={value(row.mediaId)}
                  onChange={(e) => {
                    const selected = media.find((m) => m.id === e.target.value);
                    patch("references", refs, i, {
                      mediaId: e.target.value,
                      mediaHash: selected?.sha256 ?? "",
                      state: "pending",
                    });
                  }}
                >
                  <option value="">选择真实素材</option>
                  {media.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.mime} · {m.id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                用途
                <select
                  disabled={readOnly}
                  value={value(row.role) || "identity"}
                  onChange={(e) =>
                    patch("references", refs, i, {
                      role: e.target.value,
                      state: "pending",
                    })
                  }
                >
                  {[
                    ["identity", "身份"],
                    ["style", "风格"],
                    ["location", "地点"],
                    ["prop", "道具"],
                    ["composition", "构图"],
                    ["firstFrame", "首帧"],
                    ["keyMoment", "关键时刻"],
                    ["endFrame", "末帧"],
                    ["voiceDrive", "声音驱动"],
                    ["voiceReference", "声音参考"],
                  ].map(([id, label]) => (
                    <option value={id} key={id}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <p className="muted">核对状态：{value(row.state) || "待核对"}</p>
            <button
              disabled={readOnly}
              onClick={() =>
                edit(
                  "references",
                  refs
                    .filter((_, n) => n !== i)
                    .map((r, n) => ({ ...r, order: n })),
                )
              }
            >
              移除参考
            </button>
          </div>
        ))}
        <button
          disabled={readOnly || !media.length || refs.length >= 16}
          onClick={() =>
            edit("references", [
              ...refs,
              {
                mediaId: media[0].id,
                mediaHash: media[0].sha256,
                role: kind === "shot" ? "firstFrame" : "identity",
                order: refs.length,
                state: "pending",
                keep: [],
                ignore: [],
                crop: null,
              },
            ])
          }
        >
          添加素材参考
        </button>
      </section>
      {refs.length > 0 && (
        <section>
          <h4>参考保留与忽略</h4>
          {refs.map((reference, i) => (
            <div
              className="workbench-entry"
              key={`${value(reference.mediaId)}:${i}`}
            >
              <p>
                {(
                  {
                    identity: "身份",
                    style: "风格",
                    location: "地点",
                    prop: "道具",
                    composition: "构图",
                    firstFrame: "首帧",
                    keyMoment: "关键时刻",
                    endFrame: "末帧",
                    voiceDrive: "声音驱动",
                    voiceReference: "声音参考",
                  } as Record<string, string>
                )[value(reference.role)] ?? "参考"}{" "}
                · {i + 1}
              </p>
              {[
                ["keep", "必须保持"],
                ["ignore", "可以忽略"],
              ].map(([field, label]) => (
                <div key={field}>
                  <h5>{label}</h5>
                  {strings(reference[field]).map((line, n, rows) => (
                    <div className="workbench-line" key={n}>
                      <input
                        aria-label={`${label} ${i + 1}-${n + 1}`}
                        value={line}
                        readOnly={readOnly}
                        onChange={(e) =>
                          patch("references", refs, i, {
                            [field]: replaceAt(rows, n, e.target.value),
                            state: "pending",
                          })
                        }
                      />
                      <button
                        disabled={readOnly}
                        onClick={() =>
                          patch("references", refs, i, {
                            [field]: rows.filter((_, x) => x !== n),
                            state: "pending",
                          })
                        }
                      >
                        移除
                      </button>
                    </div>
                  ))}
                  <button
                    disabled={readOnly}
                    onClick={() =>
                      patch("references", refs, i, {
                        [field]: [...strings(reference[field]), ""],
                        state: "pending",
                      })
                    }
                  >
                    添加{label}项
                  </button>
                </div>
              ))}
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
