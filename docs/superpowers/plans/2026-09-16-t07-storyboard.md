# T07 故事、资产与分镜实施计划

> **For agentic workers:** Use superpowers:subagent-driven-development. 当前用户授权自主接续；只验证本轮基础功能，集合测试留待最终集成。

**Goal:** 将现有故事草稿、资产与稳定镜头组织成可编辑、可采用且能定位承载缺口的离线工作区。

**Architecture:** 复用 T02 草稿、T05 不可变候选/采用/撤销及 T06 生成入口。007 增加镜头顺序和参考核对证据；正文仍以 draft/revision 为准。API 和有限 Electron 桥提供工作区索引、排序、coverage、参考核对；本地模板只组织已采用事实，未具备的声音/预演/真实模型准入明确阻断。

**Tech Stack:** Electron/React/TypeScript、FastAPI/Python、SQLite。

**Spec:** `docs/技术方案/模块设计/T07-故事资产与分镜.md` 与 `docs/技术方案/契约/business.openapi.json`。

## Global Constraints

- 保留 T06 未提交改动，在现有 feature 分支接续；不提交、推送、发布或调用真实模型。
- source span 按 Unicode 码点定位；旧 hash 不自动沿用。原文、台词与差异不做隐式重写。
- 选中、保存草稿、创建候选、采用和确认分开。所有写入使用既有 CAS/operation receipt；丢响应查询原操作。
- 身份与姿势分开，参考用途不得静默转义；matchesPurpose=false 保持不可用。核对结果绑定 draft/media/hash/role，并保留说明。
- 镜头重排恰好覆盖全部活动 ShotId、不变更对白和媒体归属；失效范围覆盖揭示/承载/时间线，禁止修改正在被任务冻结的输入。
- 本轮仅基础单元/API及一条离线桌面主流程、必要类型/静态检查和审查；不跑全量回归、不重打包。

## Task 1：本地内容规则与持久索引

**Files:** 新增 `backend/app/storage/migration_007.sql`、`backend/app/storage/storyboard.py`、`backend/app/services/storyboard.py`、`backend/tests/storage/test_storyboard.py`；修改 database/drafts/revisions/checks/projects 与 avi_backend.spec 的必要接线。

**Interfaces:** ProjectService 提供 `get_storyboard(project_id, session_id, window_id)` 返回 `{drafts:[{id,artifactId,kind,savedAt}],shotIds:[uuid]}`；`get_coverage(...)` 返回既有 Coverage；`reorder_shots(..., command)`、`verify_reference(..., command)` 返回 MutationReceipt。命令 payload 分别为 `{shotIds}`、`{draftId,mediaId,role,matchesPurpose,note}`。

- [x] 用基础测试先重现：保存镜头建立稳定索引、原样重排与重复ID拒绝、必留事件缺口、参考核对不采用、旧来源失效。
- [x] 007 支持旧库写前备份迁移，只读旧库明确不支持新增入口。保存 shot draft 登记唯一 shotId/artifact；候选也校验稳定ID。
- [x] 覆盖从已采用内容计算；事件须明确对应要求与观察方，物理存在不算观众揭示。有意省略必须有理由和改编说明。
- [x] 参考核对保存证据并更新指定草稿；媒体缺失/hash不匹配、重复用途歧义拒绝。修改参考身份/用途后证据不能继续放行。
- [x] 原文跨度、事件时间与稳定引用在正式版本边界校验。重排原子修改索引并失效相关采用成果，不修改 revision/媒体/费用。
- [x] 运行新增基础测试及触及文件的 Ruff/mypy，做任务 review。

## Task 2：编辑与镜头卡

**Files:** 新增 `frontend/src/app/ContentWorkbench.tsx`、内容表单/本地辅助模块及基础测试；修改 StoryDraftEditor、ProjectsHome、App、RevisionPanel 和 styles 的集成。

**Interfaces:** 消费现有 drafts/versions/media 与 Task 3 `window.desktop.storyboard.{list,coverage,reorder,verify,prompt}`。list/coverage 数据结构见 Task 1；prompt 输入 `{projectId,shotId,phase:'image'|'video'}`，返回 `{templateId,templateVersion,prompt,sourceRevisionIds,blockers,reusableVideoMediaId}`。

- [x] 三入口保持原文，提供大纲、分场、台词、必留项及来源/改编决定表单；复用单个故事自动保存引擎，禁止双编辑器互相覆盖。
- [x] 资产表单支持四类、锚点、允许变化、持续状态、真实媒体参考用途及核对；镜头表单支持观看目的、起点/事件/终点、摄影/手、时长、资产/对白/要求、补拍归属。
- [x] 资产/镜头草稿进入原版本面板，对照采用后刷新；重排仅调用顺序命令。编辑离开、只读、丢响应与 CAS 失败保留输入。
- [x] 故事与视觉导航开放对应工作区，未选项目给明确入口；沿用现有视觉风格，不要求填写JSON。
- [x] 展示 coverage 与本地模板/试片缺口，不把结构完整当语义通过，不增加必经付费任务。
- [x] 仅辅助逻辑基础测试、类型/静态与一条 T07 Electron 主流程。

## Task 3：契约、桥与本地制作依据（root）

**Files:** 新增 api/v1/storyboard.py、storyboard_models.py、services/storyboard_templates.py、electron/shared/storyboard.ts、main/projects/storyboard-ipc.ts、preload/storyboard.ts；接入 routers/security/bridge 白名单与类型，新增基础 API/bridge 测试。

- [x] 既有三接口 PUT /shot-order、GET /coverage、POST /references/verification；补充 GET /storyboard 工作区索引、GET /storyboard/shots/{shot_id}/prompt?phase=image|video。
- [x] 严格 DTO、固定路由、绑定项目session与只读状态；沿用静态错误映射、命令回执与请求上限。
- [x] 模板有稳定版本，组织已采用文字/资产/参考与单帧或动作链。prompt 仅本地展示，不调用供应商。
- [x] 返回明确缺口：未确认/待更新文字、资产/参考、未具备正式配音或局部预演/真实接口预算准入。不伪造试片可用；本轮因正式制作基准尚未齐备，reusableVideoMediaId 固定为空；后续接入基准证据后再验收已采用试片复用。
- [x] 导出 OpenAPI/TS，基础 API/桥测试；最终集中审查本轮 diff，修复实际缺陷。

## 完成记录

三个实施任务的离线范围已完成并审查。后端23项、前端定向14项、Electron基础主流程1项通过，类型/静态检查与源码构建通过；详见[实现与验证](../../开发记录/2026-09-16-T07实现与验证.md)。首次保存、故事版本定位、明确失败解锁及排序锁定时间线的问题已修复并定向复核。

集合测试、目录包与跨模块声音/预演/视频/真实服务联合验收保留到后续集成；本轮报告明确已验证范围，不将未运行的检查写作通过。
