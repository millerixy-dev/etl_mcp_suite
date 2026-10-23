## Context

使用已实现的 fetch_spark_executor_log，真实 schema 来自 src/mcp_stdio/plugins/spark/executor_log_models.py 与 tools.py。来源语义由 executor_logs.py 验证，并与 ../add-spark-executor-log-fetch/design.md 及其 capability spec 一致；该设计包含既有上游 API 来源。本 change 无新端点和配置，配置字段表、file/env-only 启动示例均不适用。

## Goals / Non-Goals

让 Agent 按问题和证据缺口选择 Driver 或明确 executor，取得日志后继续验证假设。保留 Skill 为取证工作流，服务端只提供事实。采用主文件短路由加一份条件参考；相较把完整流程塞入主文件，可减少无日志需求时的上下文；相较自动下载脚本，不重复现有 MCP 的认证与安全逻辑。

## Decisions

- Driver：用户明确请求、SQL 无 Job 即结束、终态不明或 Driver 侧错误时取证。日志流由线索决定；无具体线索先 stderr，只有退出码/没堆栈/空流时补 stdout，不把两流变成所有任务的固定开销。
- Executor：事件给出直接 executor ID、明确区分任务执行方与 Shuffle 数据提供方；只补关键 executor，继续检查恢复及 Job 结果。
- MCP 返回路径不是正文。核对 identity、manifest、size/hash，再用可用的本地只读能力读取已脱敏文件、带行号搜索和有界上下文；event JSONL 仍通过固定摘要的 query_spark_events。
- 先用默认64KiB，缺少所需时间/异常开头且 coverage 不完整时可扩大至当前1MiB上限。小文件不是完整覆盖证据；不重复同请求、不模拟范围分页；达到上限或无法读文件则保留缺口。
- manifest.event_log_sha256 与固定快照核对；不匹配时标记独立来源，不暗中换快照。不支持将 expected_sha256/manifest_path 传给日志下载工具。缺 stream 的 NOT_FOUND 只在有缓存陈旧证据时考虑一次明确 refresh，随后重新 inspect 建立新一轮快照；认证/配置/权限错误不靠增大尾部或重试解决。
- 引用采用每个本地日志自身 hash + 文件行号、流、container、attempt、coverage；归因核实 Caused by、触发操作、时间和恢复。权限拒绝、退出码、连接关闭、内存启动选项含义不混淆。

## Existing tool contract used by the Skill

| Input | Type | Default | Constraint |
|---|---|---|---|
| application_id | string | required | actual YARN application ID |
| attempt_id | string | required | explicit positive decimal, no null/latest |
| executor_id | string | required | driver or observed nonnegative decimal ID |
| log_type | string | stderr | stdout/stderr |
| tail_bytes | integer | 65536 | 1–1048576 |

Result example (synthetic; no log body):
```json
{"application_id":"application_1_42","attempt_id":"1","executor_id":"driver","container_id":"container_1_0042_01_000001","log_type":"stderr","requested_tail_bytes":65536,"fetched_at":"2026-10-15T00:00:00Z","coverage":"tail","local_path":"/private/evidence/stderr.log","size_bytes":1234,"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","manifest_path":"/private/evidence/manifest.json"}
```

## Risks / Trade-offs

- 工具不绑定输入快照 → 校验 manifest 来源，保留独立证据，不猜关联。
- 宿主可能无法访问服务器本地文件 → 明确只能确认下载、不能分析正文；不编造工具或旁路认证。
- 尾部不含异常开头 → 依据 coverage/时间扩大一次或停止，不能宣称整份无错误。
- 定位 ERROR 可能误判原因 → 读异常链和前后文，核实后续恢复，区分程序失败与早期连接噪声。

## Validation / Migration

先对旧 Skill 做离线行为基线，再补真实 request/result 模型验证和引用/安装检查。使用新鲜上下文的独立 Agent 对相同场景前向验证，记录不足而非宣称统计效果。现有安装脚本已递归复制参考；仅更新规范 skill，不覆盖用户安装副本或配置。用户可按既有安装流程更新副本。
