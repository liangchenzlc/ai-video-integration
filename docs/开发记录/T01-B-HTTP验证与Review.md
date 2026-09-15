# T01-B HTTP 子步骤

日期：2026-09-15。健康和能力接口、请求安全检查及模型契约已实现，**35 项测试通过**，可继续 B 的控制管道 codec。尚未启动正式 API 进程或接入产品桌面生命周期，完整 T01-B 仍未完成。

可复核入口：`powershell.exe -NoProfile -File scripts/check-t01-b-http.ps1`。

## 已验证

- 两个 FastAPI 接口的实例/代际/版本、单调计时、固定十二项能力以及未就绪 503。
- 所有 HTTP 路径，包括未知路径和禁用的 docs，均先经过 Host、Origin 和 Bearer 校验；重复敏感头、错误请求 ID、查询参数、GET body 均按契约拒绝。
- 请求体和响应各限制 64 KiB，认证头 128 字节；chunked 体超限中止，非法/超长 Content-Length 不进入整数解析。
- 错误统一中文固定文案；异常、框架 HTTP 错误及响应校验错误均不回显伪秘密或 Python 异常详情。
- Pydantic 拒绝额外字段、错误整数和虚假能力；数学整值 1.0 归一化，True、数字字符串和非整值不通过。
- 从真实应用导出 [OpenAPI](../../contracts/openapi.json)，对两个路径的操作 ID、参数、各状态响应、全部展开字段约束、认证和头部自动比对设计基线，结构一致。
- 已生成 `frontend/src/api/runtime-types.ts`，TypeScript 严格检查通过；Ruff 和 Mypy 通过。

## 自查修正

1. `BeforeValidator` 与范围 Field 的顺序影响 Pydantic 输出，最初运行时范围正确但 Schema 出现非标准 ge/le。调整顺序后输出标准 minimum/maximum，自动契约比对已覆盖。
2. OpenAPI 的版本使用 API 契约 `1.0.0`，健康响应中的 backendVersion 保持应用构建 `0.1.0`，避免混用。
3. 认证中间件覆盖整个应用，统一处理未知路由；捕获内部错误时不输出异常对象，避免 Starlette 外层记录含输入的栈。
4. 声明体长与实际体长不一致时返回 400；超长数字先按长度拒绝，避免受控坏输入落入 500。
5. Mypy 启用 Pydantic 插件识别 Python snake_case 构造参数及 camelCase 序列化别名。

本记录为实现者自查。测试使用 ASGI 客户端，未冒称已经验证真实 TCP 解析、Uvicorn 配置、互斥体或 Electron 安全边界；这些在控制协议和实际连接阶段补齐。
