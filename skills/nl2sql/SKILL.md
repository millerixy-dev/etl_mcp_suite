---
name: nl2sql
description: Use when a user asks a natural-language business question that requires discovering Hive tables, constructing grounded Spark SQL, executing it through Zeppelin, and explaining the result.
---

# Hive Natural Language to SQL

## 核心原则

把自然语言问题转换为 SQL 时，以真实 MCP 元数据为唯一结构依据，并通过受控 Zeppelin 段落执行。先使用 `hive` Skill，再使用 `zeppelin` Skill；不要直连 Hive、Zeppelin 或自行创建数据库访问脚本。

- 写 SQL 前必须获取涉及每张表的结构，禁止凭记忆猜库名、表名或字段名。
- SQL 中的标识符必须与 `get_table_schema` 返回值一致。
- 多个表、字段或业务含义都可能匹配时，展示候选并等待用户确认；不要自行选择后执行。
- 分区表的数据查询必须裁剪全部分区字段，并先确认分区值格式和粒度。
- 明细结果必须有界；默认 `LIMIT 1000` 或更小。
- 执行只走已配置 MCP 工具，并遵守解释器与写入安全策略。

## 所需工具

元数据发现使用：

- `list_databases`
- `list_tables`
- `get_table_schema`

Notebook 执行使用：

- `list_notebooks`
- `create_notebook`
- `add_paragraph`
- `run_paragraph`
- `get_paragraph_status`
- `get_paragraph_result`

先发现提供上述能力的已配置 MCP Server。不要依赖 Server 显示名称或客户端生成的工具命名空间。

## 工作流

### 1. 解析意图

提取并记录：业务指标或明细、时间范围、维度、过滤条件、聚合方式、排序、结果上限，以及用户已明确给出的库表线索。相对日期必须换算成明确日期，并在最终说明采用的时区和范围。

以下信息有实质歧义时先提问：

- 多个候选表或字段都符合描述。
- “收入”“活跃”“最新”等业务词没有已知口径。
- 时间范围、时区或分区选择会显著改变结果。
- 查询需要写操作，或用户目标超出只读查询。

### 2. 发现真实元数据

1. 库不明确时调用 `list_databases`。
2. 在候选库调用 `list_tables`。
3. 对查询和 JOIN 涉及的每张表调用 `get_table_schema`。
4. 需要字段注释或表定义上下文时，把 `include_ddl` 设为 `true`。
5. 建立查询对象清单：全限定表名、普通列及类型、分区列及类型、JOIN 键。

如果用户给出的对象不存在，返回少量相近候选；没有用户确认时不进入构造阶段。

### 3. 确定分区模式

`partition_columns` 非空时，先通过 `zeppelin` Skill 执行只读分区发现语句，例如：

```sql
SHOW PARTITIONS dwd.orders
```

分析有界结果中的键顺序、值格式、粒度、最新值和特殊占位值。若结果截断且无法可靠确定所需范围，向用户请求明确分区值；不要改用无界行扫描猜测分区。

除 `SHOW PARTITIONS` 这类不读取业务行的分区发现语句外，后续每条分区表查询都必须在 `WHERE` 中覆盖全部分区字段。根据用户意图和已发现格式构造等值或范围条件；不得根据字段名猜测 `yyyyMMdd`、`yyyy-MM-dd`、小时或月份粒度。

### 4. 构造 Spark SQL

- 段落正文使用部署允许的 Spark SQL 解释器前缀；常见形式是 `%spark.sql`，若被白名单拒绝则报告配置问题，不要换方式绕过。
- 字符串使用单引号，内部单引号写成两个单引号。
- 条件字面量与字段类型匹配；日期函数使用 Spark SQL 语义。
- JOIN 前验证双方键存在且类型兼容，必须提供 `ON` 条件；仅在用户明确要求时使用 `CROSS JOIN`。
- 大表先按分区过滤再 JOIN。
- 明细查询加 `LIMIT`，默认不超过 1000；结果规模明确受控的聚合可不加。
- 默认只生成只读 `SELECT` 或元数据发现语句。写操作不属于本 Skill 的自动执行范围。

#### ETL 或写入设计（仅在用户明确请求时）

先分别调用 `get_table_schema` 发现**源表**和**目标表**的列、类型及分区字段，再列出逐字段映射。类型不兼容时使用**显式 CAST** 或适用的 Spark SQL 转换；不得依赖隐式转换。

`insert_time`、`update_time` 等表示数据发生或入库时刻的字段应保留源数据的**事件时间**语义，而不是默默替换为 ETL 执行时刻。源表缺少可信事件时间字段、值为空或语义不明确时，说明缺口并请求用户指定策略。

该步骤只产出经过验证的设计或 SQL 草案。任何写入执行仍需用户明确批准，并受 Zeppelin 已配置的解释器、写入白名单和安全规则约束；被拒绝时不得改写目标库、直连后端或通过其他客户端绕过限制。

### 5. 自动校验，最多五轮

每轮逐项检查：

1. 所有库、表、字段和 JOIN 键都出现在已获取元数据中。
2. 每张分区表的全部 `partition_columns` 都有格式匹配的过滤条件。
3. SQL 与选定解释器兼容，段落前缀存在。
4. JOIN 无隐式笛卡尔积，聚合字段满足分组规则。
5. 明细结果有 `LIMIT`，查询保持只读且范围合理。

未通过时只修正对应项并重新校验。五轮后仍不通过，停止执行并展示：当前 SQL、各轮失败项、相关元数据摘要和需要用户决定的问题。

### 6. 通过 Zeppelin 执行

遵循 `zeppelin` Skill 的完整流程：

1. `list_notebooks`，复用当前任务 Notebook；没有时 `create_notebook`。
2. `add_paragraph` 添加已校验正文。
3. `run_paragraph` 非阻塞启动。
4. `get_paragraph_status` 低频轮询到终态。
5. `FINISHED` 或 `ERROR` 时调用 `get_paragraph_result`；其他终态按 Zeppelin Skill 处理。

执行错误时根据稳定错误类别处理。SQL 错误必须回到元数据或构造步骤，重新完成校验后才能重试；同一错误重复出现时停止猜测并请求用户或维护者介入。

### 7. 解释结果

返回：问题口径、明确时间/分区范围、使用的表、聚合或限制方式、结果含义，以及是否被截断。空结果不是自动失败；先检查分区和过滤条件，再说明可能原因。不要泄露原始连接信息、凭据、环境变量、堆栈或无界上游响应。

## 示例骨架

用户问“统计武汉上个月的招聘记录数”时：

1. 通过 `list_databases`、`list_tables` 找候选表。
2. 通过 `get_table_schema` 确认城市字段和分区列。
3. 通过 `SHOW PARTITIONS` 确认日期格式与可用范围。
4. 构造只使用已确认字段的 `COUNT(*)`，加入完整分区范围和城市条件。
5. 五项校验通过后，通过 Zeppelin Notebook 执行并解释计数口径。

不要把“公司名”直接猜成 `company_name`，也不要把“上个月”直接猜成某种分区格式。

## 常见错误

| 错误 | 正确处理 |
| --- | --- |
| 先写 SQL 再补查结构 | 删除未验证假设，先完成元数据清单 |
| 只验证主表 | 对 JOIN 的每张表分别调用 `get_table_schema` |
| 仅过滤部分分区列 | 发现完整分区键和值模式后补齐 |
| 候选冲突时自行选择 | 展示候选并等待确认 |
| 用脚本或直连执行 | 使用 `zeppelin` Skill 的 MCP 工作流 |
| 拉取大量明细 | 聚合、缩小分区范围或添加 `LIMIT` |
