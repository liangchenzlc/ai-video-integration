import type { TaskPlan } from "../../electron/shared/tasks";

const inputLabels: Record<string, string> = {
  idea: "一个想法",
  excerpt: "小说片段",
  script: "已有剧本",
};
const levelLabels: Record<string, string> = {
  proposal: "故事方案",
  outline: "故事大纲",
  scenes: "场景",
  dialogue: "对白",
};
const categoryLabels: Record<string, string> = {
  fact: "事实",
  action: "动作",
  dialogue: "对白",
  sound: "声音",
  screenText: "画面文字",
  reveal: "信息揭示",
};
const decisionLabels: Record<string, string> = {
  keep: "保留",
  omit: "省略",
  replace: "替换",
  unresolved: "待决定",
};
const deliveryLabels: Record<string, string> = {
  visible: "出镜对白",
  VO: "旁白",
  OS: "画外对白",
};
function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}
function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          item !== null && typeof item === "object" && !Array.isArray(item),
      )
    : [];
}
function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

export function StoryPlanPreview({
  input,
}: {
  input: TaskPlan["inputPreview"];
}) {
  if (input.kind === "asset") {
    const content = input.payload;
    const assetTypes: Record<string, string> = {
      character: "角色",
      location: "场景",
      prop: "道具",
      style: "风格",
    };
    const anchors = strings(content.identityAnchors);
    const changes = strings(content.allowedChanges);
    return (
      <div className="story-plan-preview">
        <dl className="story-plan-metadata">
          <div>
            <dt>素材名称</dt>
            <dd>{text(content.name) || "未填写"}</dd>
          </div>
          <div>
            <dt>素材类型</dt>
            <dd>{assetTypes[text(content.assetType)] ?? "未标记"}</dd>
          </div>
        </dl>
        <section>
          <h4>身份锚点</h4>
          <ul>
            {anchors.map((anchor, index) => (
              <li key={index}>{anchor}</li>
            ))}
          </ul>
        </section>
        {changes.length > 0 && (
          <section>
            <h4>允许变化</h4>
            <ul>
              {changes.map((change, index) => (
                <li key={index}>{change}</li>
              ))}
            </ul>
          </section>
        )}
      </div>
    );
  }
  if (input.kind !== "story")
    return (
      <p>当前入口只提供故事内容预览。其他类型的输入需在对应工作区核对。</p>
    );
  const content = input.payload;
  const outline = strings(content.outline);
  const requirements = records(content.requirements);
  const scenes = records(content.scenes);
  const dialogues = records(content.dialogues);
  const notes = strings(content.adaptationNotes);
  const source = text(content.sourceText);
  const sourcePoints = Array.from(source);
  return (
    <div className="story-plan-preview">
      <dl className="story-plan-metadata">
        <div>
          <dt>内容入口</dt>
          <dd>{inputLabels[text(content.inputType)] ?? "尚未标记"}</dd>
        </div>
        <div>
          <dt>故事层级</dt>
          <dd>{levelLabels[text(content.approvalLevel)] ?? "尚未标记"}</dd>
        </div>
      </dl>
      <section>
        <h4>故事原文</h4>
        <p className="story-plan-text">{source || "未填写"}</p>
      </section>
      <section>
        <h4>创作简报</h4>
        <p className="story-plan-text">{text(content.brief) || "未填写"}</p>
      </section>
      {outline.length > 0 && (
        <section>
          <h4>故事大纲</h4>
          <ol>
            {outline.map((item, index) => (
              <li className="story-plan-text" key={index}>
                {item}
              </li>
            ))}
          </ol>
        </section>
      )}
      {requirements.length > 0 && (
        <section>
          <h4>故事要求</h4>
          <ol>
            {requirements.map((item, index) => {
              const span = records([item.source])[0];
              const start = span?.startCodePoint;
              const end = span?.endCodePoint;
              const excerpt =
                span &&
                typeof content.sourceHash === "string" &&
                span.sourceHash === content.sourceHash &&
                typeof start === "number" &&
                typeof end === "number" &&
                Number.isInteger(start) &&
                Number.isInteger(end) &&
                0 <= start &&
                start < end &&
                end <= sourcePoints.length
                  ? sourcePoints.slice(start, end).join("")
                  : "";
              return (
                <li key={index}>
                  <p>
                    {categoryLabels[text(item.category)] ?? "要求"} ·{" "}
                    {item.required === true
                      ? "必须满足"
                      : item.required === false
                        ? "可选"
                        : "尚未标记是否必需"}{" "}
                    · {decisionLabels[text(item.decision)] ?? "待决定"}
                  </p>
                  <p className="story-plan-text">{text(item.text)}</p>
                  {text(item.decisionReason) && (
                    <p className="story-plan-text">
                      处理理由：{text(item.decisionReason)}
                    </p>
                  )}
                  {excerpt ? (
                    <blockquote className="story-plan-text">
                      原文摘录：{excerpt}
                    </blockquote>
                  ) : (
                    item.source != null && (
                      <p>原文引用已变化或尚未完整，请核对</p>
                    )
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      )}
      {scenes.length > 0 && (
        <section>
          <h4>场景安排</h4>
          <ol>
            {scenes.map((item, index) => (
              <li key={index}>
                <p>
                  <strong>{text(item.title) || `场景 ${index + 1}`}</strong>
                  {typeof item.plannedMs === "number" &&
                    ` · 计划 ${item.plannedMs / 1000} 秒`}
                </p>
                <p className="story-plan-text">{text(item.action)}</p>
                {(text(item.id) || text(item.locationAssetId)) && (
                  <details>
                    <summary>关联对象</summary>
                    {text(item.id) && <p>场景编号：{text(item.id)}</p>}
                    {text(item.locationAssetId) && (
                      <p>场景地点资产编号：{text(item.locationAssetId)}</p>
                    )}
                  </details>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}
      {dialogues.length > 0 && (
        <section>
          <h4>对白内容</h4>
          <ol>
            {dialogues.map((item, index) => {
              const scene = scenes.find((scene) => scene.id === item.sceneId);
              const requirementIds = strings(item.requirementIds);
              const related = requirements.filter((requirement) =>
                requirementIds.includes(text(requirement.id)),
              );
              return (
                <li key={index}>
                  <p>
                    {deliveryLabels[text(item.delivery)] ?? "对白"}
                    {scene && ` · ${text(scene.title) || "已关联场景"}`}
                  </p>
                  <p className="story-plan-text">{text(item.text)}</p>
                  {related.length > 0 && (
                    <p className="story-plan-text">
                      关联要求：
                      {related
                        .map((requirement) => text(requirement.text))
                        .join("；")}
                    </p>
                  )}
                  {(text(item.speakerAssetId) ||
                    text(item.sceneId) ||
                    requirementIds.length > 0) && (
                    <details>
                      <summary>关联对象</summary>
                      {text(item.speakerAssetId) && (
                        <p>说话角色资产编号：{text(item.speakerAssetId)}</p>
                      )}
                      {text(item.sceneId) && (
                        <p>所属场景编号：{text(item.sceneId)}</p>
                      )}
                      {requirementIds.length > 0 && (
                        <p>关联要求编号：{requirementIds.join("、")}</p>
                      )}
                    </details>
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      )}
      {notes.length > 0 && (
        <section>
          <h4>改编说明</h4>
          <ul>
            {notes.map((item, index) => (
              <li className="story-plan-text" key={index}>
                {item}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
