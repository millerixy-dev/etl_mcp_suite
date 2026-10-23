## Why

现有 Spark 诊断 Skill 只笼统说明外部日志取证，未编排已实现的 fetch_spark_executor_log。Driver 在提交 Job 前失败时，event log 可以全是成功事件；仅查看 stderr 也可能遗漏 stdout 中的异常堆栈。

## What Changes

- 给现有 Skill 增加 Driver / Executor 日志取证触发条件与按需参考。
- 明确 MCP 下载、私有本地正文读取、identity/hash/provenance 核对、跨流搜索、有限尾部扩大及证据不足时停止。
- 更新事件搜索入口、中英文使用说明，以离线行为场景和真实数据模型检查示例。

## Capabilities

### New Capabilities
无。

### Modified Capabilities
无；仅文档和 Skill 编排，复用已批准的 spark-executor-log-fetch 与 event-log inspection 合同，skip_specs=true。

## Non-Goals

不新增 MCP 参数、读取工具、诊断状态、认证方式或下载脚本；不修改服务端运行行为，不批量抓取全部 executor，不自动修权限/重跑业务作业。

## Impact

skills/spark-diagnosis/SKILL.md、references/container-logs.md、references/event-search.md、README.md、README.zh-CN.md、tests/unit/test_agent_skills.py。不修改本轮开始时已有的源码、测试和部署配置改动。
