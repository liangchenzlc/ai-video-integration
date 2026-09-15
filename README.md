# AI 漫剧工作台

面向中文新手的 Windows 本地 AI 漫剧制作工具：自有 API Key，从故事、资产与分镜到声音、视频、剪辑和 MP4，质量优先，费用可追溯，局部修改和任务恢复可控。

T01 桌面底座已完成：真实后端连接、状态与重启、六组中文导航和 Windows 目录包均已验证。T02–T14 业务功能仍待实现。前端 Electron + React + TypeScript，后端本机 FastAPI + Python，SQLite 与 FFmpeg 管理本地项目和媒体。

- [开发准入与资料清单](./docs/开发准备/README.md)
- [资料验证结果](./docs/开发准备/资料验证结果.md)
- [产品文档导航](./docs/文档导航.md)
- [T01–T14 模块需求、接口与模型](./docs/技术方案/README.md)
- [G00 离线流程原型](./docs/开发准备/原型/index.html)
- [设计契约与示例验证](./docs/技术方案/验证/README.md)
- [T01 最终验证与代码 Review](./docs/开发记录/T01-最终验证与Review.md)
- [详细开发交接：代码入口、T02 实施批次和剩余模块](./docs/开发记录/T01完成后的开发交接.md)

原型和验证脚本不调用真实模型；研究素材与模拟账目不代表正式效果或价格。当前产品仅开放本地服务连接；项目保存、模型生成、剪辑和导出尚未实现。

运行目录包：`release/t01/win-unpacked/AI Video Integration.exe`，保留整个目录。开发运行 `powershell.exe -NoProfile -File scripts/dev.ps1`；检查、打包及目录包验证分别使用 `scripts/check.ps1`、`scripts/pack-win.ps1`、`scripts/test-packaged.ps1`。
