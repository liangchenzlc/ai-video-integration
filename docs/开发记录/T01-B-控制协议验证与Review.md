# T01-B 控制协议与接口验收

日期：2026-09-16。结论：T01-B 通过，可以进入 T01-C 的真实服务与桌面生命周期连接。

最终命令 `powershell.exe -NoProfile -File scripts/check-t01-b.ps1` 退出 0；包含 HTTP 35 项、Python 控制/写入 82 项、TypeScript 45 项测试，均无跳过。Ruff、Mypy、TS 严格类型检查与 Prettier 通过。HTTP 细节见[前一子步骤](./T01-B-HTTP验证与Review.md)。

## 实现与证据

- Python `control_protocol.py` 与 TypeScript `control-codec.ts` 对应相同七类消息、四个方向和实例身份；单方向序号独立递增，init 必须且只能为父通道首帧。
- 共同读取 [39 个字节级向量](../../contracts/control-vectors.json)，源于设计示例。覆盖合包/拆包、中文及 emoji、重复与转义键、UTF-8、BOM、CRLF、NaN、非法身份/方向、半帧 EOF、精确 16 KiB 边界和不规范 Base64URL。
- 两端写入队列均计入正在写的内容，上限 64 KiB；无写入进展两秒即失败。Python 支持部分写入并由监督循环检查超时，TS 正确等待 Writable 的回调和 drain。
- 真实 Windows 匿名管道测试：读端不读取时写端阻塞，超时检查能返回；关闭读端后写线程退出。其余写队列边界使用可控阻塞和时钟验证。
- 所有解析错误只返回固定 `ProtocolError`，不暴露底层 JSON/Zod/Pydantic 输入详情；Python init 令牌字段及 frame payload 不参与 repr，TS 字节缓存使用私有字段。

## 实现者自查与修正

1. JS JSON.parse 的 reviver 看不到已合并的重复键，因此额外扫描原始合法 JSON 的字符串与容器；转义后的相同键也拒绝。所有字符串拒绝不成对代理项，避免两端 Unicode 行为不同。
2. Python 的内部别名构造规则不能直接用于外部控制帧。解码强制 by_alias=true、by_name=false，拒绝 snake_case 替代必需字段。
3. 字节长度在缓冲拼接前检查，含 LF；非法输入后解码器永久关闭并清空待处理数据，不能接着信任同一损坏通道。
4. Windows 根相对路径与不完整 UNC 路径不算绝对配置目录；校验与 TS win32 路径行为对齐。
5. Python 写线程不持锁执行 OS write，监督线程可检测超时；退出不无限 join 阻塞线程，由拥有者关闭管道/进程。主动关闭且仍有待写数据不会被 drain 冒称已完成。
6. TS 失败时释放计时器和队列并关闭写端，保留错误处理直到流关闭，避免异步错误变成未捕获异常。

该批次没有声称验证 ready/stop 的完整生命周期竞争、真实 HTTP socket 或 Uvicorn。下一步先接入 Python API/监督器并做真进程联调，再连接 Electron；所有旧实例回调隔离和界面状态规则在 T01-C 验证。
