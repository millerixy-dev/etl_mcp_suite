---
name: hive
description: Use when an agent needs to discover Hive databases or tables, inspect columns and partitions, retrieve table DDL, or validate identifiers before a data query.
---

# Hive MCP 元数据查询

## 核心原则

Hive MCP 能力只读且仅限元数据。先发现同时暴露 `list_databases`、`list_tables`、`get_table_schema` 的已配置 MCP Server，再通过当前客户端的标准 MCP 接口调用；不要依赖 Server 显示名称或客户端生成的工具前缀。

- 查询库、表、字段、分区字段或 DDL 时，必须先使用本 Skill 的 MCP 工具。
- 不使用 PyHive、JDBC、Thrift、REST、Shell 或临时脚本绕过元数据工具。
- 不把 SQL、凭据、连接地址或认证信息放入工具参数。
- 库名和表名必须来自工具结果，并符合 `[A-Za-z_][A-Za-z0-9_]*`；不要自行加引号、转义或拼接不可信标识符。

## 工具速查

| 工具 | 用途 | 输入 | 主要结果 |
| --- | --- | --- | --- |
| `list_databases` | 列出数据库 | 无 | `databases`, `cached` |
| `list_tables` | 列出指定库的表 | `database` | `database`, `tables`, `cached` |
| `get_table_schema` | 获取普通列、分区列和可选 DDL | `database`, `table`, 可选 `include_ddl` | `columns`, `partition_columns`, `ddl`, `cached` |

`include_ddl` 默认是 `false`。仅在需要建表语句、存储格式或字段注释上下文时设为 `true`。

## 标准流程

1. 已知准确库名和表名时，直接调用 `get_table_schema` 验证并获取结构。
2. 不确定库名时，先调用：

   ```text
   list_databases
   {}
   ```

3. 确定候选库后调用：

   ```text
   list_tables
   {"database":"dwd"}
   ```

4. 对选定表调用：

   ```text
   get_table_schema
   {"database":"dwd","table":"orders","include_ddl":false}
   ```

5. 返回结果时区分 `columns` 与 `partition_columns`，并说明 `cached`。不要把分区列误当作普通列，也不要声称缓存结果是实时刷新。

如果多个库或表都可能匹配业务描述，列出少量候选及匹配原因，请用户确认后再继续。不要仅凭名称相似度选择并执行后续数据查询。

## 能力边界与降级

本 Skill 能完成：

- 列举数据库和表。
- 获取字段名、类型、注释、顺序及分区字段。
- 获取 `SHOW CREATE TABLE` 对应的 DDL 结果。

本 Skill 不能完成：

- 执行调用方提供的 `SELECT`、DML 或 DDL。
- 读取数据行、统计行数或枚举真实分区值。
- 执行跨表关联或其他任意 SQL。

需要数据行或 SQL 执行时：

1. 先用 `get_table_schema` 验证涉及的每张表和字段。
2. 再使用 `zeppelin` Skill 执行经过约束的段落。
3. 对分区表，执行前必须确定分区值模式并添加分区裁剪。

不要为了执行 SQL 而自行建立 Hive 连接，也不要用 Zeppelin 重复执行本 Skill 已能完成的 `SHOW DATABASES`、`SHOW TABLES` 或 `DESCRIBE`。

## 错误处理

| 场景 | 处理 |
| --- | --- |
| `INVALID_INPUT` | 检查标识符格式，并从工具结果重新选择，不要转义绕过 |
| `NOT_FOUND` | 重新列库或列表，展示相近候选 |
| 认证、权限或连接错误 | 报告稳定错误类别和关联 ID，请维护者检查 Server 配置 |
| 未知响应形状 | 停止推断，不根据部分字段编造结构 |
| 用户要求查看数据 | 说明元数据边界，切换到 `zeppelin` Skill |

## 常见错误

- 凭记忆猜测 `company_name`、`dt` 等字段，而不调用 `get_table_schema`。
- 逐库扫描大量表却不先根据用户意图缩小范围。
- 默认请求 DDL，增加无关输出。
- 把 `partition_columns` 为空解释成查询失败；它也可能表示非分区表。
- 在错误信息中输出连接对象、环境变量或原始上游响应。
