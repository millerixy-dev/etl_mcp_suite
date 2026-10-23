## Why

Spark eventlog 能定位慢任务、失败任务及其 executor，但不包含 stdout/stderr 正文。用户已提供 CDP 网关下 Driver 日志的 JobHistory 链接；真实 Spark 2.4.7 样本也确认 Driver Logs 和 Executor Info.Log Urls 包含容器日志入口，需要一个独立工具把这些入口转换为可诊断的本地证据。

## What Changes

- 先做真实 stdout 下载验证：直接读取用户给定的 Driver JobHistory 链接，复用现有 Spark 认证/脱敏；验证完成后再交付工具。此验证入口不是允许调用者传任意 URL 的公共工具。

- 在现有 `spark` 插件新增 `fetch_spark_executor_log(application_id, attempt_id, executor_id, log_type="stderr", tail_bytes=65536)`；`executor_id="driver"` 获取 Driver 日志，普通数字 ID 获取 executor 日志。
- 复用已校验的 eventlog 取得真实 URL/容器身份，经部署配置的 NodeManager 网关访问，允许限定的同网关 JobHistory 日志重定向。禁止猜 container ID、节点 RPC 端口和 JobHistory 地址。
- 每次获取一个 stream 的有界尾部，保存脱敏 UTF-8 文本及来源清单，返回路径、SHA-256、字节数和范围摘要，不返回原始正文。
- 新增可选日志网关配置及上游 allowlist；现有 eventlog-only 配置仍能启动。认证继续来自环境 Cookie 或已配置 Knox Basic SSO。
- 新增单元、stdio 契约、架构与可选真实验证，并更新 README、配置示例和架构文档。
- 将旧 eventlog 能力中的单工具表述限定到其能力范围；eventlog HTTP 下载仍拒绝重定向，新工具的跳转由独立策略管理。

## Capabilities

### New Capabilities

- `spark-executor-log-fetch`: 精确定位 executor/Driver 容器日志，安全访问网关和受控跳转，解析有界 HTML 日志正文并保存脱敏本地证据。

### Modified Capabilities

无主规格 requirement 修改；Spark eventlog 能力仍位于已完成但未归档的 `add-spark-event-log-download`。本次对该活动能力作最小范围澄清，不重复修改其运行器 requirement；新 capability 明确最终 Spark 工具集合。

## Non-Goals

- 不实现 Spark 性能/根因诊断，不扩充 EnvironmentUpdate 配置白名单。
- 不开放任意 URL、日志文件名、输出目录、认证头、TLS 参数或 shell 命令。
- 不提供日志搜索、全文默认下载、自动轮询、多 executor 批量下载、syslog 或 HDFS/YARN CLI 访问。
- 不推导 latest attempt，不根据 executor ID 推导 container ID；日志 URL 缺失时明确失败。
- 不建立日志缓存复用、TTL、索引或新插件，不改 eventlog 下载/缓存的公共参数和结果。

## Impact

影响 `src/mcp_stdio/plugins/spark/` 内的配置、领域契约、gateway/service、HTTP/HTML/证据适配器及 composition；共享 core 只增加新 ToolOperation 和安全标识白名单。复用 httpx 和 Python 3.10 标准库，不增加依赖。增加同网关 NodeManager/JobHistory 只读访问；启动不联网、stdio 不开放监听端口。在现有五个 Spark 下载、检索和指标工具之外新增一个日志获取工具；文档和测试验证已实现能力的精确工具并集。
