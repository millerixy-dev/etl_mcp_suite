## 1. 现有 Skill 的语义与搜索参考

- [x] 1.1 RED：记录旧 Skill 的离线独立检索基线，补相对链接、真实 QueryRequest 示例和递归安装资源验证；GREEN：增加两份引用参考与 SKILL.md 路由，并同步中英文 README；REFACTOR：按需披露、去掉重复规则。用 `UV_NO_EDITABLE=1 uv run --locked pytest tests/unit/test_agent_skills.py`、Skill quick_validate 和离线独立场景验证引用、事件含义与合法搜索调用；记录真实结果和限度。

## 2. 整体验收

- [x] 2.1 执行完整 pytest、ruff、pyright、uv build、console help、严格 OpenSpec change/changes/specs 验证和独立文档/合同评审；用精确命令和结果记录验证，再标记完成。不访问在线集群，不声明未运行的集成测试或 Agent 效果改善通过。
