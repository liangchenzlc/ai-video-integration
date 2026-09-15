# T01-A 进程管理与打包探针

日期：2026-09-15。结论：T01-A 验证与自查通过，可以进入 T01-B。**完整 T01 尚未完成，当前没有可用的业务产品。**

## 已实现范围

- 两端精确依赖清单、`uv.lock` 与 `pnpm-lock.yaml`；便携工具链、版本核对和统一检查入口。
- `WindowsJob`：挂起创建、句柄允许列表、先分配 Job 再恢复、真实进程句柄、关闭时清理整棵树。
- `finish_tree`：等待整棵树，宽限结束后强制清理，确认 Job 为空且根进程退出后才返回。
- `python_launch`：受控子进程环境、开发解释器 PID 一致性、生产同一 exe 的角色启动。
- 独立的 supervisor/API **打包探针**：`backend/probes/entrypoint.py` 和 `frontend/probe/index.cjs`，验证标准流与进程生命周期。探针无 HTTP、令牌或业务接口，不作为产品入口。

## 验证证据

最终统一命令：`powershell.exe -NoProfile -File scripts/check-t01-a.ps1`，退出码 **0**。

| 检查 | 结果 |
| --- | --- |
| 系统与工具版本 | Windows 11 10.0.26200 x64；Python 3.13.15、Node 24.21.0、Electron 44.3.0，与候选清单一致 |
| 锁文件复用 | `uv sync --frozen --offline`、`pnpm install --frozen-lockfile --offline` 均退出 0 |
| Python 静态检查 | Ruff 检查和格式通过；Mypy 覆盖 5 个应用源文件，零问题 |
| Windows 实机测试 | **19 passed，0 skipped**；7 项 Job、2 项整树退出、2 项启动环境、8 项源码/冻结探针 |
| JS 探针 | Node 语法检查及 Prettier 通过；尚非 React/TypeScript 产品构建验收 |
| Python 打包 | PyInstaller 6.22.3、onedir、console=True；源码及中文/空格路径冻结包均通过四种退出场景 |
| Electron 打包 | electron-builder 26.15.3 目录包；asar 外携带完整后端目录 |
| 桌面实测 | 中文和空格路径、PATH 仅 Windows System32；renderer 加载、握手、三个标准流、后端退出码 0、桌面退出码 0、Job 活动进程 0 |

机器记录：[工具链](./t01-a-toolchain.json)、[桌面探针](./t01-a-desktop-probe.json)、[测试报告](./t01-a-tests.xml)、[代码与锁文件摘要](./t01-a-snapshot.json)。

生成目录：`backend/dist/avi_probe/`、`release/t01-a/win-unpacked/`；中文路径副本位于 `.cache/`，均不入库。

## 代码 Review 与修正

本批次由实现者逐文件自查并用实机故障测试验证，不声称经过独立审阅者审查。

1. **句柄继承过宽**：只设置父句柄不可继承不足以排除其他继承句柄。使用 CPython `_winapi.CreateProcess` 的 STARTUPINFOEX `handle_list` 限定三个标准流；新增无关可继承管道测试。pywin32 的 STARTUPINFO 不提供该字段，Job 操作仍使用 pywin32。
2. **创建失败清理**：分配 Job 失败时杀死仍挂起的进程；测试持有额外真实进程句柄确认退出。管道转成文件对象前先转移所有权，避免异常路径重复关闭；使用 ExitStack 保证某一关闭失败时仍释放其他资源。
3. **Windows 虚拟环境 PID**：`.venv/Scripts/python.exe` 是重定向启动器，实际 Python 运行在另一个 PID。直接启动 `sys._base_executable`，并从当前解释器计算 `__PYVENV_LAUNCHER__`，保留项目依赖且保证启动 PID 与报告 PID 相同。后续 Electron 开发启动必须遵循同一规则。
4. **不能只等根进程**：Windows 可能创建隐藏 conhost，API 退出后也可能遗留媒体子进程。改为等待整棵 Job，并在剩余期限内核对根句柄；测试同时验证不影响无关进程、遗留子孙被回收。
5. **测试不能无限等**：探针读管道有大小与时间限制；桌面测试本身也放入独立 Job，超时即回收全部测试进程。pytest 缓存创建在当前执行沙箱中会循环等待，关闭非必要 cacheprovider 后测试正常结束，不跳过业务断言。
6. **环境与秘密**：子进程只继承允许的 Windows 环境项。伪密钥、PYTHONPATH/PYTHONHOME、NODE_OPTIONS 和外部注入的 launcher 值不会传入子进程；环境不进入对象 repr。
7. **构建可复用**：补齐本地 pnpm.cmd 供 electron-builder 调用；探针读取已校验的 Electron dist，避免打包时重复下载。

## 实机限制与后续门槛

- GitHub 官方 Electron 下载连接超时，改从 npmmirror 取得同版本压缩包；仍由 Electron npm 包自带 SHA256 校验，未关闭校验或修改版本。
- 受限执行沙箱内 Chromium 加载返回 ERR_FAILED；自动审批允许后，在正常 Windows 权限下运行相同探针通过。`sandbox=true`、`contextIsolation=true`、`nodeIntegration=false` 始终保持。探针用户数据放在 `.cache` 内。
- 不涵盖干净机器安装、Windows 10、签名/安装器、产品 UI、HTTP/控制协议、凭据、真实模型或费用。4 项弃用的前端传递依赖及未运行的 electron-winstaller 构建脚本不影响本次目录包；安装器工作在 T13 单独验证。
- CPython 私有 `_winapi` 和 `_base_executable` 只封装在进程/启动适配层；后续 Python 升级必须重跑本批实机用例。

下一步 T01-B：正式健康/能力 HTTP 接口、认证与错误处理、双语言控制协议 codec、OpenAPI 导出和 TS 类型生成；完成对应测试与 review 后才能接入 T01-C 生命周期。
