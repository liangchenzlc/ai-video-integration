# Studio Ant Design Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the six approved blue-and-white layout and interaction changes while keeping the existing Electron project workflows intact.

**Architecture:** Add one Ant Design theme at the renderer root and migrate reusable controls only in the affected surfaces. Keep page-level state and storage as-is; make the episode page a continuous document with a small pure scroll-selection helper and sticky navigation. Move, rather than delete, the existing close-project action out of the information card so closing remains possible.

**Tech Stack:** React 19, TypeScript 5.9, Electron 44, Ant Design 5, Vitest 5, Playwright Electron.

**Spec:** `docs/superpowers/specs/2026-09-17-studio-layout-ant-design.md`

## Global Constraints

- Target Ant Design primary blue `#1677ff`, white `#ffffff`, workspace `#f5f8fc`, border `#d9e3ef`; Windows Chinese-first font `Microsoft YaHei UI` and `Segoe UI` for Latin/numerals.
- Keep the existing data structures, Electron bridge, local draft persistence, busy/error states, and unrelated AI configuration flow unchanged.
- Story synopsis spans one complete layout row but remains a multiline field with the existing 2000-character limit.
- All Electron E2E runs inherit `AVI_E2E_OFFSCREEN_WINDOW=1`; assert window x-coordinate below -10000 and do not show or focus it.
- Preserve pre-existing uncommitted changes. Do not stage/commit mixed-ownership files without a clean ownership review; task checkpoints may remain uncommitted.

## File map

- `frontend/package.json`, `frontend/pnpm-lock.yaml`: Ant Design dependency.
- `frontend/src/main.tsx`: `ConfigProvider` and Chinese locale.
- `frontend/src/app/styles.css`, `frontend/src/app/studio.css`: shared theme compatibility, targeted layout and responsive rules.
- `frontend/src/components/layout/Sidebar.tsx`: collapsible asset submenu.
- `frontend/src/pages/projects/ProjectsPage.tsx`: right-aligned actions and transfer close action to the detail header.
- `frontend/src/features/projects/ProjectDetailHeader.tsx`: close-project header action.
- `frontend/src/features/projects/ProjectOverview.tsx`, `ProjectCard.tsx`, `ProjectCreateForm.tsx`: information layout and reusable controls/cards.
- `frontend/src/pages/assets/AssetsPage.tsx`, `frontend/src/features/assets/AssetCard.tsx`, `AssetForm.tsx`: buttons, cards and input controls shared by global/project asset views.
- `frontend/src/pages/projects/EpisodePage.tsx`: seven concurrently mounted sections, navigation, step controls.
- `frontend/src/pages/projects/episode-scroll.ts`, `frontend/tests/runtime/episode-scroll.test.ts`: pure active-step calculation and unit tests.
- `frontend/tests/e2e/studio-navigation.spec.ts`: add UI checks within the existing offscreen Electron scenario.

## Task 1: Theme and collapsible asset navigation

**Files:** Modify `frontend/package.json`, `frontend/pnpm-lock.yaml`, `frontend/src/main.tsx`, `frontend/src/components/layout/Sidebar.tsx`, `frontend/src/app/styles.css`, `frontend/src/app/studio.css`; test `frontend/tests/e2e/studio-navigation.spec.ts`.

**Interfaces:** `Sidebar` retains `{page, kind, onSelect}`; asset IDs remain `character | scene | prop`. Renderer receives `ConfigProvider` without changing `App` props.

- [ ] **Step 1: Add the failing offscreen E2E assertions** immediately after the initial project heading assertion in `studio-navigation.spec.ts`:

```ts
const assetToggle = page.getByRole("button", { name: "收起素材库分类" });
await expect(assetToggle).toHaveAttribute("aria-expanded", "true");
await assetToggle.click();
await expect(page.getByRole("button", { name: "角色", exact: true })).toBeHidden();
await page.getByRole("button", { name: "展开素材库分类" }).click();
await expect(page.getByRole("button", { name: "角色", exact: true })).toBeVisible();
```

- [ ] **Step 2: Confirm the test fails for the absent toggle.** Run `cd frontend; pnpm test:e2e tests/e2e/studio-navigation.spec.ts --grep "share the new desktop navigation"`. Expected: timeout locating “收起素材库分类”; no visible Electron window.
- [ ] **Step 3: Install Ant Design and wrap the renderer.** Run `cd frontend; pnpm add antd@^5`; put `ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: "#1677ff", colorBgLayout: "#f5f8fc", colorBorder: "#d9e3ef", fontFamily: '"Microsoft YaHei UI", "Segoe UI", sans-serif' } }}` around `<App />` in `main.tsx`. In `Sidebar.tsx`, keep its existing “素材库” navigation button, add a separate named toggle with `aria-controls="asset-subnav"`, `aria-expanded={expanded}`, and `setExpanded(!expanded)`; render submenu `id="asset-subnav" hidden={!expanded}`. Clicking the main asset button calls `setExpanded(true)` then `onSelect("assets", kind)`. Add a meaningful chevron indicator that rotates, and scope legacy global button rules with `:not(.ant-btn)` so Ant buttons use their own styling.

```tsx
const [expanded, setExpanded] = useState(true);
<button aria-label={expanded ? "收起素材库分类" : "展开素材库分类"}
  aria-controls="asset-subnav" aria-expanded={expanded}
  onClick={() => setExpanded((value) => !value)}>
  <span aria-hidden="true">⌄</span>
</button>
<div id="asset-subnav" className="studio-subnav" hidden={!expanded}>
  {([["character", "角色"], ["scene", "场景"], ["prop", "道具"]] as const)
    .map(([value, label]) => (
      <button key={value} onClick={() => onSelect("assets", value)}>{label}</button>
    ))}
</div>
```

- [ ] **Step 4: Verify and checkpoint.** Run `pnpm typecheck` and the focused E2E test from `frontend`; check the offscreen assertion already present in the test still passes. Review only Task 1 diffs; do not stage any pre-existing changes merely for a checkpoint.

## Task 2: Project pages and reusable controls

**Files:** Modify `frontend/src/pages/projects/ProjectsPage.tsx`, `frontend/src/features/projects/ProjectDetailHeader.tsx`, `ProjectOverview.tsx`, `ProjectCard.tsx`, `ProjectCreateForm.tsx`, `frontend/src/pages/assets/AssetsPage.tsx`, `frontend/src/features/assets/AssetCard.tsx`, `AssetForm.tsx`, `frontend/src/app/studio.css`; test `frontend/tests/e2e/studio-navigation.spec.ts`.

**Interfaces:** `ProjectDetailHeader` gains `onClose: () => void` and `canClose: boolean`; `ProjectOverview` no longer consumes `onClose`/`canClose`. The underlying `closeProject()` in `ProjectsPage` and `updateDetails()` in `ProjectOverview` stay intact.

- [ ] **Step 1: Add failing assertions** in the existing project-detail part of `studio-navigation.spec.ts`, after the “剧集信息” heading is visible:

```ts
const info = page.getByRole("region", { name: "剧集信息" });
await expect(info.getByRole("button", { name: "关闭项目" })).toHaveCount(0);
await expect(page.getByRole("button", { name: "关闭项目" })).toBeVisible();
await expect(info.getByLabel("故事梗概")).toBeVisible();
await expect(info.getByLabel("图片 / 视频风格")).toBeVisible();
const infoRows = await info.evaluate((node) => {
  const style = node.querySelector("[data-project-style]")!.getBoundingClientRect();
  const synopsis = node.querySelector("[data-project-synopsis]")!.getBoundingClientRect();
  return { styleTop: style.top, synopsisTop: synopsis.top, synopsisWidth: synopsis.width, cardWidth: node.getBoundingClientRect().width };
});
expect(infoRows.synopsisTop).toBeGreaterThan(infoRows.styleTop);
expect(infoRows.synopsisWidth).toBeGreaterThan(infoRows.cardWidth * 0.7);
```

Also assert on the project list that `.project-actions` ends within 4px of the containing `.studio-main` content edge; keep existing field persistence assertions:

```ts
const alignment = await page.locator(".project-actions").first().evaluate((node) => {
  const content = node.closest(".studio-main")!;
  const action = node.querySelector("button:last-child")!;
  return Math.abs(content.getBoundingClientRect().right - action.getBoundingClientRect().right);
});
expect(alignment).toBeLessThan(5);
```
- [ ] **Step 2: Confirm assertions fail.** Run focused E2E; expected: close action still inside the card and project controls left-aligned.
- [ ] **Step 3: Replace generic controls and implement layout.** Use Ant `Button` on list/detail/asset actions and Ant `Card` for actual card containers. Preserve accessible button semantics: `ProjectCard` should render a `Card` containing one full-area `<button aria-label={...}>`, never a `Card` nested within `<button>`. Use `Input`, `Input.TextArea`, and controlled values in project and asset forms, keeping `label` associations stable with `htmlFor`/`id` where required. Move the existing close action into `ProjectDetailHeader` with `disabled={!canClose}`. Make `.project-actions` in list view `justify-content: flex-end`, first row of `.overview-info` grid with name / editable style / read-only aspect, and second row a full-span synopsis field. Mark the two fields with `data-project-style` and `data-project-synopsis` for geometry assertions.

```tsx
<ProjectDetailHeader session={session} onBack={returnToList}
  onClose={() => void closeProject()} canClose={ready && !busy && !leaving} />
<div className="overview-top-row">
  <h3>{session.project.name}</h3>
  <label data-project-style htmlFor="project-style">图片 / 视频风格
    <Input id="project-style" value={details.style} maxLength={100}
      onChange={(event) => updateDetails({ style: event.target.value })} />
  </label>
  <span className="overview-aspect">{session.project.aspect} {session.project.aspect === "9:16" ? "竖屏" : "横屏"}</span>
</div>
<label className="overview-synopsis" data-project-synopsis htmlFor="project-synopsis">故事梗概
  <Input.TextArea id="project-synopsis" rows={3} maxLength={2000}
    value={details.synopsis}
    onChange={(event) => updateDetails({ synopsis: event.target.value })} />
</label>
```

- [ ] **Step 4: Verify and checkpoint.** Run `pnpm typecheck`, `pnpm test -- tests/runtime/project-detail-model.test.ts tests/runtime/global-assets.test.ts`, and focused E2E. Inspect desktop and 680px layouts from offscreen snapshots; retain existing success/error/busy behavior. Review the Task 2 diff without staging unrelated content.

## Task 3: Continuous episode page and bidirectional navigation

**Files:** Create `frontend/src/pages/projects/episode-scroll.ts`, `frontend/tests/runtime/episode-scroll.test.ts`; modify `frontend/src/pages/projects/EpisodePage.tsx`, `frontend/src/app/studio.css`, `frontend/tests/e2e/studio-navigation.spec.ts`.

**Interfaces:** `activeStepIndex(tops: readonly number[], probeY: number, atBottom: boolean): number` returns an index into the seven ordered stage elements. Existing `EpisodeDraft`, `update(patch)` and `steps` IDs remain unchanged.

- [ ] **Step 1: Write the failing unit test** in `episode-scroll.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { activeStepIndex } from "../../src/pages/projects/episode-scroll";
describe("activeStepIndex", () => {
  it("uses the last section crossing the top reading line", () => {
    expect(activeStepIndex([90, 450, 900], 150, false)).toBe(0);
    expect(activeStepIndex([-310, 50, 500], 150, false)).toBe(1);
    expect(activeStepIndex([-810, -450, -10], 150, true)).toBe(2);
  });
});
```

- [ ] **Step 2: Confirm unit test fails** because `episode-scroll.ts` is absent: `cd frontend; pnpm test -- tests/runtime/episode-scroll.test.ts`.
- [ ] **Step 3: Implement the pure helper** and all seven simultaneously mounted named sections. Preserve child editors and their controlled values, replace old conditional `hidden` properties with `id`, `data-testid`, and `aria-labelledby` on each `<section>`. The click handler calls `document.getElementById("episode-stage-" + id)?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" })`. In a `useEffect`, attach a passive scroll listener and resize listener, schedule `requestAnimationFrame`, read stage `getBoundingClientRect().top`, call `activeStepIndex(tops, 150, window.scrollY > 0 && window.scrollY + innerHeight >= document.documentElement.scrollHeight - 2)`, and `setStep(steps[index].id)`; cancel frame and listeners on cleanup. Use `.episode-sidebar { position: sticky; top: 0; align-self: start; max-height: 100vh; overflow-y: auto; }` and `.episode-stage { scroll-margin-top: 24px; padding-bottom: 48px; }`. On narrow screens make sidebar sticky horizontal navigation and set stage scroll margin to 100px.

```ts
export function activeStepIndex(tops: readonly number[], probeY: number, atBottom: boolean): number {
  if (!tops.length) return 0;
  if (atBottom) return tops.length - 1;
  let index = 0;
  tops.forEach((top, candidate) => { if (top <= probeY) index = candidate; });
  return index;
}
```

- [ ] **Step 4: Add failing-then-passing E2E checks** after entering the episode in `studio-navigation.spec.ts`: expect seven visible stage headings, fill script, click nav “分镜视频”, poll for video stage near viewport top and `aria-current="step"` on its button, scroll back to script with `window.scrollTo({top: 0, behavior: 'instant'})` (use `behavior: 'auto'` in actual test), poll for script active, assert script value still present. Test reduced motion via `page.emulateMedia({ reducedMotion: "reduce" })`. Do not test by changing app window bounds.

```ts
const nav = page.getByRole("navigation", { name: "分集制作流程" });
await nav.getByRole("button", { name: /分镜视频/ }).click();
await expect.poll(() => page.getByTestId("episode-stage-video")
  .evaluate((node) => node.getBoundingClientRect().top < innerHeight)).toBe(true);
await expect(nav.getByRole("button", { name: /分镜视频/ }))
  .toHaveAttribute("aria-current", "step");
```

- [ ] **Step 5: Verify and checkpoint.** Run unit test, `pnpm typecheck`, `pnpm build`, and focused offscreen E2E. Inspect sticky behavior at desktop and narrow sizes, keyboard focus and the reduced-motion case. Review only intended edits.

## Task 4: Final integration and regression audit

**Files:** Test-only edits in `frontend/tests/e2e/studio-navigation.spec.ts` or related existing tests if their selectors legitimately changed; CSS fixes in `frontend/src/app/studio.css` only for issues observed in the bounded screenshot pass.

**Interfaces:** No new public API.

- [ ] **Step 1: Run `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build`** from `frontend`; fix failures attributable to this implementation, noting any pre-existing failures separately with concrete output.
- [ ] **Step 2: Run `pnpm test:e2e tests/e2e/studio-navigation.spec.ts`** from `frontend`, keeping offscreen configuration and the x-coordinate assertion. If other E2E specs are runnable in this branch, run them and separate stale-baseline failures from regressions.
- [ ] **Step 3: Capture one desktop and one narrow offscreen screenshot** of project list, project detail and episode; assess overflow, alignment, label association and scroll tracking in one batch. Apply one batch of fixes and do at most one confirmation pass.
- [ ] **Step 4: Review final diff and status** with `git diff --check`, `git status --short` and targeted `git diff` against the original dirty state. Do not delete user files or commit pre-existing edits. Report what passed, what remains, and the exact paths changed.

## Plan self-review

- Spec coverage: Ant theme/reuse and sidebar (Task 1); project action placement, details, close relocation, synopsis (Task 2); continuous bidirectional flow and motion (Task 3); errors, a11y, responsive and invisible E2E validation (Task 4).
- The current working tree contains overlapping uncommitted UI changes; execution works in place and preserves them. No independent worktree or commit of mixed files is assumed.

## Execution status (2026-09-17)

- Implemented the theme, collapsible asset navigation, right-aligned project actions, Ant Design cards/forms, project-information layout, and continuous episode page with bidirectional scroll tracking.
- After the existing desktop instance was closed, verified all 214 unit tests, `lint`, `typecheck`, `build`, two offscreen real-Electron navigation tests, and the headless desktop/mobile renderer flow. The headless flow checks both scroll directions, draft retention, reduced motion, contrast, view-entry scroll reset, project detail geometry, and narrow-screen overflow. The development-origin runtime E2E also passed when rerun in isolation.
- A full 15-case legacy E2E run had 7 passes and 8 failures. Most failing cases still look for removed pre-existing workbench labels such as “故事原文”, “项目素材”, “项目工作区”, and “制作工具”; the runtime development-origin test passed in isolation after that run. Do not claim the legacy suite is fully green until those flows are migrated or investigated individually.
- Independent UI review found low-contrast explanatory text and primary buttons plus retained scroll offsets between views. Scoped color fixes and a view-change scroll reset were added and verified by a red-green headless test. No visible window was opened during E2E.
