## Why

Spark SQL 故障诊断需要先取得可供后续工具读取的 event log。已验证办公网能够通过网关后的 Spark History Server 下载 Spark 2.4.7 发行版的日志 ZIP；首版只把这条路径变成可调用的 MCP 工具，尽快进入分析工具开发。

## What Changes

- 新增固定内置 `spark` 插件，暴露一个工具：`fetch_spark_event_log(application_id, attempt_id=None, refresh=False)`。
- 使用配置的 History Server 地址和环境注入的已有 Cookie，或 Knox Basic 登录换取的临时 Cookie 下载 ZIP；默认启用 HTTPS 证书验证，支持可信私有 CA；允许部署显式设置 verify_tls=false 跳过校验。
- 使用标准库校验 ZIP、JSONL 和 application/attempt 身份，脱敏后保存 JSONL 与一份 `manifest.json`，返回本地路径。
- 默认复用同来源、同请求的已保存文件；`refresh=true` 重新下载。一次下载一个目录，不引入内容寻址、去重、快照引用或自动缓存清理。
- 保留实际字节上限、超时、失败清理、私有目录和简单进程锁；补齐插件契约、测试和使用文档。

## Capabilities

### New Capabilities

- `spark-event-log-download`: 通过 YARN application ID 下载、校验、脱敏并保存 event log，供后续诊断工具直接读取。

### Modified Capabilities

- `plugin-stdio-runtime`: 固定插件集合增加 `spark`；允许同一专用缓存目录在前一进程退出后被后续 Spark 进程复用，继续隔离活动进程状态。

## Impact

- 新增 `src/mcp_stdio/plugins/spark/` 垂直切片，沿用现有配置、服务/网关和 MCP 适配器边界；共享代码扩展固定注册表、插件类型、CLI 帮助、安全错误清单和通用 MCP 原始参数校验。
- 复用已有 `httpx` 与 Python 3.10 标准库，不增加运行时依赖。
- 同步 README、配置示例、架构文档和 AGENTS.md 的插件范围，增加必要单元/契约测试及环境驱动的可选真实下载测试。
- 网络访问为配置的 History Server GET，以及启用 Basic 登录时同域 Knox SSO POST；本地持久文件作为 L3 memory。人工下载的旧 ZIP/manifest 不自动导入。

## Non-Goals

- SQL/job/stage/task 分析、root cause 判断、诊断 Skill、YARN 容器日志。
- SSH/WebHDFS、其他自动登录机制、浏览器 Cookie 提取/刷新、任意 URL 或输出路径。
- 内容寻址存储、去重、对象引用、TTL、全局容量管理、GC、索引库、独立 offline 模式、格式迁移。
- 损坏尾行修复、事件日志自身压缩/滚动格式、严格按 Spark patch 版本拦截、断点续传、后台任务。
- MCP HTTP/SSE 服务、动态插件发现或通用 memory 系统。
