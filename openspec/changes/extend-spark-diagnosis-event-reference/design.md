## Context

见 proposal.md。现有 Skill 保留固定快照、直接 ID 查询、分页、失败恢复及性能取证；query_spark_events 没有全文、regex、JSONPath 或任意字段投影参数。安装器使用 cp -R 复制完整 Skill 目录。

## Goals / Non-Goals

**Goals:** 让 Agent 按具体问题找到事件含义、真实字段和下一查询；参考按需读取，查询示例符合实际 schema。

**Non-Goals:** 无生产代码、工具合同、配置、依赖或上游端点变更；不把 rg 原始日志匹配当成 MCP 验证过的证据；不建立另一个 Skill 或状态管理器。

## Decisions

### 1. 在现有 Skill 下渐进披露

新增 references/spark-events-2.4.7.md（事件/原因/指标含义）和 references/event-search.md（问题到查询、真实 JSON 示例和上下文选择）。SKILL.md 只增加读取入口和工具能力边界。相比另建 Skill，此方式避免重复诊断流程和安装发现规则；相比全部内联，减少每次加载成本。

语义表区分原始 JSON 字段、现有 query 返回投影和筛选能力。JSON 中存在的嵌套 ID 不保证被 direct_ids 提取；缺失事件不自动表示事情未发生。应用/Stage/Task attempt、任务 Index 和 Task ID 分开说明。

### 2. 只教已实现的搜索方式

MCP 示例使用 query_spark_events，至少包含 SQL→Job→Stage、稀有 FetchFailed 和单行扩展。把命名事件与 Task End Reason 枚举分开，UNKNOWN 明确为工具缺失值标签，文本仅在已返回的 details 中阅读；没有 text/pattern/regex 参数。rg -n -F -- 仅搜索参考文档，不绕过 MCP、读取 ZIP 或裁剪信息。

参考中的每个 JSON 代码块均为 query_spark_events 请求，不含结果或其他接口。以下为所教接口的参数表（完整范围与合同仍见已交付 inspection 设计和实际 schema）：

| Input | Type | Default | Range | Required |
| --- | --- | --- | --- | --- |
| manifest_path | string | none | 已下载 manifest 的绝对路径 | yes |
| attempt_id | string or null | none | 实际 application attempt；null 不选 latest | yes |
| expected_sha256 | string | none | inspect 的 64 位小写脱敏摘要 | yes |
| event_types | list[string] or null | null | 1–16 完整 Event 名 | no |
| execution_id / job_id / stage_id / task_id | integer or null | null | 0..2^63-1，直接 ID | no |
| stage_attempt_id | integer or null | null | 须同时传 stage_id | no |
| executor_id | string or null | null | 直接 ID，沿用现有校验 | no |
| task_end_reason | string or null | null | 精确 Reason 值 | no |
| lines | list[integer] or null | null | 1–20 个不同 1-based 行号 | no |
| after_line | integer | 0 | 仅控制页起点 | no |
| limit | integer | 20 | 1–20 | no |
| max_detail_chars | integer | 2048 | 1–32768；>2048 须单 lines 且 limit=1 | no |

代表性结果（没有匹配，例示结构而非真实诊断）：

```json
{"snapshot":{"application_id":"application_1_42","attempt_id":"1","sha256":"0000000000000000000000000000000000000000000000000000000000000000"},"matched_count":0,"task_end_count":0,"task_end_reasons":[],"reasons_omitted":0,"events":[],"returned_count":0,"next_after_line":null,"coverage":{"application_start_seen":true,"application_end_seen":true}}
```

无新增可配置设置，因此无需新增文件或 env-only 启动配置；现有文件/env-only 配置与启动示例继续由 README 和下载设计维护，不重复或修改凭证方案。

### 3. 官方版本来源与验证边界

- Core 事件与字段：[SparkListener](https://github.com/apache/spark/blob/v2.4.7/core/src/main/scala/org/apache/spark/scheduler/SparkListener.scala)、[JsonProtocol](https://github.com/apache/spark/blob/v2.4.7/core/src/main/scala/org/apache/spark/util/JsonProtocol.scala)。
- Task 原因：[TaskEndReason](https://github.com/apache/spark/blob/v2.4.7/core/src/main/scala/org/apache/spark/TaskEndReason.scala)。
- SQL 事件：[SQLListener](https://github.com/apache/spark/blob/v2.4.7/sql/core/src/main/scala/org/apache/spark/sql/execution/ui/SQLListener.scala)。
- 日志是否记录：[EventLoggingListener](https://github.com/apache/spark/blob/v2.4.7/core/src/main/scala/org/apache/spark/scheduler/EventLoggingListener.scala)。

参考说明以 Apache Spark 2.4.7 为准，厂商事件先从 inspect 获取实际完整名，未知字段/原因保持未知。原始 Task Metrics 含多种时间单位，不把 CPU/Shuffle Write 纳秒当作现有六项毫秒指标。

验证实际 Markdown 相对引用可解析且安装后内容一致；JSON 示例交给真实 QueryRequest 严格校验。记录旧 Skill 的独立检索基线，再用新 Skill 做同范围离线场景验证，评价引用和查询有效性，不能仅凭关键词测试声明诊断改善。

## Risks / Trade-offs

- [部分字段被现有投影省略] → 逐项说明可查询/可阅读范围，32768 只能扩大已有投影；不宣称全文读取。
- [示例身份或摘要被照抄] → 标注为格式示例，要求从当前 manifest/inspect 结果替换，不臆造真实快照。
- [参考过长] → 入口按问题选择两份参考，参考有标题与 rg 示例；不强制全量加载。
- [包内资源丢失] → 扩展既有真实安装测试逐文件比较，包括 references；不改正常安装行为。

## Migration Plan

无需运行时迁移。提交规范 Skill 与资源，由用户按原安装方式更新；本任务不覆盖已安装的用户 Skill 或 MCP 配置。回滚移除新增参考、入口及对应测试即可。
