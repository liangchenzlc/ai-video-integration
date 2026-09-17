import type { ServiceType } from "./config-model";

export interface ProviderPreset {
  id: string;
  label: string;
  baseUrl: string;
  protocol: string;
  models: string[];
}

export const providerPresets: Record<ServiceType, ProviderPreset[]> = {
  text: [
    {
      id: "openai",
      label: "OpenAI",
      baseUrl: "https://api.openai.com/v1",
      protocol: "openai",
      models: ["gpt-4o", "gpt-4"],
    },
    {
      id: "volcengine",
      label: "火山引擎",
      baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
      protocol: "openai",
      models: ["deepseek-v3-2-251201", "doubao-1-5-pro-32k-250115"],
    },
    {
      id: "gemini",
      label: "Google Gemini",
      baseUrl: "https://generativelanguage.googleapis.com",
      protocol: "gemini",
      models: ["gemini-2.5-pro", "gemini-3-flash-preview"],
    },
    {
      id: "deepseek",
      label: "DeepSeek",
      baseUrl: "https://api.deepseek.com",
      protocol: "openai",
      models: ["deepseek-v4-flash", "deepseek-v4-pro"],
    },
    {
      id: "qwen",
      label: "通义千问",
      baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
      protocol: "openai",
      models: ["qwen3-max", "qwen-plus"],
    },
  ],
  image: [
    {
      id: "volcengine",
      label: "火山引擎",
      baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
      protocol: "volcengine",
      models: ["doubao-seedream-4-5-251128", "doubao-seedream-4-0-250828"],
    },
    {
      id: "gemini",
      label: "Google Gemini",
      baseUrl: "https://generativelanguage.googleapis.com",
      protocol: "gemini",
      models: ["gemini-2.5-flash-image", "gemini-3-pro-image-preview"],
    },
    {
      id: "openai",
      label: "OpenAI",
      baseUrl: "https://api.openai.com/v1",
      protocol: "openai",
      models: ["dall-e-3", "dall-e-2"],
    },
    {
      id: "dashscope",
      label: "通义万象",
      baseUrl: "https://dashscope.aliyuncs.com",
      protocol: "dashscope",
      models: ["wan2.6-image", "qwen-image-edit-plus"],
    },
  ],
  storyboard_image: [
    {
      id: "dashscope",
      label: "通义万象",
      baseUrl: "https://dashscope.aliyuncs.com",
      protocol: "dashscope",
      models: ["wan2.6-image", "qwen-image-edit-plus"],
    },
    {
      id: "volcengine",
      label: "火山引擎",
      baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
      protocol: "volcengine",
      models: ["doubao-seedream-4-5-251128"],
    },
    {
      id: "gemini",
      label: "Google Gemini",
      baseUrl: "https://generativelanguage.googleapis.com",
      protocol: "gemini",
      models: ["gemini-2.5-flash-image"],
    },
  ],
  video: [
    {
      id: "kling",
      label: "可灵 Kling",
      baseUrl: "",
      protocol: "kling",
      models: ["kling-omni-video", "kling-video"],
    },
    {
      id: "vidu",
      label: "Vidu",
      baseUrl: "",
      protocol: "vidu",
      models: ["viduq2", "viduq3-pro"],
    },
    {
      id: "volces",
      label: "火山引擎",
      baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
      protocol: "volcengine",
      models: ["doubao-seedance-2-0-260128"],
    },
    {
      id: "minimax",
      label: "MiniMax 海螺",
      baseUrl: "https://api.minimaxi.com/v1",
      protocol: "openai",
      models: ["MiniMax-Hailuo-2.3"],
    },
    {
      id: "openai",
      label: "OpenAI",
      baseUrl: "https://api.openai.com/v1",
      protocol: "openai",
      models: ["sora-2", "sora-2-pro"],
    },
  ],
  tts: [
    {
      id: "minimax",
      label: "MiniMax T2A",
      baseUrl: "https://api.minimaxi.com/v1",
      protocol: "openai",
      models: ["speech-02-hd", "speech-02-turbo"],
    },
  ],
  jimeng2_character_auth: [
    {
      id: "jimeng_material_api",
      label: "即梦业务素材 API",
      baseUrl: "",
      protocol: "",
      models: [],
    },
  ],
};

export function applyPreset(preset: ProviderPreset): Pick<
  ProviderPreset,
  "baseUrl" | "protocol"
> & {
  provider: string;
  models: string;
  defaultModel: string;
} {
  return {
    provider: preset.label,
    baseUrl: preset.baseUrl,
    protocol: preset.protocol,
    models: preset.models.join(", "),
    defaultModel: preset.models[0] ?? "",
  };
}
