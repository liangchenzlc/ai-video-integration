# T01 最终验证与 Review

2026-09-16，Windows 11 x64。**T01 工程范围已完成，可进入 T02；本轮按用户要求停在 T01 与交接。** 没有真实模型调用、费用或业务数据库。T02–T14 未实现，正式产品及真人验收未完成。

## 交付物

- 可运行目录包：`release/t01/win-unpacked/AI Video Integration.exe`，必须保留整个目录。
- 源码：正式 Electron main/preload/React 页面；Python supervisor/API/Job；固定 HTTP 和控制协议。
- 使用与后续实施：[详细交接文档](./T01完成后的开发交接.md)。
- 界面：[首页截图](./截图/T01-首页.png)。主窗口 1280×800，截图为本机缩放下的完整页面；主动作、六组导航与键盘焦点已检查，内容可纵向滚动。
- 机器证据：[最终摘要与 SHA256](./t01-final-evidence.json)、[目录包测试](./t01-packaged-tests.json)、[目录包实测](./t01-packaged-metrics.json)。

## 验证结果

| 执行 | 结果 |
| --- | --- |
| `scripts/check.ps1` | 退出 0；契约、类型、ESLint/Prettier、Ruff/Mypy、两端测试、构建和当时 4 项桌面测试全部通过 |
| 后端完整 pytest | 148 passed，无失败、无跳过；本轮 25.45 秒，含真实 Windows 与冻结后端故障测试 |
| 前端 Vitest | 77 passed，无失败、无跳过；含真实 Node/Python 启动、重启、停止与 TCP HTTP 校验 |
| 最终开发 CSP 补验 | TypeScript 与构建通过；Playwright 5 passed，新增 Vite/React 开发来源和刷新后同实例重连验证 |
| 最终 ESLint | 退出 0，覆盖变更后源码与测试 |
| `scripts/pack-win.ps1` | 退出 0，固定版本 PyInstaller 与 electron-builder 目录包 |
| `scripts/test-packaged.ps1` | 退出 0，4 passed；全新中文/空格路径运行，PATH 仅 Windows System32 |

真实桌面测试同时验证能力仅 runtime、有限桥、无 require/process、sandbox/contextIsolation 开启、Node 禁用、来源/CSP/新窗口限制、六组未开放导航、双击重启合并、第二应用实例退出、旧服务进程清理以及正常关闭。三种故障分别终止当前 main/supervisor/API，并通过已持有的进程句柄确认后端退出；存活桌面可明确重启。

目录包单次从启动测试进程至界面真实 ready 为 **2583 ms**。Electron main RSS 为 **121192448 字节**，仅主进程，不是整个应用总内存。Electron 44.3.0 内置 Node 24.20.0；项目构建 Node 为 24.21.0。体积、Python/SQLite 运行时和摘要见 JSON。该启动值包含自动化开销，只是一台机器上的单次测量，不是性能保证。

## A01–A20 验收对应关系

| 编号 | 对应证据与结论 |
| --- | --- |
| A01 | T01-A frozen 安装/锁文件记录；本轮工具链检查、契约比较、类型生成、两端构建通过 |
| A02 | 正式目录包在中文/空格路径中通过；自带两种 role 后端，隐藏子进程、标准流和真实健康可用 |
| A03 | ENOENT/EACCES 启动适配故障、30 秒启动截止的状态机用例；真实缺 init 截止；失败不无限重启 |
| A04 | 后端认证正负例与实例令牌校验，固定错误/秘密哨兵；桌面桥与快照不暴露地址或令牌 |
| A05 | Host/Origin/方法/body/query 与实际 TCP 回环验证，错误统一 |
| A06 | 真实 Electron 无 require/process；仅五个桥方法；主进程检查 sender/frame/来源，恶意参数拒绝 |
| A07 | CSP 限制远程请求/脚本，非法导航保持原 WebContents/DOM，新窗口不创建；外部资料固定映射 |
| A08 | HTTP API/控制/构建版本校验；状态机版本失败清理后 incompatible，backendVersion 未验证不展示 |
| A09 | 真实 API 被终止后连接失效，明确点击重启才创建新实例；源码与目录包均通过 |
| A10 | 真实正常退出、main/supervisor/API 故障清理；T01-A 无关进程不受影响与后代归属测试 |
| A11 | 双击重启只增加一代；第二可执行实例退出且原窗口/代际保持 |
| A12 | 六组中文导航均显示尚未开放；1280×800 下无横向溢出、键盘焦点与重启动作可达，截图自查 |
| A13 | 关闭意图覆盖启动/待重启/晚到成功；spawn 前关闭仍保持 init→stop 顺序；失败时安全关闭 |
| A14 | current child/runtimeId/generation 守卫，旧退出与晚到健康不改新状态；界面按 revision 合并 |
| A15 | 共用 39 个 wire vectors、两端 codec、UTF-8/重复键/超长/半帧/序号/方向/身份案例 |
| A16 | 状态机 stopped+close 双条件；真实 stubborn 子进程确认后仍存活时不会提前报告停止 |
| A17 | 真实 5 秒宽限后强制清理及父 EOF 打断等待；main 8 秒最终截止，STOP_TIMEOUT 禁止就地重启 |
| A18 | 真实 API 用户互斥体占用不杀原实例，停止后可以再启动 |
| A19 | 401 立即断开且不重用旧令牌；三次瞬态失败断开、同一实例恢复 ready；无业务自动重发 |
| A20 | HTTP 默认文档关闭、异常/错误/快照的固定安全输出与秘密哨兵通过 |

边界：权限不足、启动截止、版本不符和健康退化的确定性分支采用注入失败/时钟的测试；正常连接、重启及三种崩溃采用真实进程。没有将这些确定性测试描述为每种故障都在真实安装器中演练。

## 实现者代码 Review

本次是实现者逐文件自查与测试，没有独立审查者。

1. 生命周期：修正 spawn 事件之前退出的顺序，先 init 再 stop；保留启动所需秘密直到 init 发出，随后取消工作并清除。停止确认不等于退出，8 秒超时不得因后续 close 重新允许重启。
2. 异常恢复：API 已连接后意外退出显示 disconnected，保留明确重启动作。异常 supervisor 退出允许恢复依据是已测试的唯一不可继承 Job 句柄关闭机制；正常 stop 仍要求 stopped 和 close。只对当前持有 child 操作。
3. HTTP 与桥：严格 UTF-8、重复键、有限响应、正确头/身份/能力表；只转固定错误码。preload 不返回原始 Electron event、异常、地址或令牌；新增业务必须另设命令。
4. 桌面来源：正式 `app://ui/` 只提供构建静态白名单，拒绝外网导航、新窗口、权限申请与下载。开发 CSP 仅在固定 localhost 来源放行 Vite/React refresh 的内联脚本/样式与 HMR，生产不放行。
5. 界面：修正装饰点干扰导航可访问名称；先订阅再查询，旧 revision 不覆盖新状态；未实现页面没有保存/生成假按钮。截图检查文字对比、焦点与工作流顺序。
6. 打包：electron-builder 需要项目本地 pnpm/Node PATH，脚本已显式设置并还原。正式后端在 asar 外；测试观察器不进入发布包。
7. 测试设施：Playwright 返回的 launcher PID 不等于实际 Electron main PID，改从 main 取 PID 再持有真实进程句柄。Electron 取消导航后 Playwright 的导航等待会挂起，改检查实际 WebContents URL 和 DOM，未放宽导航保护。

## 保留的后续事项

- T02–T14 完整业务工作流未实施，详见交接文档；当前能力表保持仅 runtime。
- G00 与 T01 界面只有内部工程/交互走查，真实新手参与者尚未招募。用户已授权推进工程，真人理解/完整工作流验收继续由 T14 负责，不能宣传为已通过用户验收。
- 当前仅 Windows 11 x64 本机目录包；干净系统、其他 Windows、签名、安装器、升级/卸载保留数据属于 T13。
- 真实模型、正式声音传输、口型、AI 音乐/音效、艺术效果与账单均未测试，后续须明确调用预算。
- 构建存在上游 Zod 注释注解警告、无 author/默认 Electron 图标等工程提示；不影响本轮目录包。发行元数据、产品图标和第三方许可清单在 T13 补齐，不假称已正式发行。
