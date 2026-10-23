# Spark 运维场景 Skill 扩展实施计划

**目标：** 让现有 Spark 诊断 Skill 从运维现象进入可证伪的根因取证路径。

**架构：** 主 Skill 只增加按需路由；`operations-scenarios.md` 保留独立 S/R 目录及证据限制。现有 MCP 合同和引用规则不变。

**技术栈：** Markdown Skill、Python 3.10、pytest、uv、OpenSpec。

## Task 1.1：场景目录和路由

**文件：** 修改 `tests/unit/test_agent_skills.py`、`skills/spark-diagnosis/SKILL.md`；新增 `skills/spark-diagnosis/references/operations-scenarios.md`。

**接口：** 主 Skill 的 Markdown 链接指向新参考；参考中 `S01` 等现象编号与 `R01` 等根因编号交叉引用，不构成 MCP 参数或结果字段。

1. 在现有 Spark reference 链接测试的预期集合中加入 `references/operations-scenarios.md`，并添加测试：读取新参考，分别从 `| SNN |`、`| RNN |` 表格行提取编号，断言非空且唯一；从每行 RNN 的“关联现象”列提取 SNN，断言每个引用存在、全部 SNN 至少被一个 RNN 覆盖。
2. 运行 `PYTHONPATH=src uv run --locked pytest -q tests/unit/test_agent_skills.py::test_spark_operations_scenarios_have_valid_cross_references`；期望新文件缺失导致 RED。
3. 新增参考：先列现象，再列候选根因；每个根因写首查证据、支持条件、反证或歧义、能力缺口。更新主 Skill 描述与按需路由，明确先验证影响范围/恢复，再决定是否支持根因；不重复已有事件/容器日志合同。
4. 运行同一测试，再运行 `PYTHONPATH=src uv run --locked pytest -q tests/unit/test_agent_skills.py`，期望 GREEN。运行 Skill quick_validate；手工以“排队无 Task”“FetchFailed 后恢复”“JobSucceeded 但 Driver 退出”检查不越权归因。

## Task 2.1：使用说明与整体验证

**文件：** 修改 `README.md`、`README.zh-CN.md`；新增本变更 `verification.md`。

**接口：** README 链接指向同一新参考，不新增命令或工具参数。

1. 在双语 README 的 Spark Skill 段加入运维场景入口及“候选原因需证据/反证、YARN 与业务结果缺口”的说明。
2. 运行 `PYTHONPATH=src uv run --locked pytest -q tests/unit/test_agent_skills.py` 验证文档引用未破坏现有安装/契约测试。
3. 运行 `PYTHONPATH=src uv run --locked pytest -q tests/unit tests/contract`、`uv run --locked ruff check .`、`uv run --locked pyright`、`uv build`、`uv run --locked mcp-stdio --help`、`openspec validate --changes`、`openspec validate --specs`，以及 `git diff --check`；把实际结果和已有无关改动的边界写入 `verification.md`。
