# 验证记录（2026-10-15）

## TDD 与 Skill 取证行为

- RED：`PYTHONPATH=src uv run --locked pytest -q tests/unit/test_agent_skills.py::test_spark_operations_scenarios_have_valid_cross_references` 因 `operations-scenarios.md` 不存在而失败，确认测试能检出缺失参考。
- GREEN：新增现象/根因目录及主 Skill 路由后，`PYTHONPATH=src uv run --locked pytest -q tests/unit/test_agent_skills.py` 为 30 passed。
- `uv run --locked python /Users/liji/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/spark-diagnosis`：`Skill is valid!`。
- 离线场景核对：排队无 Task 只形成 R01/R02 候选，缺 YARN 分配诊断不判资源不足；FetchFailed 后若 Stage/Job 恢复，只报告局部故障及恢复，不认定应用失败或磁盘/网络根因；JobSucceeded 后 Driver 退出继续查 Driver 双流与外部终态，不把该 Job 的成功升级为应用成功。这是文档逻辑核对，不是一次真实集群诊断。

## 完整检查

| 命令 | 实际结果 |
| --- | --- |
| `PYTHONPATH=src uv run --locked pytest -q` | 2088 passed，6 skipped，7 deselected；集成测试未运行 |
| `uv run --locked ruff check .` | All checks passed |
| `uv run --locked pyright` | 0 errors，0 warnings；工具提示有新版本，不影响检查结果 |
| `uv build` | sdist 和 wheel 均构建成功 |
| `uv run --locked --no-editable mcp-stdio --help` | exit 0，显示内置插件命令参数 |
| `openspec validate --changes --strict` | 21 passed，0 failed；另有既存归档提示 |
| `openspec validate --specs --strict` | 3 passed，0 failed；另有既存长度提示 |
| `git diff --check` | exit 0 |

本变更没有调用实时 Spark/YARN 服务，也没有修改服务端合同、认证或安装的用户 Skill 副本。工作区原有未提交的 Spark 容器日志与凭据脱敏改动未纳入本变更的实现范围。
