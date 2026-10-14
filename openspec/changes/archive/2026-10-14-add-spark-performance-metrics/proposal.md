## Why

已有工具能定位失败事件，却不能直接回答“运行时间花在哪里、哪些任务形成长尾”。补充两个确定性指标工具，让 Agent 从 Stage 排名进入 Task 分布，再通过现有事件查询验证候选原因，避免把海量 Task 文本交给模型计算。

## What Changes

- Spark 插件新增 `get_spark_stage_metrics`：按 Stage attempt 返回耗时排名、TaskEnd 分类计数、成功尝试的 Input/Shuffle Read 汇总和事件引用。
- 新增 `get_spark_task_distribution`：指定 Stage attempt，返回六个固定指标的分布及按一个指标排序的有界任务列表。
- 沿用 manifest、显式 application attempt 和脱敏 JSONL SHA-256 固定快照；复用本地验证读取、时限、错误、脱敏和目录所有权。
- 扩展已有 `spark-diagnosis` Skill 的慢作业流程，复用 inspect/query 获取应用起止、任务细节、恢复和反证。
- 明确成功 TaskEnd 尝试的样本口径、缺失值、固定分位数算法、Stage 重试和聚合来源。

## Capabilities

### New Capabilities

- `spark-performance-metrics`: 两个离线性能事实工具，以及使用其结果定位瓶颈并验证候选原因的 Skill 流程。

### Modified Capabilities

无已归档能力行为变更。新增能力与已实现的 `spark-event-log-inspection` 并存，保留原工具合同。

## Non-Goals

- 不开发 DiagnosisState、Agent 后端、诊断会话 API 或持久分析文件。
- 不新增 app-summary/task-details 包装工具；复用现有事件查询。
- 不做自动根因分类、异常阈值系统、历史基准、跨应用对比或关键路径分析。
- 不新增 SQL/job 关系查询引擎、去重逻辑任务模型、实时监控或完整 Spark UI 指标。
- 不增加任意指标表达式、可配置分位数、采样算法、索引、配置项、第三方依赖或网络端点。
- 不将最长 Stage、GC 或 Shuffle 等单个指标直接解释为根因。

## Impact

- 实现计划位于现有 Spark slice，复用 `VerifiedEventLogReader`，补充 domain/result models、只读 gateway、application service、MCP adapters 和 runtime 生命周期接线。
- 测试覆盖指标口径、排序/遗漏、快照冲突、私有路径、取消、MCP schema、工具并集和原 fetch/inspect/query 回归。
- 更新已有 `skills/spark-diagnosis/SKILL.md`、README 与架构说明，不增加分发入口。
- 无缓存迁移、无依赖/配置变化。Agent 持有工作上下文，L3 仅保存现有 event log 和 manifest。
