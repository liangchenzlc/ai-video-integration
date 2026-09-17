import { useState, type FormEvent } from "react";
import { Dialog } from "../../components/ui/Dialog";
import {
  emptyConfig,
  serviceLabels,
  type AiConfig,
  type ConfigDraft,
  type ServiceType,
} from "./config-model";
import { applyPreset, providerPresets } from "./provider-presets";

export function ConfigForm({
  existing,
  onClose,
  onSave,
}: {
  existing: AiConfig | null;
  onClose: () => void;
  onSave: (draft: ConfigDraft, id?: string) => void;
}) {
  const [form, setForm] = useState<ConfigDraft>(
    existing ? { ...existing, apiKey: "" } : emptyConfig,
  );
  const [error, setError] = useState("");
  const change = (partial: Partial<ConfigDraft>) =>
    setForm((value) => ({ ...value, ...partial }));
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.name.trim() || !form.provider.trim()) {
      setError("请填写名称和提供商");
      return;
    }
    onSave(
      { ...form, name: form.name.trim(), provider: form.provider.trim() },
      existing?.id,
    );
  }
  return (
    <Dialog
      title={existing ? "编辑 AI 配置" : "添加 AI 配置"}
      onClose={onClose}
    >
      <form className="studio-form" onSubmit={submit}>
        <label>
          服务类型
          <select
            value={form.serviceType}
            onChange={(e) =>
              change({ serviceType: e.target.value as ServiceType })
            }
          >
            {Object.entries(serviceLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          名称
          <input
            value={form.name}
            onChange={(e) => change({ name: e.target.value })}
            required
            placeholder="例如：故事创作模型"
          />
        </label>
        <label>
          预设厂商
          <select
            value=""
            onChange={(event) => {
              const preset = providerPresets[form.serviceType].find(
                (item) => item.id === event.target.value,
              );
              if (preset) change(applyPreset(preset));
            }}
          >
            <option value="">选择后填入 URL 和模型</option>
            {providerPresets[form.serviceType].map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          提供商
          <input
            value={form.provider}
            onChange={(e) => change({ provider: e.target.value })}
            required
            placeholder="选择预设或输入自定义厂商"
          />
        </label>
        <label>
          Base URL
          <input
            value={form.baseUrl}
            onChange={(e) => change({ baseUrl: e.target.value })}
            type="url"
            placeholder="https://"
          />
        </label>
        {!["text", "tts", "jimeng2_character_auth"].includes(
          form.serviceType,
        ) && (
          <label>
            接口规范
            <select
              value={form.protocol}
              onChange={(e) => change({ protocol: e.target.value })}
            >
              <option value="">请选择</option>
              <option value="openai">OpenAI 兼容</option>
              <option value="volcengine">火山引擎</option>
              <option value="dashscope">通义万象</option>
              <option value="gemini">Google Gemini</option>
              <option value="kling">可灵</option>
              <option value="vidu">Vidu</option>
              <option value="custom">自定义</option>
            </select>
          </label>
        )}
        <label>
          {form.serviceType === "jimeng2_character_auth" ? "Token" : "API Key"}
          <input
            type="password"
            value={form.apiKey}
            onChange={(e) => change({ apiKey: e.target.value })}
            autoComplete="off"
            placeholder="仅供当前表单演示，不会保存"
          />
        </label>
        <label>
          模型列表
          <textarea
            value={form.models}
            onChange={(e) => change({ models: e.target.value })}
            rows={2}
            placeholder="多个模型用逗号分隔"
          />
        </label>
        <label>
          默认模型
          <input
            value={form.defaultModel}
            onChange={(e) => change({ defaultModel: e.target.value })}
            placeholder="输入模型名称"
          />
        </label>
        {!["text", "tts", "jimeng2_character_auth"].includes(
          form.serviceType,
        ) && (
          <div className="form-pair">
            <label>
              提交路径
              <input
                value={form.endpoint}
                onChange={(e) => change({ endpoint: e.target.value })}
                placeholder="选填"
              />
            </label>
            <label>
              查询路径
              <input
                value={form.queryEndpoint}
                onChange={(e) => change({ queryEndpoint: e.target.value })}
                placeholder="选填"
              />
            </label>
          </div>
        )}
        <label className="form-check">
          <input
            type="checkbox"
            checked={form.isDefault}
            onChange={(e) => change({ isDefault: e.target.checked })}
          />{" "}
          设为此服务类型的默认配置
        </label>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" onClick={onClose}>
            取消
          </button>
          <button className="studio-primary" type="submit">
            保存演示配置
          </button>
        </div>
      </form>
    </Dialog>
  );
}
