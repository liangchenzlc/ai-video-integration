# T06 文字、图像与结果取回实施计划

> **For agentic workers:** Use superpowers:subagent-driven-development task by task after T05 review and verification. Offline implementation is complete; remaining unchecked items require live-provider admission and separate authorization.

**目标：** 把受预算约束的文字/图像结果登记为可对照且不自动采用的候选；保留失败原始资料、媒体、用量和调用关联，恢复只取原结果。

**依据：** T06 模块设计、03 模型接入与成本控制、T04 持久执行器、T05 不可变版本和采用协议。用户授权继续完成既有设计；未授权新增真实推理费用。

## 设计与边界

- 继续唯一 planTask/startTask 付费入口，无旁路 generate。生成候选只修改候选和执行进度，不修改 adopted/confirmed，不增加用户 project revision 的并发冲突。
- 006 增加候选 task/call/ordinal 与 revision 的唯一关联、结果解析状态、必要的受保护输入/结果元数据。004→005→006 正常迁移、只读不升级、写前备份仍适用。
- 正式候选使用 T05 TypedPayload。模型缺字段、错误 kind、超限或错误引用时保留原始响应并报告结构不合格，不自动修复。只有故事 proposal 的现有人工规范化允许补空集合，不能对不合格模型响应做隐式创作补全。
- 故事模型候选不得改写输入的 sourceText/sourceHash/inputType；原文仍为冻结输入。生成阶段只允许其声明的成果字段变化，来源跨度必须匹配原始Unicode码点及hash。响应里的未知稳定ID不能自动变成已存在资产/对白/场景。
- 本地 synthetic 模式清晰标注，使用固定有效文本/PNG和可注入故障，不能冒充真实模型效果。升级前 T04 留存的原始 JSON 不自动变成新候选。
- 图像结果须经过实际解码/哈希/原子发布后成为媒体；在对应资产/镜头候选中保留版本引用与用途，不能自动宣称身份或用途已人工核对。
- 同一 call/ordinal 的候选登记可重放；数据库提交中断、文件发布后中断均恢复原结果。部分结果只保留已得候选并停止尚未提交调用。
- 下载器只接受适配器输出的受控 HTTPS 结果引用，逐跳校验主机/IP；拒绝私网、本机、链路本地、元数据目标、含凭据 URL、非 HTTPS/异常端口。DNS解析结果与实际连接固定一致，TLS验证原主机，响应URL和签名不得发给renderer。
- 真实百炼适配必须先重新核对官方当前接口/地域/参数/价格；已有研究仅为线索。未具备完整能力与价格依据的分支保持 disabled。真实账户、质量、账单与付费调用需要当次授权，不能用fixture替代。

## Task 1：结果登记与候选恢复

实施前核对：当前 T04 的每个 create step 调用只请求一个候选，`maxCalls` 是调用次数，不能误当单次返回数；precheck step 不得登记为创作候选。006 的持久映射须明确 task/call/结果 ordinal，并为后续图像媒体发布保留独立结果记录。升级前没有完整结果协议版本的 T04 响应继续保留原状。结果解析失败使用静态错误码，不把原始模型响应或签名 URL放入公共错误。

文字阶段边界：所有阶段锁定 sourceText/sourceHash/inputType；adaptation 只提出 brief/requirements/adaptationNotes，outline 只改 outline，scene 只改 scenes，dialogue 只改 dialogues。approvalLevel 可随阶段标明成果层次，但不是用户确认状态。未在该阶段允许的已有字段必须原样保留；有意跨阶段修改应由另一个明确计划承载。固定响应例子可以生成这些字段，正常响应解析不得补缺字段。SourceSpan 逐条核对冻结原文 hash 和 Unicode 码点边界。

文件：006迁移、storage candidates、services task_executor/task_adapter、ProjectService薄代理、tasks DTO、候选storage/executor tests。

- [x] RED：成功文本结果登记正式 revision 且不自动采用；无效 JSON 保留原始资料但不能确认。
- [x] 建立 call/ordinal 唯一候选映射，Task.candidateRevisionIds 从持久关联读取。
- [x] 实现结果解析和登记边界：先留存原始结果，再验证/发布，最后同事务关联候选与调用成功状态。
- [x] 固定响应适配器支持完整文本、有效PNG、损坏响应、部分候选，不触网。
- [x] 故障覆盖：下载中断恢复原call；登记前/后崩溃重放不重复；未知不补发；原媒体与费用不丢失。
- [x] UUID候选分页同时受T05条数/字节预算约束；报告 RED/GREEN与审查。

## Task 2：安全下载与生成媒体

文件：services安全下载端口、结果媒体发布、T02共享媒体校验接口、定向网络/文件故障测试。

- [x] RED：302到127.0.0.1、混合DNS公共/私有地址、TLS主机错误、过大/损坏/错误MIME响应均拒绝。
- [x] 实现有限重定向、连接/读取/总体超时、流式长度边界与固定解析地址连接；不携带服务商凭据到结果主机。
- [x] staging→校验→hash→原子发布→数据库登记，沿用T02缺失恢复且保留唯一结果。
- [x] 验证每种拒绝在网络/文件适配层无内网连接、无路径逃逸、无渲染层URL泄漏。
- [x] 固定本地测试传输只在fixture注入，生产没有绕过HTTPS/IP校验的开关。

## Task 3：百炼输入编译与适配准入

文件：版本化能力资料/价目、provider adapter/input compiler、脱敏响应fixtures、T03 capability registry、验证记录。

- [x] 重新只读核对官方文字和图像接口、北京地域、同步/异步、参考数量/尺寸/角色、用量与价格；记来源、日期和未知项。
- [x] RED：必要参考2张而能力上限1张时计划拒绝且零提交；不支持参数/用途不能静默丢弃。
- [ ] 编译确切请求快照，保存角色/顺序/hash、模板与能力版本、token/图像上限，实际提交使用同一快照。
- [ ] 接入受保护凭据读取及服务响应校验，submit与query/download分离；未可证参数保持能力缺失。
- [ ] 以脱敏fixtures验证成功/确定失败/未知/部分结果/过期/下载故障；真实付费验收单独记录需用户授权的具体批次和最大金额。


本轮完成禁用的离线编译器与响应解析器，17项固定响应测试及独立审查通过。请求摘要、字节与角色冻结已实现；上表实际提交、凭据/查询接线及真实用量未实现，因此相关混合条目保留未勾选。用户明确本轮不授权真实调用。

## Task 4：候选 API 与可对照桌面入口

文件：GET /projects/{pid}/tasks/{taskId}/candidates、有限桥、TaskPanel与RevisionPanel集成、类型生成、UI/Electron tests。

- [x] 严格RevisionPage安全响应与UUID分页，固定桥命令，不提供任意URL访问。
- [x] 任务结果展示候选内容/真实缩略图、来源和结构失败原因，选中不采用。
- [x] 候选复用T05影响/采用/检查/确认流程；处理未知状态、恢复下载、部分成功，保留已有结果。
- [x] 真桌面固定文本/图像任务→结果→对照→采用，重开候选仍在；下载失败恢复不产生第二次提交/占用。
- [x] 静态/类型/单元/实际解码/桌面截图及独立审查；记录真实服务和质量准入仍未完成的项。

## 不可替代的后续验收

本地安全、恢复和候选工程通过不等于百炼当前账户可用、正式模型组合合格或T14成片验收通过。T07继续建立故事/资产/镜头的完整人工编辑及承载关系；T10生产OSS音频传输与T14真实片单/双人看片/新手试用按原标准执行。

离线实现与最终验证证据见[2026-09-16-T06实现与验证](../../开发记录/2026-09-16-T06实现与验证.md)。
