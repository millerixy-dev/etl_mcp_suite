## Why

已有下载工具将 Spark event log 保存为可跨会话复用的本地证据，但 Agent 还不能按用户问题定位失败事件、验证恢复情况并引用证据。先补齐 Gather–Select 的最小闭环，让后续诊断工具建设由实际取证缺口驱动。

## What Changes

- 在现有 Spark MCP 插件新增 `inspect_spark_event_log`：扫描指定快照，返回事件分布、失败信号、TaskEnd 原因分布及少量证据入口。
- 新增 `query_spark_events`：按事件自身字段精确筛选，返回全量匹配计数、原因分布及分页证据；按行号回读时允许有界地扩大错误文本。
- 新增一份 `spark-diagnosis` Skill，指导“确认问题 → 提出假设 → 选择证据 → 检查反证/恢复 → 结论或缺口”的循环。
- 用 manifest、attempt 和文件 SHA-256 固定诊断快照；分析工具只读已有脱敏 JSONL，不隐式下载或刷新。
- 明确缺失结束事件、字段未知、脱敏及输出截断的影响，避免将 task 重试失败直接当作 application 根因。

## Capabilities

### New Capabilities

- `spark-event-log-inspection`: 两个本地分析工具的精确筛选、计数、分页、证据与安全契约，以及消费这些结果的最小诊断 Skill。

### Modified Capabilities

无已归档能力的行为变更。沿用活动变更 `add-spark-event-log-download` 的缓存格式与获取契约；工具集合的跨变更衔接见 Impact。

## Non-Goals

- 不实现自动根因分类器、Agent 后端、通用查询 DSL、向量检索或持久索引。
- 不实现跨实体自动查询扩展、性能指标汇总、逐事件语义完整性校验或通用递归 JSON 裁剪器。
- 不复刻 Spark UI，不承诺全部 UI 指标，不做完整性能调优或实时运行监控。
- 不新增下载路径、认证方式、配置项或第三方依赖，不保留额外原始 ZIP。
- 不在工具内拉取 YARN/Driver/Executor 日志；需要这些证据时由 Skill 描述缺口或调用另一个已可用工具。
- 不把两个已验证的成功作业样本当作失败根因诊断验收材料。

## Impact

- 代码计划局限于 `src/mcp_stdio/plugins/spark/`、相关 unit/contract 测试及 README/架构说明；Skill 计划放在 `skills/spark-diagnosis/SKILL.md`，遵循现有仓库 Skill 分发方式。
- 缓存继续使用已有 `manifest.json` 和 `eventlog-*.jsonl`；本能力不写摘要、索引或诊断状态文件。
- 与并行设计 `add-spark-executor-log-fetch` 互补，无实现依赖。每份能力只声明自己贡献的工具；实际进程精确工具集取已实现 Spark 能力的并集，不能混入其他插件工具。实施任务 1.1 同步跨变更的排他表述；精确工具集测试按已实现能力的并集衔接，不等待 executor-log 实现。
- 预期下载能力加本能力共有三个工具；若 executor-log 能力同时落地则共有四个。下载接口与原有配置保持兼容。
