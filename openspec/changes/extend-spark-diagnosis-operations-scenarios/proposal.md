## Why

现有 Spark 诊断 Skill 已能取证失败、慢作业和容器日志，但缺少从运维人员观察到的现象进入相应取证路径的索引。用户希望先按现象定位场景，再逐项验证候选 root cause，而不是将单个错误事件直接当作根因。

## What Changes

- 扩展 `spark-diagnosis` 的触发描述与主文件路由，覆盖提交、排队、执行、重试、终态、输出和证据缺失等运维表现。
- 新增按“现象 → 候选根因 → 首查证据 → 支持/反证 → 能力缺口”组织的按需参考，并让结论继续遵守现有快照、来源和恢复检查规则。
- 增加最小的 Skill 结构/链接测试和面向真实工具合同的离线场景验证，更新用户使用说明。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无；本次只改 Agent Skill 的诊断编排和文档，不改 MCP 工具、输入输出合同或服务端行为，使用 `skip_specs: true`。

## Non-Goals

不新增自动根因分类器、阈值、MCP 参数、上游 API、后台状态或自动修复/重跑动作；不把 Spark 事件日志无法证明的 YARN/存储/业务事实写成确定结论；不覆盖已安装的用户 Skill 副本。

## Impact

`skills/spark-diagnosis/SKILL.md`、一份新的场景参考、`tests/unit/test_agent_skills.py` 及 README 中的 Skill 说明。保留本轮开始时已有的未提交 Spark 日志改动。
