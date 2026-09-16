import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test, vi } from "vitest";
import {
  inspectCheckJob,
  receiptForPendingVersionOperation,
  RevisionComparison,
  validConfirmationReport,
} from "../../src/app/RevisionPanel";
import type {
  ArtifactState,
  CheckReport,
  Impact,
  Revision,
} from "../../electron/shared/versions";

const oldId = "00000000-0000-4000-8000-000000000001";
const newId = "00000000-0000-4000-8000-000000000002";
const artifactId = "00000000-0000-4000-8000-000000000003";
const sourceHash = "a".repeat(64);
const contentHash = "b".repeat(64);

function revision(id: string, sourceText: string): Revision {
  return {
    id,
    artifactId,
    parentId: id === oldId ? null : oldId,
    payload: {
      kind: "story",
      content: {
        sourceText,
        sourceHash,
        inputType: "idea",
        approvalLevel: "proposal",
        brief: `${sourceText}简报`,
        outline: [],
        requirements: [],
        scenes: [],
        dialogues: [],
        adaptationNotes: [],
      },
    },
    contentHash,
    createdAt: "2026-09-16T08:00:00Z",
  };
}

const artifact: ArtifactState = {
  id: artifactId,
  kind: "story",
  adoptedRevisionId: oldId,
  confirmedRevisionId: oldId,
  needsUpdate: false,
  latestAdoptionId: null,
};
const impact: Impact = {
  previewId: "00000000-0000-4000-8000-000000000004",
  artifactId,
  fromRevisionId: oldId,
  toRevisionId: newId,
  affectedArtifactIds: ["00000000-0000-4000-8000-000000000005"],
  affectedScopes: ["requirementCoverage", "export"],
  estimatedExtraMicroCny: null,
  requiredChecks: ["structural", "references"],
  expiresAt: "2026-09-16T08:05:00Z",
};

test("comparison keeps selected, adopted and confirmed states distinct without exposing hashes", () => {
  const html = renderToStaticMarkup(
    createElement(RevisionComparison, {
      artifact,
      adopted: revision(oldId, "当前采用的原文"),
      selected: revision(newId, "正在查看的候选"),
      impact,
      projectId: artifactId,
    }),
  );
  expect(html).toContain("当前采用");
  expect(html).toContain("当前确认");
  expect(html).toContain("正在查看");
  expect(html).toContain("当前采用的原文");
  expect(html).toContain("正在查看的候选");
  expect(html).toContain("额外费用暂时无法确定");
  expect(html).toContain("内容结构");
  expect(html).toContain("引用关系");
  expect(html).not.toContain(sourceHash);
  expect(html).not.toContain(contentHash);
  expect(html).not.toContain("<pre");
});

test("image comparison renders local thumbnails for both adopted and selected references", () => {
  const imageRevision = (id: string, mediaId: string): Revision => ({
    id,
    artifactId,
    parentId: null,
    payload: {
      kind: "asset",
      content: {
        assetType: "character",
        name: "门灯旅人",
        identityAnchors: ["深色雨衣"],
        allowedChanges: [],
        states: [],
        references: [
          {
            mediaId,
            mediaHash: "c".repeat(64),
            role: "identity",
            order: 0,
            state: "pending",
            keep: [],
            ignore: [],
            crop: null,
          },
        ],
      },
    },
    contentHash,
    createdAt: "2026-09-16T08:00:00Z",
  });
  const html = renderToStaticMarkup(
    createElement(RevisionComparison, {
      artifact,
      adopted: imageRevision(oldId, oldId),
      selected: imageRevision(newId, newId),
      impact: null,
      projectId: artifactId,
    }),
  );
  expect(html).toContain(`avi-media://local/${artifactId}/${oldId}`);
  expect(html).toContain(`avi-media://local/${artifactId}/${newId}`);
  expect(html.match(/<img/g)).toHaveLength(2);
});

test("confirmation requires a passing local report for the exact revision and every required rule", () => {
  const base: CheckReport = {
    id: "00000000-0000-4000-8000-000000000006",
    revisionIds: [newId],
    ruleIds: ["structural", "references"],
    outcome: "pass",
    issueIds: [],
    method: "local",
    observedRanges: [],
    evidenceMediaIds: [],
    ruleVersion: "local-structure-v1",
    limitations: "只检查确定性的内容结构和引用存在性。",
  };
  expect(
    validConfirmationReport(base, newId, ["structural", "references"]),
  ).toBe(true);
  expect(
    validConfirmationReport({ ...base, outcome: "unknown" }, newId, [
      "structural",
      "references",
    ]),
  ).toBe(false);
  expect(
    validConfirmationReport({ ...base, revisionIds: [oldId] }, newId, [
      "structural",
      "references",
    ]),
  ).toBe(false);
  expect(
    validConfirmationReport({ ...base, ruleIds: ["structural"] }, newId, [
      "structural",
      "references",
    ]),
  ).toBe(false);
  expect(
    validConfirmationReport({ ...base, method: "ai" }, newId, [
      "structural",
      "references",
    ]),
  ).toBe(false);
});

test("a failed job read retains the accepted check job for a same-job retry", async () => {
  const handle = { jobId: newId, targetRevisionId: oldId };
  const getReport = vi.fn();
  const result = await inspectCheckJob(
    handle,
    async () => ({
      ok: false as const,
      error: { code: "BACKEND_UNAVAILABLE", message: "暂时无法连接" },
    }),
    getReport,
  );
  expect(result).toEqual({
    state: "retry",
    handle,
    message: "暂时无法连接",
  });
  expect(getReport).not.toHaveBeenCalled();
});

test("a direct version receipt with another operation id remains pending", () => {
  const pending = {
    kind: "create" as const,
    operationId: oldId,
    expectedRevision: 3,
  };
  expect(
    receiptForPendingVersionOperation(pending, newId, {
      operationId: newId,
      committedRevision: 4,
      resourceId: artifactId,
      state: "committed",
    }),
  ).toBeNull();
});

test("an operation lookup with a mismatched nested receipt remains pending", () => {
  const pending = {
    kind: "create" as const,
    operationId: oldId,
    expectedRevision: 3,
  };
  expect(
    receiptForPendingVersionOperation(pending, oldId, {
      operationId: newId,
      committedRevision: 4,
      resourceId: artifactId,
      state: "committed",
    }),
  ).toBeNull();
});
