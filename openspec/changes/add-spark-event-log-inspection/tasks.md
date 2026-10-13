## 1. 合同与安全快照

- [x] 1.1 同步 inspection 与并行 download/executor-log 的排他工具集表述，只处理合同衔接，不等待另一能力全部完成；RED：添加严格输入/结果/ref 测试，确认失败；GREEN：定义最小 DTO 和只读 port；REFACTOR：复用现有校验。用 `uv run --locked pytest tests/unit/plugins/spark/test_models.py` 验证 nullable attempt、摘要、直接筛选、扩大文本仅限单行、空列表与类型拒绝；合同同步后运行 `openspec validate --changes --strict`。
- [x] 1.2 RED：补充多 attempt、来源/路径/symlink、缺文件、大小/摘要/身份冲突及取消测试；GREEN：实现同一遍读取中的快照验证和最小直接字段提取；REFACTOR：复用 cache 私有路径和脱敏函数，不加关系表。用 `uv run --locked pytest tests/unit/plugins/spark/test_cache.py` 验证无写入/网络回退、文件关闭和错误，不为校验再读整份文件。

## 2. 概览与精确事件查询

- [x] 2.1 RED：在新 `tests/unit/plugins/spark/test_inspection.py` 增加全文件失败信号/原因计数、证据排序、未知字段/事件和固定文本投影测试；GREEN：实现 inspect 及共享直接 ID/文本提取；REFACTOR：保持计数和文本截断独立。用 `uv run --locked pytest tests/unit/plugins/spark/test_inspection.py` 验证最多 20 入口、32 类计数、omitted、结束存在性、缺失原因 UNKNOWN，且不汇总性能指标或推断应用根因。
- [x] 2.2 RED：补充直接筛选、不跨实体扩展、stage attempt、稀有失败、多页遍历、页外原因统计、ref 回读及扩大文本测试；GREEN：实现 query；REFACTOR：复用单遍扫描与文本规则。用同一 inspection 测试命令验证页前全量计数、固定 hash、无空页循环、单行最多 32768 字符及截断标志。

## 3. MCP 与 Skill

任务 2.2 的接口验证通过后，3.1 的接线与 3.2 的 Skill/文档可以并行：源码和接线测试由 3.1 负责，Skill、安装脚本、文档和五场景取证演练由 3.2 负责。任务 4.1 等两项均验收后执行。

- [ ] 3.1 RED：扩展 Spark service/tools/plugin 和 stdio 合同失败测试；GREEN：接入两个工具、安全操作名及关闭/时限处理；REFACTOR：保持既有分层和单一目录所有权。用 `uv run --locked pytest tests/unit/plugins/spark tests/contract/test_spark_stdio.py tests/contract/test_architecture.py` 验证精确工具集、schema、安全错误、离线读取、取消/关闭以及旧 fetch 回归。
- [ ] 3.2 RED：先定义五类合成诊断场景的预期结论/证据，补 Skill 分发/发现测试；GREEN：新增 `skills/spark-diagnosis/SKILL.md`，同步既有 Skill 分发入口（如需）、README、`docs/architecture/runtime-flow.md` 与 `docs/architecture/modules.md`；REFACTOR：保持步骤简短，不加入固定轮数门槛。用 `uv run --locked pytest tests/unit/test_agent_skills.py` 验证工具名/分发；逐案演练“明确异常、重试恢复、executor 丢失原因未知、不完整、全成功”，在本任务下记录实际查询、refs 与结论核对，不能只凭关键词测试声明诊断有效。

## 4. 整体验证

- [ ] 4.1 运行 `uv sync --locked`、`uv run --locked pytest`、`uv run --locked ruff check .`、`uv run --locked pyright`、`uv build`、`uv run --locked mcp-stdio --help`、`openspec validate add-spark-event-log-inspection --strict`、`openspec validate --changes --strict` 和 `openspec validate --specs --strict`；审查整项 diff/合同一致性并在本任务下记录结果。本地真实成功日志可选验证扫描耗时、峰值内存、事件数/摘要，不入库；没有材料或未执行网络集成时明确记为跳过。
