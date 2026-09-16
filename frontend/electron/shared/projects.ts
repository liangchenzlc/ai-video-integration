import { z } from "zod";
import type { DraftsBridge } from "./drafts";
import type { MediaBridge } from "./media";

export const projectUuid = z
  .string()
  .regex(
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  );
const integer = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
export const fpsSchema = z.strictObject({
  numerator: z.union([z.literal(24), z.literal(25), z.literal(30)]),
  denominator: z.literal(1),
});
export const projectSchema = z.strictObject({
  id: projectUuid,
  name: z.string().min(1).max(120),
  revision: integer,
  eventSequence: integer,
  formatVersion: integer.min(1),
  aspect: z.enum(["16:9", "9:16"]),
  resolution: z.enum(["720p", "1080p"]),
  fps: fpsSchema,
  targetMs: integer.min(1),
  budgetMicroCny: integer,
  executionMode: z.enum(["synthetic", "real"]).nullable().default(null),
  savedAt: z.string().nullable(),
  readOnly: z.boolean(),
});
export const sessionSchema = z.strictObject({
  projectId: projectUuid,
  projectSessionId: projectUuid,
  mode: z.enum(["read", "write"]),
  project: projectSchema,
});
export const receiptSchema = z.strictObject({
  operationId: projectUuid,
  committedRevision: integer,
  resourceId: projectUuid,
  state: z.string().min(1).max(100),
});
export const recentSchema = z
  .array(
    z.strictObject({
      projectId: projectUuid,
      name: z.string().min(1).max(120),
      lastOpenedAt: z.string(),
    }),
  )
  .max(100);
export const directoryChoiceSchema = z
  .strictObject({ grantId: projectUuid, name: z.string().max(255) })
  .nullable();
export const chooseDirectorySchema = z.strictObject({
  purpose: z.enum(["createProject", "openProject"]),
});
export const createProjectSchema = z.strictObject({
  clientOperationId: projectUuid,
  expectedRevision: z.literal(0),
  payload: z.strictObject({
    directoryGrantId: projectUuid,
    name: z.string().trim().min(1).max(120),
    aspect: z.enum(["16:9", "9:16"]),
    resolution: z.enum(["720p", "1080p"]),
    fps: fpsSchema,
    targetMs: integer.min(1),
  }),
});
export const openProjectSchema = z.strictObject({
  directoryGrantId: projectUuid,
  requestedMode: z.enum(["read", "write"]),
});
export const recentInputSchema = z.strictObject({ projectId: projectUuid });
export const operationInputSchema = z.strictObject({
  operationId: projectUuid,
});
export const operationSchema = z.strictObject({
  operationId: projectUuid,
  state: z.enum(["committed", "accepted"]),
  receipt: receiptSchema,
});
export const closedSchema = z.strictObject({ closed: z.literal(true) });
export type ProjectSession = z.infer<typeof sessionSchema>;
export type CreateProject = z.infer<typeof createProjectSchema>;
export type RecentProject = z.infer<typeof recentSchema>[number];
export type ProjectResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: { code: string; message: string } };
export const projectMessages: Record<string, string> = {
  PLAN_STALE: "计划已过期或输入、模型配置已改变，请重新生成本地计划。",
  CAPABILITY_MISSING:
    "当前没有已准入的真实模型能力。可在新项目选择本地练习，或查看模型设置。",
  BUDGET_EXCEEDED:
    "项目、阶段或任务费用达到上限。请核对预算配置；原任务查询与下载仍可用。",
  TASK_BUSY: "另一个任务正在执行，请查看顶部活动任务并等待。",
  RECOVERY_NOT_ALLOWED: "当前状态或服务商能力不支持此恢复操作，请查询原任务。",
  EXECUTION_MODE_MISMATCH:
    "此项目已固定执行模式，练习与真实费用不能混记，请新建项目。",
  INPUT_INCOMPLETE:
    "生成所需输入不完整。请填写故事原文和创作简报，再生成计划；空白草稿仍可保存。",
  INPUT_LOCKED: "当前采用版本正被活动任务使用。请等待任务结束后再采用。",
  PREVIEW_STALE: "采用影响预览已过期或内容已变化，请重新预览。",
  REVISION_SIZE_LIMIT:
    "候选内容超过 700 KiB。草稿仍已保留，请精简后再保存候选。",
  DEPENDENCY_CYCLE: "这次采用会形成循环依赖，当前版本没有改变。",
  CHECK_REQUIRED:
    "必要检查尚未通过。可以先采用并标记待审核，或完成检查后确认。",
  UNDO_CONFLICT: "采用之后相关内容已有修改，无法直接撤销。请先核对当前版本。",
  CREDENTIAL_ENCRYPTION_FAILED:
    "Windows 加密不可用，未保存凭据。请重新录入并选择仅本次使用，或取消。",
  CREDENTIAL_DECRYPTION_FAILED:
    "无法解密此凭据，请在当前 Windows 用户下重新录入。",
  CREDENTIAL_UNAVAILABLE: "凭据当前不可用，请重新录入。",
  CREDENTIAL_NOT_FOUND: "凭据已不存在，请刷新设置后重新录入。",
  CREDENTIAL_KIND_MISMATCH:
    "凭据类型不匹配，请选择对应的 API Key 或 OSS 凭据。",
  CREDENTIAL_IN_USE: "此凭据正在使用，请检查相关设置。",
  CONFIRMATION_REQUIRED: "请先确认删除凭据。",
  STORAGE_CREDENTIAL_INVALID: "请选择同一服务商的 OSS 凭据。",
  STORAGE_PERSISTENCE_MISMATCH: "持久存储配置需要已加密保存的 OSS 凭据。",
  CAPABILITY_UNAVAILABLE: "此模型尚未通过所需验证，请查看能力缺口。",
  CAPABILITY_PHASE_MISMATCH: "此模型不支持所选制作阶段。",
  CONNECTION_CHECK_UNAVAILABLE:
    "此模型尚无已核定免费的检测适配器，未发起远程请求。",
  CONNECTION_CHECK_FAILED: "账户检测未通过，请核对凭据、地域和账户权限。",
  PROJECT_MIGRATION_FAILED: "项目升级未完成，旧数据库已保留，请重新打开项目。",
  REQUEST_INVALID: "请检查输入内容与所选配置。",
  VALIDATION_FAILED: "请检查输入内容与所选配置。",
  GRANT_REJECTED: "目录授权已失效，请重新选择目录。",
  SESSION_EXPIRED: "项目连接已失效，请重新打开项目。",
  PROJECT_READ_ONLY: "项目当前只读，请关闭占用窗口后重新打开。",
  PROJECT_BUSY: "项目正在使用，请关闭占用窗口后重试。",
  OPERATION_ID_REUSED: "操作编号对应的内容不同，请核对原操作。",
  REVISION_CONFLICT: "内容已更新，请核对已保存的内容。",
  DIRECTORY_NOT_EMPTY: "所选目录不是空目录，请选择新的空目录。",
  PROJECT_NOT_FOUND: "未找到项目，请重新选择项目目录。",
  OBJECT_NOT_FOUND: "未找到记录，请重新打开项目。",
  PROJECT_CORRUPT: "项目数据库无法读取，原文件已保留。",
  PROJECT_VERSION_UNSUPPORTED: "此项目格式与当前应用不兼容。",
  PROJECT_RECOVERY_REQUIRED: "项目创建尚未完成，原文件已保留，请查询原操作。",
  UNSAFE_PROJECT_PATH: "请选择本机普通目录，避开网络、同步或链接目录。",
  STORAGE_UNAVAILABLE: "无法访问本地存储，请检查磁盘与目录权限。",
  BACKEND_UNAVAILABLE: "本地服务连接中断，请先恢复服务，再查询原操作。",
  PROTOCOL_INVALID: "本地服务返回数据异常，请查询原操作，不要重复新建。",
  SOURCE_REJECTED: "无法执行来自此页面的请求。",
  MEDIA_TOOLS_NOT_CONFIGURED: "请先选择本机 FFmpeg 工具。",
  MEDIA_TOOLS_UNAVAILABLE: "无法启动媒体工具，请重新选择 FFmpeg。",
  MEDIA_TOOLS_MISMATCH: "FFmpeg 与 ffprobe 不匹配，请选择同一构建的工具。",
  MEDIA_TOOLS_CAPABILITY_MISSING: "媒体工具缺少 H.264、AAC 或字幕编码支持。",
  MEDIA_FORMAT_UNSUPPORTED: "请选择支持的图片、音频或视频格式。",
  MEDIA_SIZE_LIMIT: "单个媒体文件不能超过 2 GiB。",
  MEDIA_PIXEL_LIMIT: "图片尺寸超过 4,000 万像素。",
  MEDIA_INVALID: "媒体无法完整解码，原文件已保留。",
  MEDIA_PROBE_TIMEOUT: "媒体检查超时，原文件已保留。",
  MEDIA_TOOL_OUTPUT_LIMIT: "媒体工具返回数据超限，检查已停止。",
  INSUFFICIENT_DISK_SPACE: "项目磁盘空间不足，请腾出空间后重试。",
  MEDIA_SOURCE_CHANGED: "导入期间源文件发生变化，请重新选择。",
  MEDIA_HASH_MISMATCH: "文件内容不同，不能作为原素材恢复。请导入为新素材。",
  MEDIA_RECOVERY_REQUIRED: "导入中断，文件已保留，请核对原作业。",
  MEDIA_MISSING: "素材文件缺失，请重新定位原文件。",
  MEDIA_UNAVAILABLE: "素材当前不可用，原记录已保留。",
  JOB_NOT_CANCELLABLE: "作业已结束，无法取消。",
  JOB_CANCELLED: "作业已取消，原文件已保留。",
  JOB_INTERRUPTED: "作业中断，请核对原结果。",
  BACKUP_FAILED: "项目备份未通过检查，旧数据库已保留。",
};
export function projectError(code: string): { code: string; message: string } {
  const known = Object.hasOwn(projectMessages, code)
    ? code
    : "BACKEND_UNAVAILABLE";
  return { code: known, message: projectMessages[known] };
}
export interface ProjectsBridge {
  drafts: DraftsBridge;
  media: MediaBridge;
  chooseDirectory(
    input: z.infer<typeof chooseDirectorySchema>,
  ): Promise<ProjectResult<z.infer<typeof directoryChoiceSchema>>>;
  create(
    input: CreateProject,
  ): Promise<ProjectResult<z.infer<typeof receiptSchema>>>;
  open(
    input: z.infer<typeof openProjectSchema>,
  ): Promise<ProjectResult<ProjectSession>>;
  openRecent(
    input: z.infer<typeof recentInputSchema>,
  ): Promise<ProjectResult<ProjectSession>>;
  recent(): Promise<ProjectResult<RecentProject[]>>;
  current(): Promise<ProjectResult<ProjectSession | null>>;
  close(): Promise<ProjectResult<z.infer<typeof closedSchema>>>;
  operation(
    input: z.infer<typeof operationInputSchema>,
  ): Promise<ProjectResult<z.infer<typeof operationSchema>>>;
}
