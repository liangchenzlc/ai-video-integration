export type ServiceType =
  | "text"
  | "image"
  | "storyboard_image"
  | "video"
  | "tts"
  | "jimeng2_character_auth";
export const serviceLabels: Record<ServiceType, string> = {
  text: "文本 / 对话",
  image: "文本生成图片",
  storyboard_image: "分镜图片生成",
  video: "视频生成",
  tts: "语音合成 TTS",
  jimeng2_character_auth: "即梦2角色认证",
};
export interface AiConfig {
  id: string;
  name: string;
  provider: string;
  serviceType: ServiceType;
  baseUrl: string;
  protocol: string;
  models: string;
  defaultModel: string;
  endpoint: string;
  queryEndpoint: string;
  isDefault: boolean;
}
export type ConfigDraft = Omit<AiConfig, "id"> & { apiKey: string };
export const emptyConfig: ConfigDraft = {
  name: "",
  provider: "",
  serviceType: "text",
  baseUrl: "",
  protocol: "",
  models: "",
  defaultModel: "",
  endpoint: "",
  queryEndpoint: "",
  isDefault: true,
  apiKey: "",
};
