# T01-C 后端验证与 Review

2026-09-16，Windows 11 x64。本步骤完成正式 supervisor/API 入口、API 用户互斥体、真实 socket/Uvicorn 启动和停止，以及冻结后端。不是完整桌面验收。

执行 `powershell.exe -NoProfile -File scripts/check-t01-c-backend.ps1`：退出码 0，148 项测试通过，无失败、无跳过；Ruff、格式检查、Mypy 21 个 app 文件通过，两份 PyInstaller spec 构建通过。机器报告为 `.cache/t01-c-backend-tests.xml`。

真实进程案例覆盖正常停止、父管道 EOF、supervisor/API 被终止、非法协议、启动中停止、缺少 init、互斥体占用、假子进程确认停止后仍存活，以及中文空格路径中不依赖系统 Python 的冻结后端。

本轮是实现者自查 Review，没有独立审查者。发现并修复：已进入 5 秒正常停止等待时，父 EOF 仍必须立即终止 Job，不能继续等正常宽限；增加真实不响应进程回归用例，确认 EOF 缩短到强制清理时限。错误优先保留原 API 错误，不被随后的进程退出改写。

安全边界：仅记录固定错误码；秘密通过专用 stdin 初始化；API 的 stop_ack 不证明 Job 清空。PyInstaller 的 tzdata 警告未造成当前单调时钟路径失败，不将此结果推断为其他时区功能已验证。

下一步为 Electron HTTP/生命周期/IPC，之后才接产品界面和完整目录包验收。
