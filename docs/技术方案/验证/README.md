# 设计资料验证

这里的 Python 是文档验证工具，不是后端应用，不访问服务商。要求 Python 3.12+、jsonschema 4.x；生产运行时继续按 T01 候选基线实测。

在项目根执行：

```powershell
$env:PYTHONIOENCODING='utf-8'
python docs/技术方案/验证/build_contracts.py
python docs/技术方案/验证/build_examples.py
python docs/技术方案/验证/validate_design.py
```

build_contracts.py 是设计期 Schema/OpenAPI 源，生成 JSON 不手工改字段；build_examples.py 生成接口结构样例与语义夹具。生产实现后以 FastAPI 导出契约核对，再用实际代码测试接替设计 oracle。

验证范围：JSON Schema 结构、自引用解析、每个 API 的正例与负例、七镜时间线/来源范围、预算及恢复预期、SQL 建表与关系/不可变/唯一/费用约束、文档链接和模块覆盖。验证用内存数据库，不写用户项目。

接口 examples 的 scope=transport_shape_only 表示只演示请求/响应字段，不假称任意 UUID 在运行中的项目存在；domain.examples 的虚拟媒体图与场景才承担跨字段验证。文件 provenance=synthetic；模型能力、Windows 启动/锁/崩溃恢复、真实 API 防重、预览/导出一致性及人工艺术判断均不在本工具的证明范围内。

G00 原型有独立浏览器走查脚本，见 [原型与走查](../../开发准备/G00-原型与走查.md)。缺浏览器时如实记录未运行，不把静态文件检查当操作通过。
