## 1. 场景取证编排

- [x] 1.1 RED：先加场景与根因目录交叉引用完整性的测试并确认失败；GREEN：扩展主 Skill 的运维入口，新增现象、候选根因、证据与反证参考；REFACTOR：去除与现有事件/日志参考重复的说明。用 `PYTHONPATH=src uv run --locked pytest -q tests/unit/test_agent_skills.py`、Skill quick_validate 和三类离线场景核对完成验证。

## 2. 使用说明和整体校验

- [x] 2.1 更新 README/README.zh-CN.md 中的 Skill 使用说明，并核对新参考与实际 MCP 能力一致。运行完整单元/契约测试、lint、type check、build、console smoke，以及 `openspec validate --changes`、`openspec validate --specs`；审查 diff 并记录精确结果。
