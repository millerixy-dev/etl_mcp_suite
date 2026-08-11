---
name: zeppelin
description: Use when an agent needs to list, create, reuse, execute, cancel, inspect, or recover Apache Zeppelin notebooks and paragraphs through MCP tools.
---

# Zeppelin MCP 操作

## 核心原则

通过当前 MCP 客户端已配置的工具操作 Zeppelin。先发现同时暴露本 Skill 所需工具的 Server，再按工具名调用；不要依赖 Server 显示名称或客户端生成的命名空间。

- 只使用 MCP 工具，不用 `curl`、`requests`、Py4J 或自建脚本直连 Zeppelin REST API。
- 不在提示、代码、Notebook 或结果中写入 URL、端口、Cookie、Token、用户名或密码。
- 遵守解释器白名单、SQL 写入限制和 Shell 命令白名单。工具拒绝内容时，说明命中的安全规则；不得通过编码、拆分或换解释器绕过。
- 把 Notebook ID、Paragraph ID 和 Interpreter Setting ID 当作不透明值，只使用工具返回值或用户明确提供的值。

## 工具速查

| 工具 | 用途 | 输入 |
| --- | --- | --- |
| `list_notebooks` | 列出 Notebook 目录树 | 无 |
| `create_notebook` | 创建 Notebook | `name` |
| `add_paragraph` | 添加经过安全校验的段落 | `notebook_id`, `title`, `body` |
| `run_paragraph` | 非阻塞启动段落 | `notebook_id`, `paragraph_id` |
| `get_paragraph_status` | 查询归一化状态 | `notebook_id`, `paragraph_id` |
| `get_paragraph_result` | 获取有界结果或安全错误详情 | `notebook_id`, `paragraph_id` |
| `cancel_paragraph` | 取消活动段落 | `notebook_id`, `paragraph_id` |
| `restart_interpreter` | 重启已知且允许的解释器设置 | `setting_id` |

## Notebook 组织

显式用户或项目规则指定的根目录优先；没有规则时使用 `/agents/`。创建名称采用：

```text
<root>/<简要目的>_<YYYYMMDD>_<三位序号>
```

目的使用动词开头且不超过 20 个字符，例如 `/agents/核对订单分区_20260810_001`。创建前必须调用 `list_notebooks`：同一任务已有可复用 Notebook 时继续添加段落；没有时才创建。一个任务尽量集中在一个 Notebook 中。

## 标准执行流程

1. 调用 `list_notebooks`，按根目录和任务目的寻找可复用 Notebook。
2. 无可复用项时调用 `create_notebook`，例如：

   ```text
   create_notebook
   {"name":"/agents/核对订单分区_20260810_001"}
   ```

3. 选择部署允许的解释器前缀并调用 `add_paragraph`。不要猜测或规避解释器白名单：

   ```text
   add_paragraph
   {"notebook_id":"<opaque-id>","title":"统计最新分区","body":"%spark.sql\nSELECT COUNT(*) FROM dwd.orders WHERE dt = '2026-08-10'"}
   ```

4. 使用返回的 `paragraph_id` 调用 `run_paragraph`。该调用非阻塞。
5. 间隔约 3–5 秒调用 `get_paragraph_status`，避免无间隔高频轮询：
   - `PENDING`、`RUNNING`：继续等待。
   - `FINISHED`：调用 `get_paragraph_result`。
   - `ERROR`：调用 `get_paragraph_result` 获取有界失败详情。
   - `CANCELLED`：停止轮询并报告已取消；不要把取消误报为成功。
6. 返回结果时说明查询目的、终态、是否截断以及安全的错误信息；不要输出原始连接或认证数据。

### 慢执行处理

从 `run_paragraph` 成功返回时开始累计等待时间。段落处于 `PENDING` 或 `RUNNING` 且累计超过 **300 秒** 时，暂停自动轮询并向用户报告已等待时长与安全的任务摘要，由**用户决定**继续等待或调用 `cancel_paragraph`。

- 不得自动切换解释器、重新提交段落或把取消当作重试。
- 用户明确要求取消后，先取消并确认终态；只有用户随后明确要求重试时，才以已配置且被允许的解释器重新走完整的添加、运行和轮询流程。
- 不要猜测替代解释器名称、资源池或设置 ID；若没有用户批准的可用解释器，说明限制并等待指示。

## 取消与恢复

- 用户要求停止活动段落时，调用 `cancel_paragraph`，随后调用 `get_paragraph_status` 确认终态。若段落已经结束，报告工具返回的安全错误，不要创建替代请求。
- 只有用户明确要求，或错误证据明确指向解释器状态且已知 `setting_id` 时，才调用 `restart_interpreter`。重启后重新检查段落状态；不要猜测 Setting ID，也不要把重启当作通用重试。
- 执行失败时先依据工具返回的稳定错误类别判断配置、权限、连接、超时、输入或上游问题。修改段落内容前重新检查安全约束。

## 常见错误

| 错误 | 正确处理 |
| --- | --- |
| 未列目录就创建 Notebook | 先 `list_notebooks`，优先复用 |
| 在根目录或无意义名称下创建 | 使用已配置根目录或 `/agents/` 与可追踪名称 |
| 自行构造 ID | 只使用工具返回或用户明确提供的 ID |
| 执行后立即取结果 | 先轮询到允许取结果的终态 |
| 为通过校验而改写危险内容 | 保留拒绝，解释规则并请求安全方案 |
| 输出超大结果 | 接受有界结果，改用聚合或更小查询 |
