# Episode Production Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the seven passive sections of the episode detail page with an interactive, persistent five-stage production demo, including two storyboard-image modes and local review/rollback states.

**Architecture:** Keep the existing project/episode entry and Ant Design visual world. Put versioned episode state, dependency transitions, nine-grid grouping, and deterministic demo fixtures in focused pure modules; keep the page as an orchestrator with one component per stage. Reuse existing project-media bridge for genuine local imports, but never call model-generation APIs.

**Tech Stack:** Electron, React 19, TypeScript 5.9, Ant Design 5, Vitest 5, Playwright/Electron, localStorage, existing `window.desktop.projects.media` bridge.

**Spec:** `docs/superpowers/specs/2026-09-17-episode-production-flow-design.md`

## Global Constraints

- Scope: episode detail page and necessary frontend state/components/styles/tests; no backend, real AI task, global AI configuration, project-detail layout, audio/edit/export changes.
- Five stages: source/script generation; script approval/asset extraction; asset images; storyboard script/images; shot videos.
- Aspect is `16:9` or `9:16` in stage two; **do not add resolution/clarity input** on the episode page. Default aspect/style from `readProjectDetails` and `session.project.aspect`.
- All simulated model choices/results say “演示”; no API, charges, fake service connection, or claims of accurate extraction from arbitrary novel text.
- All source, approved snapshots, candidates and adopted IDs remain separate; edits mark only dependent downstream items stale and preserve prior candidates.
- Nine-grid has at most nine distinct shots per batch, each cell permanently bound to a shot ID; the full sheet is never used as one shot's video input.
- No image/video binary, paths, or credentials in localStorage. Store only demo IDs or project-media IDs and check real media availability.
- Preserve the currently dirty worktree. `EpisodePage.tsx`, `project-detail-model.ts`, `studio.css`, and `ProjectsPage.tsx` are currently untracked user-owned files; read their current contents before edits and never replace them from Git. Do not commit their pre-existing content implicitly. Stage only explicitly owned new files; if a coherent commit cannot exclude pre-existing changes, leave the checkpoint uncommitted and report it.
- The shell `pnpm` wrapper currently tries to rebuild `node_modules` and aborts without a TTY. Use the already installed scripts with the bundled Node `C:/Users/snow/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe` directly; baseline `tsc -p tsconfig.web.json` passed this way. Do not purge dependencies to fix the wrapper.

## File map and contracts

- `frontend/src/features/projects/episode-workflow.ts`: version-2 state, safe legacy migration, localStorage persistence and review transitions. Export `readWorkflow`, `saveWorkflow`, `emptyWorkflow`, `stageStatus`, `editScript`, `editAsset`, `editShot`, `adoptFrame`, and the types below.
- `frontend/src/features/projects/episode-grid.ts`: stable group/cell mapping and reordering; export `groupShotIds`, `createGridBatches`, `bindGridCell`.
- `frontend/src/features/projects/episode-demo.ts`: labeled model options, deterministic sample script/assets/shots/image IDs and motion previews; export `DEMO_MODELS`, `sampleScript`, `sampleAssets`, `sampleShots`, `sampleImage`, `sampleMotion`.
- `frontend/src/features/projects/episode-media.ts`: typed `mediaUrl`, project-media listing, import/query/poll wrapper; never embeds file paths in renderer state.
- `frontend/src/pages/projects/EpisodePage.tsx`: state owner, scroll navigation, saving/error banner, media availability and stage callbacks; retain its existing public props and add `ready`.
- `frontend/src/pages/projects/episode/StageNav.tsx`, `SourceStage.tsx`, `ScriptStage.tsx`, `AssetsStage.tsx`, `StoryboardStage.tsx`, `VideoStage.tsx`: focused presentational editors using typed data/callback props; no direct localStorage access.
- `frontend/src/features/assets/asset-model.ts` and `frontend/src/features/projects/project-detail-model.ts`: optional validated `visualRef` on a shared resource, without changing existing resources or project-detail UI.
- `frontend/src/pages/projects/ProjectsPage.tsx`: forward the existing `ready` value to `EpisodePage`; no navigation redesign.
- `frontend/src/app/studio.css`: replace only the `.episode-*` section and related narrow-screen rules needed for five-stage layout; preserve unrelated styles.
- `frontend/tests/episode/*.test.ts(x)`: focused pure-state, server-rendered structure and demo-boundary tests. `frontend/tests/episode-e2e/flow.spec.ts` plus `frontend/playwright.episode.config.ts`: Electron flow test separate from the deleted general e2e config.

Shared shape for tasks (define exactly in `episode-workflow.ts`):

```ts
export type StageId = "source" | "script" | "assets" | "storyboard" | "video";
export type Review = "not_started" | "review" | "confirmed" | "stale";
export type DemoRun = "idle" | "preparing" | "running" | "failed";
export type MediaRef = { kind: "demo-image" | "demo-motion" | "project-image" | "project-video"; id: string };
export type Candidate<T> = { id: string; value: T; source: "demo" | "manual" | "import"; usableForVideo?: boolean };
export type AssetItem = { id: string; kind: "character" | "scene" | "prop"; name: string; description: string; linkedResourceId: string | null; imageCandidates: Candidate<MediaRef>[]; selectedImageId: string | null; review: Review };
export type ShotItem = { id: string; title: string; description: string; action: string; dialogue: string; plannedMs: number; assetIds: string[]; review: Review; firstFrames: Candidate<MediaRef>[]; selectedFirstId: string | null; endFrames: Candidate<MediaRef>[]; selectedEndId: string | null; videos: Candidate<MediaRef>[]; selectedVideoId: string | null; frameReview: Review; videoReview: Review };
export type GridBatch = { id: string; sheet: MediaRef; cells: { index: number; shotId: string; ref: MediaRef | null; review: Review }[] };
export type EpisodeWorkflow = { version: 2; novel: string; scriptDraft: string; scriptCandidates: Candidate<string>[]; approvedScript: { text: string; aspect: "16:9" | "9:16"; style: string } | null; aspect: "16:9" | "9:16"; style: string; models: { script: string; analysis: string; assetImage: string; storyboardText: string; storyboardImage: string; video: string }; assets: AssetItem[]; shots: ShotItem[]; gridBatches: GridBatch[]; storyboardMode: "frames" | "grid"; reviews: Record<StageId, Review>; legacyNotes: { characters: string; props: string; scenes: string; imagePrompt: string; videoPrompt: string } };
```

---

### Task 1: Versioned episode state and legacy migration

**Files:** Create `frontend/src/features/projects/episode-workflow.ts`; test `frontend/tests/episode/workflow.test.ts`. Consume `readEpisodeDraft` and `readProjectDetails` from `project-detail-model.ts`. Produce the shared types and `readWorkflow(projectId, episodeId, defaults, storage?)`, `saveWorkflow(projectId, episodeId, value, storage?)`, `emptyWorkflow(defaults)`.

- [ ] **Step 1: Write failing tests.** Use a memory `Storage` implementation and write an old key `avi-episode-draft-p-e` containing `script`, `shots`, `characters`, `props`, `scenes`, `imagePrompt`, `videoPrompt`. Assert `readWorkflow("p", "e", {aspect:"16:9",style:"写实"}, storage)` has version 2, unchanged script/shot ID/legacy notes, and does not mutate old storage. Add a second test where `setItem` throws `QuotaExceededError`; `saveWorkflow` returns `{ok:false}` and never reports success.

```ts
expect(readWorkflow("p", "e", { aspect: "16:9", style: "写实" }, storage)).toMatchObject({
  version: 2, scriptDraft: "旧剧本", shots: [{ id: "shot-1", description: "街口" }],
  legacyNotes: { characters: "阿遥", imagePrompt: "雨夜" },
});
expect(saveWorkflow("p", "e", state, throwingStorage).ok).toBe(false);
```

- [ ] **Step 2: Run red.** In `frontend`: `& "C:/Users/snow/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe" node_modules/vitest/vitest.mjs run tests/episode/workflow.test.ts`; expected missing module/exports.
- [ ] **Step 3: Implement.** Parse the V2 key `avi-episode-workflow-v2-${projectId}-${episodeId}` defensively, validate `version === 2` and required arrays/fields, otherwise map the legacy `readEpisodeDraft(projectId, episodeId, storage)`. Return a fresh state; do not write during read. `saveWorkflow` wraps `storage.setItem` in `try/catch` and returns `{ok:true}` or `{ok:false,error:"本集内容未能保存，请检查本地空间。"}`. Preserve the old notes even if the five-stage UI does not expose them immediately.

```ts
export function saveWorkflow(projectId: string, episodeId: string, value: EpisodeWorkflow, storage: Pick<Storage, "setItem"> = localStorage) {
  try { storage.setItem(`avi-episode-workflow-v2-${projectId}-${episodeId}`, JSON.stringify(value)); return { ok: true } as const; }
  catch { return { ok: false, error: "本集内容未能保存，请检查本地空间。" } as const; }
}
```

- [ ] **Step 4: Run green + typecheck.** Run the focused test and `node_modules/typescript/bin/tsc -p tsconfig.web.json` via the bundled Node. Check that other episodes use separate keys.
- [ ] **Step 5: Checkpoint.** Stage only the two newly created files if independently committable; never stage unrelated dirty files.

### Task 2: Partial invalidation and nine-grid identity

**Files:** Create `frontend/src/features/projects/episode-grid.ts`; modify `episode-workflow.ts`; test `frontend/tests/episode/dependencies.test.ts` and `grid.test.ts`. Consume the shared state types. Produce `editScript(state,text)`, `editAsset(state,id,patch)`, `editShot(state,id,patch)`, `adoptFrame(state,shotId,role,candidateId)`, `groupShotIds(ids)`, `createGridBatches(ids,sheetFactory)`, `bindGridCell(batch,index,shotId,ref)` and `stageStatus(state,id)`.

- [ ] **Step 1: Write failing tests.** Confirm script edits preserve all prior candidates while marking assets/storyboard/video stale. Confirm editing asset A marks only shots referring to A stale; editing shot S leaves another shot T unchanged; adopting a new frame marks only S video stale. Confirm ten shots form groups of 9 and 1; after reorder, `cells[0].shotId` remains the original shot ID. Reject `bindGridCell` for a shot ID not listed in that batch.

```ts
expect(groupShotIds(Array.from({ length: 10 }, (_, i) => `s${i}`)).map(x => x.length)).toEqual([9, 1]);
expect(editAsset(state, "asset-a", { description: "蓝外套" }).shots.find(s => s.id === "shot-b")?.videoReview).toBe("confirmed");
expect(bindGridCell(batch, 0, "not-in-batch", ref)).toEqual(batch);
```

- [ ] **Step 2: Run red.** Run both focused files with the installed Vitest script; expected missing exports.
- [ ] **Step 3: Implement.** Use immutable maps keyed by stable IDs, leave `videos`, `firstFrames`, `endFrames` and `gridBatches` intact, and change only review flags. `groupShotIds` uses slices of length 9. `createGridBatches` captures shot IDs at generation time and sets `index` from 0 to at most 8. `stageStatus` returns the explicit stage review with dependent stale status taking precedence; never infer confirmation merely from populated text.

```ts
export const groupShotIds = (ids: readonly string[]) => Array.from(
  { length: Math.ceil(ids.length / 9) }, (_, n) => ids.slice(n * 9, n * 9 + 9),
);
export function editAsset(state: EpisodeWorkflow, id: string, patch: Pick<AssetItem, "name" | "description">): EpisodeWorkflow {
  return { ...state, assets: state.assets.map(a => a.id === id ? { ...a, ...patch, review: "review" } : a),
    shots: state.shots.map(s => s.assetIds.includes(id) ? { ...s, frameReview: "stale", videoReview: "stale" } : s),
    reviews: { ...state.reviews, assets: "review", storyboard: "stale", video: "stale" } };
}
```

- [ ] **Step 4: Run green + typecheck.** Verify local dependency isolation, group membership and 0/9/10 shot boundaries.
- [ ] **Step 5: Checkpoint.** Commit only files owned by this task if safe; otherwise retain test results without sweeping user changes.

### Task 3: Truthful deterministic demo results

**Files:** Create `frontend/src/features/projects/episode-demo.ts`; test `frontend/tests/episode/demo.test.ts`. Consume `AssetItem`, `ShotItem`, `MediaRef`, `Candidate` types. Produce `DEMO_MODELS` and `sampleScript(novel)`, `sampleAssets()`, `sampleShots(script)`, `sampleImage(seed)`, `sampleMotion(shotId)`.

- [ ] **Step 1: Write failing tests.** Assert empty input produces no candidate, repeated input gives the same labeled sample text, generic asset names do not pretend to extract arbitrary names, distinct shot IDs are generated, and image/motion refs have `demo-*` kinds rather than project-media kinds.

```ts
expect(sampleScript("  ")).toBeNull();
expect(sampleScript("雨夜有人借灯")).toEqual(sampleScript("雨夜有人借灯"));
expect(sampleImage("s1").kind).toBe("demo-image");
expect(sampleMotion("s1").kind).toBe("demo-motion");
```

- [ ] **Step 2: Run red.** Run `tests/episode/demo.test.ts`; expected missing exports.
- [ ] **Step 3: Implement.** Use two named demo choices A/B for each phase so the selector is operable; both run the same deterministic local fixture logic but persist the chosen option. Make script a visibly labeled editable scaffold quoting a short input excerpt; asset cards use `角色 A`/`场景 A`/`道具 A` and require correction by the user. Derive fixture IDs from stable input/shot IDs; generate no HTTP requests, random costs, or fake MP4. Keep demo visual refs as bundled/code-native illustration IDs, not binary in storage.

```ts
export const DEMO_MODELS = {
  script: ["A", "B"].map(x => ({ value: `demo-script-${x}`, label: `演示·剧本模型 ${x}` })),
  analysis: ["A", "B"].map(x => ({ value: `demo-analysis-${x}`, label: `演示·素材分析模型 ${x}` })),
  assetImage: ["A", "B"].map(x => ({ value: `demo-image-${x}`, label: `演示·文生图模型 ${x}` })),
  storyboardText: ["A", "B"].map(x => ({ value: `demo-storyboard-${x}`, label: `演示·分镜模型 ${x}` })),
  storyboardImage: ["A", "B"].map(x => ({ value: `demo-frame-${x}`, label: `演示·分镜图模型 ${x}` })),
  video: ["A", "B"].map(x => ({ value: `demo-video-${x}`, label: `演示·图生视频模型 ${x}` })),
} as const;
```

- [ ] **Step 4: Run green + typecheck.** Verify deterministic IDs and explicit demo labeling.
- [ ] **Step 5: Checkpoint.** Stage only the new demo module and test if safe.

### Task 4: Five-stage shell, novel and script review

**Files:** Replace only the episode implementation in `frontend/src/pages/projects/EpisodePage.tsx`; create `frontend/src/pages/projects/episode/StageNav.tsx`, `SourceStage.tsx`, `ScriptStage.tsx`; modify `frontend/src/pages/projects/ProjectsPage.tsx` to forward `ready`; update episode-only selectors in `frontend/src/app/studio.css`; test `frontend/tests/episode/stages.test.tsx`.

**Interfaces:** Consume `readWorkflow/saveWorkflow`, `DEMO_MODELS`, `sampleScript`, `stageStatus`. `EpisodePage` retains `session`, `episode`, `number`, `onBack` and adds `ready: boolean`; each stage receives state plus typed callbacks, never storage directly.

- [ ] **Step 1: Write failing structure tests.** Server-render `SourceStage`, `ScriptStage`, and `StageNav`; assert labels “本集小说”“剧本生成模型”“画幅比例”“视觉风格” and exactly five navigation items, with no “清晰度”. Test script candidate selection callback contract and a read-only prop that disables mutation actions.

```tsx
const markup = renderToStaticMarkup(<StageNav active="source" reviews={state.reviews} onSelect={() => {}} />);
expect(markup.match(/episode-stage-link/g)).toHaveLength(5);
expect(renderToStaticMarkup(<ScriptStage value={state} readOnly onChange={() => {}} />)).not.toContain("清晰度");
```

- [ ] **Step 2: Run red.** Run `tests/episode/stages.test.tsx`; expected components missing.
- [ ] **Step 3: Implement.** Keep the existing `EpisodePage` header and scroll-aware active step behavior (`activeStepIndex`), change step IDs to five stages, load by project/episode key, display a persistent “交互演示” banner and visible save error/status. `SourceStage` stores novel and explicit candidate selection; `ScriptStage` edits script, compares source, chooses aspect/style/analysis model, confirms a snapshot then creates editable asset candidates. Use one primary action per stage. Call `saveWorkflow` on every user mutation and only update visible “已保存” after success; disable edits for `session.mode === "read"` and media mutations while `!ready`. Do not introduce a second global sidebar or change other pages.

```tsx
<EpisodePage session={session} episode={episode} number={number} ready={ready} onBack={returnToProject} />
```

- [ ] **Step 4: Run green + typecheck.** Test navigation/markup, verify the old example episode still opens, and inspect desktop/narrow layout once after all five stages land.
- [ ] **Step 5: Checkpoint.** Do not commit the pre-existing untracked page, CSS or `ProjectsPage.tsx` as if they were newly authored; retain the diff for review.

### Task 5: Asset review, sharing and genuine local media binding

**Files:** Create `frontend/src/pages/projects/episode/AssetsStage.tsx` and `frontend/src/features/projects/episode-media.ts`; modify `frontend/src/features/assets/asset-model.ts`, `frontend/src/features/projects/project-detail-model.ts` only for optional `visualRef`; test `frontend/tests/episode/assets.test.ts(x)` and `media.test.ts`.

**Interfaces:** Consume `AssetItem`, `MediaRef`, `readProjectResources/saveProjectResources`, and `window.desktop.projects.media`; produce `listUsableMediaResult(items,mimePrefix)`, `listUsableMedia(projectId,mimePrefix)`, `mediaUrl(projectId,mediaId)`, and `importProjectMedia(projectId,purpose)` returning either `{ok:true,mediaId}` or a typed failure/unknown result. `GlobalAsset.visualRef` accepts only image refs (`demo-image` or `project-image`), never motion/video refs.

- [ ] **Step 1: Write failing tests.** Assert demo image selection does not create a `project-image` ref; sharing an asset preserves an existing `GlobalAsset.id`; duplicate names prompt explicit link/create choice; `validAsset` accepts optional `{kind:"project-image",id}` and rejects malformed refs. Assert `mediaUrl` only constructs `avi-media://local/${projectId}/${mediaId}` for validated UUIDs and import uncertainty does not trigger a second call.

```ts
expect(validAsset({ ...resource, visualRef: { kind: "project-image", id: mediaId } })).toBe(true);
expect(listUsableMediaResult([{ id: mediaId, mime: "video/mp4", availability: "available" }], "image/")).toEqual([]);
```

- [ ] **Step 2: Run red.** Run both asset/media tests; expected missing module or optional-field support.
- [ ] **Step 3: Implement.** Render editable grouped cards, project-resource link/create decision, per-item demo image candidates, adopted preview and confirm action. Extend `GlobalAsset` with optional `visualRef: MediaRef` and validate it without invalidating old cards. For genuine media, call `chooseFile({purpose:"importMedia"})`, get the latest project revision from `window.desktop.projects.drafts.project`, submit `media.import` once with stable `clientOperationId`, query the same operation if result is uncertain, then poll its job until `succeeded` and bind `resultId`; show failure/missing/relocation states. Existing media can be selected from `media.list`; show only available images. Store media ID, never a file path, and render through the registered `avi-media://` scheme.

```ts
export function mediaUrl(projectId: string, mediaId: string) {
  if (!projectUuid.safeParse(projectId).success || !projectUuid.safeParse(mediaId).success) return null;
  return `avi-media://local/${projectId}/${mediaId}`;
}
```

- [ ] **Step 4: Run green + typecheck.** Test old resources still load, import errors do not erase candidate cards, and unavailable media cannot be confirmed as usable.
- [ ] **Step 5: Checkpoint.** Only commit new independently owned files; leave dirty existing files untouched in staging.

### Task 6: Shot script, first/end frames and nine-grid mapping

**Files:** Create `frontend/src/pages/projects/episode/StoryboardStage.tsx`; modify `EpisodePage.tsx` episode-specific wiring and `.episode-*` styles; test `frontend/tests/episode/storyboard.test.tsx` and `grid.test.ts`.

**Interfaces:** Consume `ShotItem`, `GridBatch`, `groupShotIds/createGridBatches/bindGridCell`, `sampleShots/sampleImage`, `editShot/adoptFrame`. Expose `onReorder(shotIds)`, `onCreateGrid()`, `onBindCell(batchId,index,shotId,ref)` callbacks.

- [ ] **Step 1: Write failing tests.** Server-render both mode selectors and a nine-grid of nine cells; assert 10 shots produce two batches, a cell retains its original shot label after reorder, a whole-sheet ref cannot be selected as one shot's first frame, and a tail-frame note says unsupported video models may treat it as review-only. Test static preview is labeled “静态预览”.

```ts
expect(createGridBatches(ids10, () => sheetRef)).toHaveLength(2);
expect(createGridBatches(ids10, () => sheetRef)[1].cells.map(c => c.shotId)).toEqual(["shot-10"]);
```

- [ ] **Step 2: Run red.** Run storyboard/grid tests; expected stage not found or missing behavior.
- [ ] **Step 3: Implement.** Provide script-model choice and editable stable shot cards with reordering, asset associations, dialogue/action/duration. Offer an image-model choice followed by “首尾帧” or “九宫格” mode. The former keeps separate first/end candidates; the latter creates at most nine fixed mappings per sheet, offers per-cell review/selection and a visually distinct “仅供分镜参考” badge when unsuitable. Switching modes preserves prior candidates. The static preview uses adopted shot images in order with planned duration but makes no video claim.

```tsx
<button type="button" aria-pressed={value.storyboardMode === "frames"} onClick={() => onMode("frames")}>首尾帧</button>
<button type="button" aria-pressed={value.storyboardMode === "grid"} onClick={() => onMode("grid")}>九宫格分镜</button>
```

- [ ] **Step 4: Run green + typecheck.** Verify first/end adoption is independent, nine-grid group boundaries and stable ID mapping survive save/reload.
- [ ] **Step 5: Checkpoint.** Preserve existing dirty page/style content; stage only isolated new files when safe.

### Task 7: Per-shot video, recovery and end-to-end proof

**Files:** Create `frontend/src/pages/projects/episode/VideoStage.tsx`, `frontend/tests/episode/video.test.tsx`, `frontend/tests/episode-e2e/flow.spec.ts`, `frontend/playwright.episode.config.ts`; finish `EpisodePage.tsx` orchestration, `episode-media.ts`, and episode-only styles.

**Interfaces:** Consume `ShotItem.selectedFirstId`, candidate `MediaRef`s, `sampleMotion`, media availability, and stage `Review`. Produce per-shot active/demo/failure/review/confirmed UI, no export controls.

- [ ] **Step 1: Write failing tests.** Test that an unconfirmed, grid-sheet-only or `usableForVideo:false` image blocks video input with a reason, per-shot demo generation leaves another shot untouched, failure/retry preserves prior candidates, imported `project-video` uses `<video controls>` while `demo-motion` is explicitly labeled non-video. E2E creates/opens one episode, enters novel, creates and approves script/assets, builds 10 shots, tests two nine-grid batches, refreshes, edits one shot and sees only its video become stale.

```tsx
expect(renderToStaticMarkup(<VideoStage value={state} readOnly={false} onChange={() => {}} />)).toContain("交互演示");
expect(canGenerateVideo({ ...shot, selectedFirstId: null })).toEqual({ ok: false, reason: "请先选定本镜可用的单幅分镜图" });
```

- [ ] **Step 2: Run red.** Run focused video tests, then the new e2e test against a built Electron app; expected missing component/flow. Put Electron windows offscreen with `AVI_E2E_OFFSCREEN_WINDOW=1`; use temporary project directories under `../.cache` and do not show an interactive window.
- [ ] **Step 3: Implement.** One shot at a time; select the demo video model, show a visibly simulated motion preview for demo candidates and a real player only for imported MP4. Never promote a whole grid sheet or low-quality review tile to a valid video input. Persist candidate IDs/reviews; on reload clear transient simulated `running` states to `review`/`idle` and retain previous outputs. Add informative empty/error/readonly states, a five-stage completion summary (“演示流程完成，非成片”), and no sound/edit/export claim. Finish visible focus, responsive navigation and reduced-motion scroll behavior.

```ts
export function canGenerateVideo(shot: ShotItem) {
  const selected = shot.firstFrames.find(c => c.id === shot.selectedFirstId);
  return selected?.usableForVideo === true
    ? { ok: true } as const
    : { ok: false, reason: "请先选定本镜可用的单幅分镜图" } as const;
}
```

- [ ] **Step 4: Run green and verify.** From `frontend`, run focused Vitest tests, both TypeScript projects, Electron build, and the isolated e2e config. Inspect desktop and narrow viewport once, batch-fix defects, confirm with at most one more visual pass. Verify `git diff --check` on owned files and confirm no real model request occurred.
- [ ] **Step 5: Handoff checkpoint.** Report passing/failing commands, known demo limitations, and all file changes. Do not auto-stage pre-existing user changes; make a code commit only if it can be isolated safely.

## Verification commands

Run in `frontend` PowerShell using the installed scripts without invoking the `pnpm` wrapper:

```powershell
$taskNode = "C:/Users/snow/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
& $taskNode node_modules/vitest/vitest.mjs run tests/episode
& $taskNode node_modules/typescript/bin/tsc -p tsconfig.web.json
& $taskNode node_modules/typescript/bin/tsc -p tsconfig.node.json
& $taskNode node_modules/electron-vite/bin/electron-vite.js build
& $taskNode node_modules/@playwright/test/cli.js test -c playwright.episode.config.ts
```

If the existing backend/toolchain cannot start the Electron e2e run, record the exact failure; pure state, renderer typecheck and build must still be independently verified. Do not claim real AI quality or billing behavior from this demo.
