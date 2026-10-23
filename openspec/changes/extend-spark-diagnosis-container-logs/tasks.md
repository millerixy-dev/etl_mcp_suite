## 1. Skill 编排与契约

- [x] 1.1 RED：记录旧 Skill 的离线行为基线并运行新增示例模型/引用测试确认缺口；GREEN：加入 Driver/Executor 日志参考、主 Skill 路由、事件搜索衔接和双语 README；REFACTOR：删除重复指导，用 `PYTHONPATH=src uv run --locked pytest -q tests/unit/test_agent_skills.py`、Skill quick_validate 和独立离线前向场景核对工具参数、跨流取证、来源/coverage、恢复与停止条件。

## 2. 整体验证

- [x] 2.1 评审最终文档和真实工具合同的一致性，运行完整 pytest、ruff、pyright、uv build、console smoke、strict OpenSpec changes/specs 与 diff 检查；将精确结果与行为验证局限写入 verification.md，再完成本 change。不调用真实集群，不安装或覆盖用户 Skill 副本。
