import { useState } from "react";
import { ConfigForm } from "../../features/ai-config/ConfigForm";
import { ConfigTable } from "../../features/ai-config/ConfigTable";
import type {
  AiConfig,
  ConfigDraft,
} from "../../features/ai-config/config-model";
import {
  GenerationSettings,
  PromptSettings,
  SceneModelSettings,
  promptFields,
  type PromptKey,
  type SceneKey,
} from "../../features/ai-config/AdvancedSettings";

const tabs = [
  "AI 配置",
  "高级设置（提示词）",
  "高级设置（业务场景）",
  "生成设置",
  "SD2 资产管理",
] as const;
export function AiConfigPage() {
  const [items, setItems] = useState<AiConfig[]>([]);
  const [tab, setTab] = useState<(typeof tabs)[number]>(tabs[0]);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<AiConfig | null>(null);
  const [imageConcurrency, setImageConcurrency] = useState(3);
  const [videoConcurrency, setVideoConcurrency] = useState(1);
  const [prompts, setPrompts] = useState<Record<PromptKey, string>>(
    () =>
      Object.fromEntries(promptFields.map(({ key }) => [key, ""])) as Record<
        PromptKey,
        string
      >,
  );
  const [sceneModels, setSceneModels] = useState<Record<SceneKey, string>>({
    story: "",
    assets: "",
    storyboard: "",
    video: "",
    voice: "",
  });
  function save(draft: ConfigDraft, id?: string) {
    // Never retain credentials in UI state or browser storage.
    const { apiKey: _ignored, ...metadata } = draft;
    void _ignored;
    setItems((existing) => {
      const withoutOld = existing.filter((item) => item.id !== id);
      return [
        { ...metadata, id: id ?? crypto.randomUUID() },
        ...withoutOld.map((item) =>
          metadata.isDefault && item.serviceType === metadata.serviceType
            ? { ...item, isDefault: false }
            : item,
        ),
      ];
    });
    setFormOpen(false);
  }
  return (
    <section className="studio-page" aria-labelledby="ai-title">
      <div className="studio-page-head">
        <div>
          <h1 id="ai-title">AI 配置</h1>
          <p>管理文本、图片、视频及语音服务的模型信息。</p>
        </div>
      </div>
      <div className="preview-note" role="note">
        界面演示：本页配置只在当前窗口保留；API Key
        不保存，也不会发起连接或生成请求。
      </div>
      <div className="studio-tabs" role="tablist" aria-label="AI 配置类别">
        {tabs.map((name) => (
          <button
            key={name}
            role="tab"
            aria-selected={tab === name}
            className={tab === name ? "active" : ""}
            onClick={() => setTab(name)}
          >
            {name}
          </button>
        ))}
      </div>
      {tab === "AI 配置" && (
        <>
          <div className="studio-toolbar">
            <button
              className="studio-primary"
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
            >
              添加配置
            </button>
            <span>每种服务类型可设置一个默认配置</span>
          </div>
          <ConfigTable
            items={items}
            onEdit={(item) => {
              setEditing(item);
              setFormOpen(true);
            }}
            onDelete={(id) =>
              setItems((current) => current.filter((item) => item.id !== id))
            }
          />
        </>
      )}
      {tab === "高级设置（提示词）" && (
        <PromptSettings
          values={prompts}
          onChange={(key, value) =>
            setPrompts((current) => ({ ...current, [key]: value }))
          }
        />
      )}
      {tab === "高级设置（业务场景）" && (
        <SceneModelSettings
          items={items}
          selected={sceneModels}
          onChange={(key, id) =>
            setSceneModels((current) => ({ ...current, [key]: id }))
          }
        />
      )}
      {tab === "生成设置" && (
        <GenerationSettings
          image={imageConcurrency}
          video={videoConcurrency}
          onImage={setImageConcurrency}
          onVideo={setVideoConcurrency}
        />
      )}
      {tab === "SD2 资产管理" && (
        <div className="settings-section">
          <h2>SD2 资产管理</h2>
          <p>接入即梦2认证与资产服务后，可在这里查看和管理已登记的角色资产。</p>
          <div className="studio-empty">尚无已连接的资产服务</div>
        </div>
      )}
      {formOpen && (
        <ConfigForm
          existing={editing}
          onClose={() => setFormOpen(false)}
          onSave={save}
        />
      )}
    </section>
  );
}
