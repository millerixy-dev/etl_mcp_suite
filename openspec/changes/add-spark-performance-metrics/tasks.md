## 1. 指标合同与计算口径

- [x] 1.1 RED：在现有 `tests/unit/plugins/spark/test_models.py` 补两个请求、命名结果和严格输入失败测试；GREEN：定义最小指标 DTO 与只读 gateway 合同；REFACTOR：复用现有 snapshot/ref/coverage 和输入校验。用 `uv run --locked pytest tests/unit/plugins/spark/test_models.py` 验证配对 Stage 选择、固定 order_by、limit、nullable application attempt、摘要、未知参数和精确结果字段；运行 `openspec validate --changes --strict` 核对工具并集衔接。
- [x] 1.2 RED：新增 `tests/unit/plugins/spark/test_metrics.py` 的单事件指标/样本口径测试；GREEN：实现六个固定指标提取、Success/非成功/未知分类和 nearest-rank；REFACTOR：共享数值有效性规则，不加通用指标表达式。用 `uv run --locked pytest tests/unit/plugins/spark/test_metrics.py` 验证合法零、缺对象/字段、bool/string/float/负数、非法时间、Shuffle 缺分量、两个大分量求和、重试/推测样本及空/单/双样本分位数。

## 2. 两个离线事实工具

- [x] 2.1 RED：在 metrics 测试补 Stage attempt 分组、未归属事件、生命周期选取、排名/遗漏与筛选；GREEN：复用验证 reader 实现 `get_spark_stage_metrics`；REFACTOR：只保留计数、和及必要 refs。用 `uv run --locked pytest tests/unit/plugins/spark/test_metrics.py` 验证重试分开、缺/逆序时间为 null、TaskEnd-only 组、排序并列、全组计数先于 limit、成功样本总量及来源 ref；沿用快照冲突、私有路径和无写入/网络合同。
- [ ] 2.2 RED：补分布与有界 Task 排名、独立缺失计数、各 order_by、refs 回读与取消测试；GREEN：实现 `get_spark_task_distribution`，仅保留选定组必要数值和至多 limit 个任务投影；REFACTOR：复用字段提取与口径，保证原总时限和关闭等待。用 `uv run --locked pytest tests/unit/plugins/spark/test_metrics.py tests/unit/plugins/spark/test_cache.py` 验证全部成功样本先于排名、并列按行号、未知 ID 保持 null、零成功/零匹配、末端摘要冲突不发布结果、取消/超时关闭和 refs 对应原事件。

## 3. MCP 接线与 Agent 工作流

- [ ] 3.1 RED：扩展现有 service/tools/plugin、公共 operation 名和 stdio/架构合同失败测试；GREEN：接入两个工具并保持旧三项兼容、单一目录 owner 和安全公有结果边界；REFACTOR：遵守 service→port 依赖方向。用 `uv run --locked pytest tests/unit/core/test_errors.py tests/unit/plugins/spark tests/contract/test_spark_stdio.py tests/contract/test_architecture.py tests/unit/test_registry.py` 验证已实现工具精确并集、schema、离线调用、错误/脱敏、清理以及 fetch/inspect/query 回归。
- [ ] 3.2 RED：定义三组合成慢作业取证材料及预期事实/候选原因边界，补现有 Skill 发现/合同测试；GREEN：扩展 `skills/spark-diagnosis/SKILL.md`、README 和架构文档；REFACTOR：流程保持简短，无固定诊断轮数或新状态。用 `uv run --locked pytest tests/unit/test_agent_skills.py` 验证工具名与工作流，并通过实际 MCP 演练“大 Shuffle 与长尾同现”“数据量相近而 Fetch Wait 高”“重试且部分指标缺失”；在本任务下记录真实调用输入/数值/计数/refs/结论核对，不能仅凭关键词测试声明诊断有效。

## 4. 整体验证

- [ ] 4.1 执行 `uv sync --locked`、`uv run --locked pytest`、`uv run --locked ruff check .`、`uv run --locked pyright`、`uv build`、`uv run --locked mcp-stdio --help`、`openspec validate add-spark-performance-metrics --strict`、`openspec validate --changes --strict`、`openspec validate --specs --strict` 和整项代码/经济性评审，记录实际结果后验收。使用可用的真实私有本地样本验证计数/摘要/refs并记录扫描耗时与进程峰值；无材料或未运行 live integration 时明确跳过，不把小成功样本宣称为100 MB或真实根因验收。
