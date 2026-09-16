import { useEffect, useState, type RefObject } from "react";
import {
  entries,
  replaceAt,
  sourceSpan,
  strings,
  textHash,
  uuid,
  value,
  type Entry,
} from "./storyboard-fields";
import type { Draft } from "../../electron/shared/drafts";

type Content = Draft["content"]["content"];
export function StoryStructure({
  content,
  sourceField,
  readOnly,
  projectId,
  onEdit,
}: {
  content: Content;
  sourceField: RefObject<HTMLTextAreaElement | null>;
  readOnly: boolean;
  projectId: string;
  onEdit: (content: Content) => void;
}) {
  const source = value(content.sourceText);
  const [hash, setHash] = useState("");
  const [assets, setAssets] = useState<
    { id: string; name: string; kind: string }[]
  >([]);
  useEffect(() => {
    let active = true;
    const refresh = () => {
      void (async () => {
        const result = await window.desktop.storyboard.list({ projectId });
        if (!result.ok) return;
        const loaded = await Promise.all(
          result.data.drafts
            .filter((d) => d.kind === "asset")
            .map(async (d) => ({
              summary: d,
              result: await window.desktop.projects.drafts.get({
                projectId,
                draftId: d.id,
              }),
            })),
        );
        if (active)
          setAssets(
            loaded
              .filter((row) => row.result.ok)
              .map((row) => ({
                id: row.summary.artifactId,
                name: row.result.ok
                  ? value(row.result.data.content.content.name)
                  : "",
                kind: row.result.ok
                  ? value(row.result.data.content.content.assetType)
                  : "",
              })),
          );
      })();
    };
    refresh();
    window.addEventListener("storyboard-updated", refresh);
    return () => {
      active = false;
      window.removeEventListener("storyboard-updated", refresh);
    };
  }, [projectId]);
  useEffect(() => {
    let active = true;
    void textHash(source).then((next) => {
      if (active) setHash(next);
    });
    return () => {
      active = false;
    };
  }, [source]);
  const outline = strings(content.outline),
    notes = strings(content.adaptationNotes);
  const requirements = entries(content.requirements),
    scenes = entries(content.scenes),
    dialogues = entries(content.dialogues);
  const edit = (field: string, next: unknown) => {
    if (!readOnly) onEdit({ ...content, [field]: next } as Content);
  };
  const patch = (field: string, items: Entry[], index: number, values: Entry) =>
    edit(field, replaceAt(items, index, { ...items[index], ...values }));
  const remove = (field: string, items: unknown[], index: number) =>
    edit(
      field,
      items.filter((_, n) => n !== index),
    );
  return (
    <div className="story-structure">
      <div className="section-heading">
        <h3>内容整理</h3>
        <span>原文保持原样，逐项记录改编决定</span>
      </div>
      <label>
        当前审核层级
        <select
          disabled={readOnly}
          value={value(content.approvalLevel) || "proposal"}
          onChange={(e) => edit("approvalLevel", e.target.value)}
        >
          <option value="proposal">内容方案</option>
          <option value="outline">故事大纲</option>
          <option value="scenes">分场</option>
          <option value="dialogue">对白</option>
        </select>
      </label>
      <section>
        <h4>故事大纲</h4>
        {outline.map((line, i) => (
          <div className="workbench-line" key={i}>
            <label>
              大纲 {i + 1}
              <textarea
                value={line}
                readOnly={readOnly}
                onChange={(e) =>
                  edit("outline", replaceAt(outline, i, e.target.value))
                }
              />
            </label>
            <button
              disabled={readOnly}
              onClick={() => remove("outline", outline, i)}
            >
              移除
            </button>
          </div>
        ))}
        <button
          disabled={readOnly}
          onClick={() => edit("outline", [...outline, ""])}
        >
          添加大纲
        </button>
      </section>
      <section>
        <h4>必须保留与改编决定</h4>
        <p className="muted">选中原文后记录来源。原文变化后旧引用仍需核对。</p>
        {requirements.map((item, i) => {
          const span = item.source as Entry | null;
          return (
            <div className="workbench-entry" key={value(item.id) || i}>
              <label>
                要求内容
                <input
                  value={value(item.text)}
                  readOnly={readOnly}
                  onChange={(e) =>
                    patch("requirements", requirements, i, {
                      text: e.target.value,
                    })
                  }
                />
              </label>
              <div className="form-row">
                <label>
                  类别
                  <select
                    disabled={readOnly}
                    value={value(item.category) || "fact"}
                    onChange={(e) =>
                      patch("requirements", requirements, i, {
                        category: e.target.value,
                      })
                    }
                  >
                    {[
                      ["fact", "事实"],
                      ["action", "动作"],
                      ["dialogue", "对白"],
                      ["sound", "声音"],
                      ["screenText", "画面文字"],
                      ["reveal", "信息揭示"],
                    ].map(([id, label]) => (
                      <option key={id} value={id}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  决定
                  <select
                    disabled={readOnly}
                    value={value(item.decision) || "unresolved"}
                    onChange={(e) =>
                      patch("requirements", requirements, i, {
                        decision: e.target.value,
                      })
                    }
                  >
                    <option value="unresolved">待决定</option>
                    <option value="keep">保留</option>
                    <option value="omit">省略</option>
                    <option value="replace">替换</option>
                  </select>
                </label>
              </div>
              <label>
                <input
                  type="checkbox"
                  checked={item.required === true}
                  disabled={readOnly}
                  onChange={(e) =>
                    patch("requirements", requirements, i, {
                      required: e.target.checked,
                    })
                  }
                />{" "}
                必须保留
              </label>
              {(item.decision === "omit" || item.decision === "replace") && (
                <label>
                  决定理由
                  <textarea
                    value={value(item.decisionReason)}
                    readOnly={readOnly}
                    onChange={(e) =>
                      patch("requirements", requirements, i, {
                        decisionReason: e.target.value,
                      })
                    }
                  />
                </label>
              )}
              <p
                className={
                  span && span.sourceHash !== hash ? "notice" : "muted"
                }
              >
                {span
                  ? span.sourceHash === hash
                    ? `原文码点 ${span.startCodePoint}–${span.endCodePoint}`
                    : "原文已变化，来源待核对"
                  : "尚无来源定位"}
              </p>
              <button
                disabled={readOnly || !hash}
                onClick={() => {
                  const selected = sourceSpan(
                    source,
                    sourceField.current?.selectionStart ?? 0,
                    sourceField.current?.selectionEnd ?? 0,
                    hash,
                  );
                  if (selected)
                    patch("requirements", requirements, i, {
                      source: selected,
                    });
                }}
              >
                使用选中的原文
              </button>
              <button
                disabled={readOnly}
                onClick={() => remove("requirements", requirements, i)}
              >
                移除要求
              </button>
            </div>
          );
        })}
        <button
          disabled={readOnly}
          onClick={() =>
            edit("requirements", [
              ...requirements,
              {
                id: uuid(),
                text: "",
                category: "fact",
                source: null,
                required: true,
                decision: "unresolved",
                decisionReason: "",
              },
            ])
          }
        >
          添加要求
        </button>
      </section>
      <section>
        <h4>分场</h4>
        {scenes.map((item, i) => (
          <div className="workbench-entry" key={value(item.id) || i}>
            <label>
              场景名称
              <input
                value={value(item.title)}
                readOnly={readOnly}
                onChange={(e) =>
                  patch("scenes", scenes, i, { title: e.target.value })
                }
              />
            </label>
            <label>
              场景动作
              <textarea
                value={value(item.action)}
                readOnly={readOnly}
                onChange={(e) =>
                  patch("scenes", scenes, i, { action: e.target.value })
                }
              />
            </label>
            <label>
              计划时长（秒）
              <input
                type="number"
                min="1"
                value={Number(item.plannedMs || 1000) / 1000}
                readOnly={readOnly}
                onChange={(e) =>
                  patch("scenes", scenes, i, {
                    plannedMs: Math.round(Number(e.target.value) * 1000),
                  })
                }
              />
            </label>
            <label>
              地点资产
              <select
                disabled={readOnly}
                value={value(item.locationAssetId)}
                onChange={(e) =>
                  patch("scenes", scenes, i, {
                    locationAssetId: e.target.value || null,
                  })
                }
              >
                <option value="">暂无地点资产</option>
                {assets
                  .filter((a) => a.kind === "location")
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name || a.id.slice(0, 8)}
                    </option>
                  ))}
              </select>
            </label>
            <button
              disabled={readOnly}
              onClick={() => remove("scenes", scenes, i)}
            >
              移除场景
            </button>
          </div>
        ))}
        <button
          disabled={readOnly}
          onClick={() =>
            edit("scenes", [
              ...scenes,
              {
                id: uuid(),
                title: "",
                action: "",
                plannedMs: 1000,
                locationAssetId: null,
              },
            ])
          }
        >
          添加场景
        </button>
      </section>
      <section>
        <h4>对白</h4>
        {dialogues.map((item, i) => (
          <div className="workbench-entry" key={value(item.id) || i}>
            <label>
              台词原文
              <textarea
                value={value(item.text)}
                readOnly={readOnly}
                onChange={(e) =>
                  patch("dialogues", dialogues, i, { text: e.target.value })
                }
              />
            </label>
            <div className="form-row">
              <label>
                所属场景
                <select
                  disabled={readOnly}
                  value={value(item.sceneId)}
                  onChange={(e) =>
                    patch("dialogues", dialogues, i, {
                      sceneId: e.target.value,
                    })
                  }
                >
                  <option value="">选择场景</option>
                  {scenes.map((s) => (
                    <option key={value(s.id)} value={value(s.id)}>
                      {value(s.title) || "未命名场景"}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                呈现方式
                <select
                  disabled={readOnly}
                  value={value(item.delivery) || "visible"}
                  onChange={(e) =>
                    patch("dialogues", dialogues, i, {
                      delivery: e.target.value,
                    })
                  }
                >
                  <option value="visible">出镜对白</option>
                  <option value="VO">旁白</option>
                  <option value="OS">画外对白</option>
                </select>
              </label>
              <label>
                说话角色
                <select
                  disabled={readOnly}
                  value={value(item.speakerAssetId)}
                  onChange={(e) =>
                    patch("dialogues", dialogues, i, {
                      speakerAssetId: e.target.value,
                    })
                  }
                >
                  <option value="">选择角色</option>
                  {assets
                    .filter((a) => a.kind === "character")
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name || a.id.slice(0, 8)}
                      </option>
                    ))}
                </select>
              </label>
            </div>
            <fieldset>
              <legend>关联要求</legend>
              {requirements.map((r) => (
                <label className="check-option" key={value(r.id)}>
                  <input
                    type="checkbox"
                    disabled={readOnly}
                    checked={strings(item.requirementIds).includes(value(r.id))}
                    onChange={(e) =>
                      patch("dialogues", dialogues, i, {
                        requirementIds: e.target.checked
                          ? [...strings(item.requirementIds), value(r.id)]
                          : strings(item.requirementIds).filter(
                              (id) => id !== r.id,
                            ),
                      })
                    }
                  />
                  {value(r.text) || "未命名要求"}
                </label>
              ))}
            </fieldset>
            <button
              disabled={readOnly}
              onClick={() => remove("dialogues", dialogues, i)}
            >
              移除对白
            </button>
          </div>
        ))}
        <button
          disabled={
            readOnly ||
            !scenes.length ||
            !assets.some((a) => a.kind === "character")
          }
          onClick={() =>
            edit("dialogues", [
              ...dialogues,
              {
                id: uuid(),
                speakerAssetId:
                  assets.find((a) => a.kind === "character")?.id ?? "",
                text: "",
                delivery: "visible",
                requirementIds: [],
                sceneId: value(scenes[0].id),
              },
            ])
          }
        >
          添加对白
        </button>
      </section>
      <section>
        <h4>改编说明</h4>
        {notes.map((line, i) => (
          <div className="workbench-line" key={i}>
            <textarea
              aria-label={`改编说明 ${i + 1}`}
              value={line}
              readOnly={readOnly}
              onChange={(e) =>
                edit("adaptationNotes", replaceAt(notes, i, e.target.value))
              }
            />
            <button
              disabled={readOnly}
              onClick={() => remove("adaptationNotes", notes, i)}
            >
              移除
            </button>
          </div>
        ))}
        <button
          disabled={readOnly}
          onClick={() => edit("adaptationNotes", [...notes, ""])}
        >
          添加改编说明
        </button>
      </section>
    </div>
  );
}
