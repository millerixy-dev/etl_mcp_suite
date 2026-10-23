## Why

现有 spark-diagnosis Skill 已有查询和因果边界，但事件含义分散，缺少按问题查找事件、字段和后续证据的参考。补齐版本明确的语义与当前可用搜索示例，让 Agent 按需构建上下文。

## What Changes

- 扩展现有 Skill 的按需参考入口，不创建第二份诊断 Skill。
- 增加 Spark 2.4.7 事件语义参考：触发含义、直接字段、关联查询及不能推出的结论，附对应版本官方源码。
- 增加基于已实现 query_spark_events 的搜索示例、分页/截断说明与 Gather–Select 取证例子；rg 仅用于搜索参考文档。
- 验证相对链接、示例参数和递归安装；同步中英文 README 的参考入口。

## Capabilities

### New Capabilities

无。本次是已有 Skill 的文档补充，设置 skip_specs: true；没有新增 MCP 或运行时能力。

### Modified Capabilities

无。保留 download、inspection、performance 工具及数据合同，不以文档变更改写运行时规格。

## Non-Goals

不实现 search_spark_events、全文/正则搜索、索引、JSONPath、额外日志获取、DiagnosisState、新配置/依赖；不安装到用户全局目录；不声明所有 Spark UI 信息都存在于 event log。

## Impact

仅修改 skills/spark-diagnosis、tests/unit/test_agent_skills.py 和 README.md / README.zh-CN.md。安装脚本已使用递归复制，无需修改脚本或生产代码。验证中不访问集群或读取凭证。
