import type { Media, MediaJob } from "../../../electron/shared/media";
import { projectUuid } from "../../../electron/shared/projects";
import type { DesktopBridge } from "../../../electron/shared/runtime";

export type ListedMedia = Pick<Media, "id" | "mime" | "availability">;
export type MediaImportResult =
  | { ok: true; mediaId: string }
  | {
      ok: false;
      reason: "cancelled" | "failure" | "uncertain";
      message?: string;
    };

const uncertainCodes = new Set([
  "BACKEND_UNAVAILABLE",
  "PROTOCOL_INVALID",
  "SESSION_EXPIRED",
]);

function bridge() {
  return (globalThis as { desktop?: DesktopBridge }).desktop?.projects;
}

export function listUsableMediaResult<T extends ListedMedia>(
  items: readonly T[],
  mimePrefix: string,
): T[] {
  return items.filter(
    (item) =>
      item.availability === "available" && item.mime.startsWith(mimePrefix),
  );
}

/** Check a persisted media ID against a fresh project listing, not a saved flag. */
export function hasAvailableMedia(
  items: readonly ListedMedia[],
  mediaId: string,
  mimePrefix: string,
) {
  return items.some(
    (item) =>
      item.id === mediaId &&
      item.availability === "available" &&
      (mimePrefix.endsWith("/")
        ? item.mime.startsWith(mimePrefix)
        : item.mime === mimePrefix),
  );
}

export async function listUsableMedia(projectId: string, mimePrefix: string) {
  if (!projectUuid.safeParse(projectId).success) return [] as Media[];
  const projects = bridge();
  if (!projects) return [] as Media[];
  try {
    const items: Media[] = [];
    const seenCursors = new Set<string>();
    let cursor: string | null = null;
    for (;;) {
      const result = await projects.media.list({
        projectId,
        limit: 200,
        ...(cursor ? { cursor } : {}),
      });
      if (!result.ok) return [] as Media[];
      items.push(...result.data.items);
      const nextCursor = result.data.nextCursor;
      if (!nextCursor) return listUsableMediaResult(items, mimePrefix);
      // A malformed or repeated cursor must fail closed, not loop forever.
      if (seenCursors.has(nextCursor)) return [] as Media[];
      seenCursors.add(nextCursor);
      cursor = nextCursor;
    }
  } catch {
    return [] as Media[];
  }
}

export function mediaUrl(projectId: string, mediaId: string) {
  if (
    !projectUuid.safeParse(projectId).success ||
    !projectUuid.safeParse(mediaId).success
  )
    return null;
  return `avi-media://local/${projectId}/${mediaId}`;
}

async function waitForImport(
  projectId: string,
  jobId: string,
  getJob: (input: {
    projectId: string;
    jobId: string;
  }) => Promise<
    | { ok: true; data: MediaJob }
    | { ok: false; error: { code: string; message: string } }
  >,
): Promise<MediaImportResult> {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      const result = await getJob({ projectId, jobId });
      if (!result.ok) return { ok: false, reason: "uncertain" };
      if (result.data.state === "succeeded" && result.data.resultId)
        return { ok: true, mediaId: result.data.resultId };
      if (result.data.state === "failed" || result.data.state === "cancelled")
        return {
          ok: false,
          reason: "failure",
          message: result.data.errorCode ?? "导入作业未完成。",
        };
    } catch {
      return { ok: false, reason: "uncertain" };
    }
    await new Promise<void>((resolve) => window.setTimeout(resolve, 350));
  }
  return { ok: false, reason: "uncertain" };
}

/** Imports one user-selected file once. Uncertain outcomes are only queried. */
export async function importProjectMedia(
  projectId: string,
  purpose: "reference" | "speech" | "video" | "music" | "sfx" | "evidence",
): Promise<MediaImportResult> {
  if (!projectUuid.safeParse(projectId).success)
    return { ok: false, reason: "failure", message: "项目编号无效。" };
  const projects = bridge();
  if (!projects)
    return { ok: false, reason: "failure", message: "本地媒体服务不可用。" };

  let selection;
  try {
    selection = await projects.media.chooseFile({ purpose: "importMedia" });
  } catch {
    return { ok: false, reason: "failure", message: "无法选择本地图片。" };
  }
  if (!selection.ok)
    return { ok: false, reason: "failure", message: selection.error.message };
  if (!selection.data) return { ok: false, reason: "cancelled" };

  let current;
  try {
    current = await projects.drafts.project({ projectId });
  } catch {
    return { ok: false, reason: "failure", message: "无法读取项目版本。" };
  }
  if (!current.ok)
    return { ok: false, reason: "failure", message: current.error.message };
  const clientOperationId = crypto.randomUUID();
  const command = {
    clientOperationId,
    expectedRevision: current.data.revision,
    payload: { fileGrantId: selection.data.grantId, purpose },
  };
  let jobId: string | null = null;
  try {
    const submitted = await projects.media.import({ projectId, command });
    if (submitted.ok) jobId = submitted.data.resourceId;
    else if (uncertainCodes.has(submitted.error.code)) {
      const queried = await projects.drafts.operation({
        projectId,
        operationId: clientOperationId,
      });
      if (!queried.ok) return { ok: false, reason: "uncertain" };
      jobId = queried.data.receipt.resourceId;
    } else
      return { ok: false, reason: "failure", message: submitted.error.message };
  } catch {
    try {
      const queried = await projects.drafts.operation({
        projectId,
        operationId: clientOperationId,
      });
      if (!queried.ok) return { ok: false, reason: "uncertain" };
      jobId = queried.data.receipt.resourceId;
    } catch {
      return { ok: false, reason: "uncertain" };
    }
  }
  return jobId
    ? waitForImport(projectId, jobId, projects.media.job)
    : { ok: false, reason: "uncertain" };
}
