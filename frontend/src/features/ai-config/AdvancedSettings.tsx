import type { AiConfig } from "./config-model";

export const promptFields = [
  { key: "story", label: "故事创作", hint: "约束故事结构、人物关系与情绪节奏" },
  { key: "character", label: "角色设定", hint: "描述角色外观、性格与统一形象" },
  { key: "scene", label: "场景描述", hint: "明确空间、时间和视觉风格" },
  { key: "shot", label: "分镜画面", hint: "指定构图、机位和镜头运动" },
] as const;
export type PromptKey = (typeof promptFields)[number]["key"];

export function PromptSettings({
  values,
  onChange,
}: {
  values: Record<PromptKey, string>;
  onChange: (key: PromptKey, value: string) => void;
}) {
  return (
    <div className="settings-section">
      <h2>创作提示词</h2>
      <p>按创作步骤整理提示词。内容只在当前窗口保留，不会提交给模型。</p>
      <div className="advanced-fields">
        {promptFields.map((field) => (
          <label key={field.key}>
            {field.label}
            <span className="field-hint">{field.hint}</span>
            <textarea
              rows={4}
              value={values[field.key]}
              onChange={(event) => onChange(field.key, event.target.value)}
              placeholder={`输入${field.label}提示词`}
            />
          </label>
        ))}
      </div>
    </div>
  );
}

const scenes = [
  { key: "story", label: "故事创作", type: "text" },
  { key: "assets", label: "角色、场景、道具", type: "image" },
  { key: "storyboard", label: "分镜图片", type: "storyboard_image" },
  { key: "video", label: "镜头视频", type: "video" },
  { key: "voice", label: "分镜配音", type: "tts" },
] as const;
export type SceneKey = (typeof scenes)[number]["key"];
export function SceneModelSettings({
  items,
  selected,
  onChange,
}: {
  items: AiConfig[];
  selected: Record<SceneKey, string>;
  onChange: (key: SceneKey, id: string) => void;
}) {
  return (
    <div className="settings-section">
      <h2>业务场景与模型</h2>
      <p>将已添加的演示配置对应到创作步骤；映射只在当前窗口保留。</p>
      <div className="scene-settings">
        {scenes.map((scene) => (
          <label key={scene.key}>
            {scene.label}
            <select
              value={selected[scene.key]}
              onChange={(event) => onChange(scene.key, event.target.value)}
            >
              <option value="">尚未指定</option>
              {items
                .filter((item) => item.serviceType === scene.type)
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {item.defaultModel || "未选模型"}
                  </option>
                ))}
            </select>
          </label>
        ))}
      </div>
    </div>
  );
}

export function GenerationSettings({
  image,
  video,
  onImage,
  onVideo,
}: {
  image: number;
  video: number;
  onImage: (value: number) => void;
  onVideo: (value: number) => void;
}) {
  return (
    <div className="settings-section">
      <h2>一键生成并发设置</h2>
      <p>预览图片和视频任务的同时生成数量。当前阶段没有接入任务执行。</p>
      <div className="form-pair">
        <label>
          图片并发数
          <input
            type="number"
            min="1"
            max="10"
            value={image}
            onChange={(event) => onImage(Number(event.target.value))}
          />
        </label>
        <label>
          视频并发数
          <input
            type="number"
            min="1"
            max="10"
            value={video}
            onChange={(event) => onVideo(Number(event.target.value))}
          />
        </label>
      </div>
      <p className="field-hint">
        图片用于角色、场景和分镜画面；视频用于镜头生成。设置在关闭窗口后会清空。
      </p>
    </div>
  );
}
