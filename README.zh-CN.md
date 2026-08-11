# mcp-stdio

[English](README.md) | 简体中文

一个轻量级、基于插件的 MCP（Model Context Protocol）stdio Server。每个子进程只加载一个内置插件，并且只向 MCP Host 暴露该插件的工具。

内置插件包括：用于只读 HiveServer2 元数据查询（数据库、表、字段、分区与可选 DDL）的 **Hive schema plugin**、用于 **Zeppelin 笔记本执行**的插件，以及用于 **DolphinScheduler 调度**的插件。

## 前置条件

- Python 3.10 或更高版本
- 用于项目和依赖管理的 [uv](https://docs.astral.sh/uv/) 0.11.28 或更高版本（当前验证版本为 0.11.28）
- 可从当前进程访问的 HiveServer2 端点（仅在调用 Hive 工具时需要）

### 安装 uv（macOS）

使用 Homebrew 安装：

```bash
brew install uv
```

或使用 [官方独立安装脚本](https://docs.astral.sh/uv/getting-started/installation/)：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

如果安装脚本更新了 Shell 配置，请打开新的终端窗口，然后确认版本：

```bash
uv --version
```

## 安装项目

克隆仓库后，使用 uv 按锁文件同步环境：

```bash
git clone https://github.com/millerixy-dev/etl_mcp_suite.git
cd etl_mcp_suite
uv sync --frozen
```

该命令使用已提交的 `uv.lock` 在隔离环境中安装包和命令行入口 `mcp-stdio`。

## Agent Skills

客户端无关的 Hive、Zeppelin 和自然语言查询 Skill 统一维护在 `skills/hive`、`skills/zeppelin` 与 `skills/nl2sql`。根据正在使用的 MCP 客户端，将相同的规范文件安装到当前项目：

```bash
./scripts/install-skills-codex.sh
./scripts/install-skills-trae.sh
```

第一条命令安装到 `.codex/skills`，第二条安装到 `.trae/skills`。如需指定其他项目目录，传入 `--project-root /path/to/project`。若任一受管理的 Skill 已存在，安装会在复制前停止；请先审查本地定制内容，确认安全后才使用 `--force` 覆盖。不会影响无关的 Skill 目录。

### 同时为 Codex 安装 Skill 和本地 MCP Server

对于 Codex，一条命令即可安装 Skill、将当前源码检出作为可编辑 uv 工具暴露，并管理目标项目的 `.codex/config.toml`：

```bash
./scripts/install-skills-codex.sh --project-root /path/to/project --with-mcp
```

该模式等效于执行 `uv tool install --editable <this-repository> --reinstall`。Codex 启动稳定的 `mcp-stdio` 命令；每个新启动的 MCP 进程都会从当前检出导入代码，因此修改本地源码后无需重写 `.codex/config.toml`。`uv tool dir --bin` 返回的工具可执行目录必须已位于 `PATH` 中。

安装器管理一个带标记的配置块，其中包含 `mcp_servers.hive` 和 `mcp_servers.zeppelin`。它使用 Codex 的 `env_vars` 将变量名从启动 Codex 的环境传入；不会将凭据值、Python 路径、虚拟环境路径或 `PYTHONPATH` 写入 TOML 文件。启动 Codex 前请导出必需变量：

Codex 也支持在 `[mcp_servers.<name>.env]` 中直接配置字面值，但这些值会以明文保存在 `.codex/config.toml`。安装器刻意不为凭据生成这种形式。

```bash
export HIVE_HOST=<hive-host>
export HIVE_USERNAME=<your-ldap-user>
export HIVE_PASSWORD=<your-ldap-password>
export ZEPPELIN_BASE_URL=<zeppelin-base-url>
# 可选的 Zeppelin 登录信息：要么同时设置，要么都不设置。
export ZEPPELIN_USERNAME=<zeppelin-user>
export ZEPPELIN_PASSWORD=<zeppelin-password>
# 显式允许的解释器 JSON 数组：
export ZEPPELIN_ALLOWED_INTERPRETERS='["spark.sql", "spark.pyspark"]'
```

缺少 `HIVE_HOST`、`HIVE_USERNAME`、`HIVE_PASSWORD` 或 `ZEPPELIN_BASE_URL` 时，安装器只会提示缺失的变量名，安装仍会成功，以便稍后再配置启动环境。使用 `--force --with-mcp` 重复执行会刷新受管理的 Skill，并替换唯一一个受管理 TOML 块，同时保留其他 Codex 设置。未标记的 Hive 或 Zeppelin 配置表被视为用户自管内容，绝不会被覆盖。Trae 安装器目前只安装 Skill，并会拒绝 `--with-mcp`。

## 配置

Hive 插件可以单独或组合使用以下两种方式配置：

- 带版本号的 YAML 或 JSON **配置文件**（通过 `--config` 传入）；
- **仅使用环境变量**（不需要 `--config`）。

两种方式下，凭据都只能通过环境变量提供；它们不会出现在配置值、工具参数或日志中。

### 配置文件（可选）

完整示例请参见 `docs/examples/hive.yaml` 和 `docs/examples/hive.json`。`--config` 参数是可选的。

```yaml
version: 1
plugin: hive
settings:
  host: hive.example.internal
  port: 10001
  database: catalog
  cache_ttl_seconds: 60
secrets:
  username: HIVE_USERNAME
  password: HIVE_PASSWORD
```

启动进程前导出被引用的环境变量：

```bash
export HIVE_USERNAME=<your-ldap-user>
export HIVE_PASSWORD=<your-ldap-password>
```

### 仅使用环境变量启动

省略 `--config`，并通过 `<PREFIX>_<FIELD>` 环境变量提供每个字段。Hive 插件的前缀为 `HIVE`，因此每个 settings 和 secrets 字段都映射到一个变量：

| 字段 | 变量 | 是否必需 |
| --- | --- | --- |
| `settings.host` | `HIVE_HOST` | 是 |
| `settings.port` | `HIVE_PORT` | 否（默认 `10000`） |
| `settings.database` | `HIVE_DATABASE` | 否（默认 `default`） |
| `settings.cache_ttl_seconds` | `HIVE_CACHE_TTL_SECONDS` | 否（默认 `30`） |
| `secrets.username` | `HIVE_USERNAME` | 是 |
| `secrets.password` | `HIVE_PASSWORD` | 是 |

```bash
export HIVE_HOST=<hive-host>
export HIVE_USERNAME=<your-ldap-user>
export HIVE_PASSWORD=<your-ldap-password>
uv run mcp-stdio --plugin hive
```

缺少必需变量时，进程会快速以 `CONFIG_ERROR` 失败，并只说明变量名（例如 `HIVE_HOST`），不会暴露任何凭据值。

### 优先级

当同时提供 `--config` 文件和环境变量时，环境变量具有最高优先级：

1. `<PREFIX>_<FIELD>`（例如 `HIVE_PORT`）
2. `MCP_STDIO__SETTINGS__<FIELD>`（通用覆盖，例如 `MCP_STDIO__SETTINGS__CACHE_TTL_SECONDS=120`）
3. 文件中的值
4. 模型默认值

所有覆盖值均按与文件值相同的规则验证。凭据也遵循相同优先级：`<PREFIX>_<FIELD>` 的值会覆盖文件中的凭据引用。

### 安全说明

- `secrets` 下的值是环境变量**名称**，不是凭据本身。
- 运行时绝不会向 stdout、MCP 结果或日志写入凭据、令牌或授权数据。应用日志写入 stderr，并自动脱敏密钥。
- Hive 插件仅提供元数据功能：它不接受或执行调用方提供的 SQL，只会针对已验证标识符生成 `SHOW DATABASES`、`SHOW TABLES`、`DESCRIBE` 以及可选的 `SHOW CREATE TABLE` 语句。

## 使用

通过 stdio 直接运行 Hive 插件。使用配置文件时：

```bash
uv run mcp-stdio --plugin hive --config docs/examples/hive.yaml
```

或者仅使用环境变量（不带 `--config`）：

```bash
uv run mcp-stdio --plugin hive
```

> **说明：** 在当前环境中，`uv run` 可能因缓存权限错误而失败。可改用虚拟环境解释器：`PYTHONPATH=src .venv/bin/python -m mcp_stdio --plugin hive`。

### MCP Host 配置

通过 `mcp-stdio` 入口和 `--plugin` 参数向本地 MCP Host 注册 Hive 插件。上方的 Codex 安装器会完成此注册，无需绝对检出路径。每个插件实例都是隔离的子进程，拥有独立的配置、凭据、连接、缓存和故障域。`--config` 是可选的；仅环境变量配置无需服务端配置文件。其他 MCP Host 也可使用等效的命令名注册与环境变量转发能力：

```json
{
  "mcpServers": {
    "hive": {
      "command": "mcp-stdio",
      "args": ["--plugin", "hive"]
    }
  }
}
```

### 调试日志

传入 `--debug` 可开启详细 stderr 日志。即使开启调试，密钥仍会被脱敏。

```bash
uv run mcp-stdio --plugin hive --config docs/examples/hive.yaml --debug
```

## Hive 工具契约

Hive 进程恰好暴露三个只读工具。

### `list_databases`

执行固定的 `SHOW DATABASES` 语句。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `databases` | string[] | 数据库名称 |
| `cached` | boolean | 结果是否来自本地缓存 |

### `list_tables`

通过 `SHOW TABLES IN <database>` 列出一个已验证数据库中的表。

| 参数 | 类型 | 必需 | 说明 |
| --- | --- | --- | --- |
| `database` | string | 是 | 必须匹配 `[A-Za-z_][A-Za-z0-9_]*` |

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `database` | string | 已验证的数据库名称 |
| `tables` | string[] | 表名称 |
| `cached` | boolean | 缓存标志 |

### `get_table_schema`

通过 `DESCRIBE` 返回普通列与分区列；还可选通过 `SHOW CREATE TABLE` 返回 DDL。

| 参数 | 类型 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `database` | string | 是 | | 必须匹配 `[A-Za-z_][A-Za-z0-9_]*` |
| `table` | string | 是 | | 必须匹配 `[A-Za-z_][A-Za-z0-9_]*` |
| `include_ddl` | boolean | 否 | `false` | 为 true 时也返回 `SHOW CREATE TABLE` 输出 |

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `database` | string | 已验证的数据库名称 |
| `table` | string | 已验证的表名称 |
| `columns` | object[] | 包含 `name`、`type`、`comment`、`ordinal` 的普通列 |
| `partition_columns` | object[] | 分区列（结构相同） |
| `ddl` | string \| null | 当 `include_ddl` 为 true 时为 DDL 文本，否则为 null |
| `cached` | boolean | 缓存标志 |

不安全的标识符会返回 `INVALID_INPUT`，且不会打开 Hive 连接。

## 进程隔离

每个 `mcp-stdio` 进程只加载一个插件。各进程不共享内存、凭据、连接、缓存或可变运行时状态。某个插件进程失败时，独立启动的其他插件进程不受影响。

## 工具错误

在到达 MCP 客户端前，失败会被映射为稳定类别：`CONFIG_ERROR`、`INVALID_INPUT`、`AUTHENTICATION_FAILED`、`PERMISSION_DENIED`、`NOT_FOUND`、`CONNECTION_FAILED`、`TIMEOUT`、`UPSTREAM_ERROR` 和 `UNEXPECTED_RESPONSE`。错误包含类别、操作、简明消息、是否可重试、安全标识符和关联 ID；绝不包含堆栈跟踪、凭据、请求头、Cookie 或未经处理的上游响应体。

## 测试

运行单元测试、契约测试与 MCP 协议循环测试：

```bash
uv run pytest -m 'not integration'
```

运行 lint 和类型检查：

```bash
uv run ruff check src tests
uv run pyright
```

### 按需启用的 HiveServer2 集成测试

集成测试需要真实的 HiveServer2，默认跳过。设置启用变量并提供连接变量后可运行：

```bash
MCP_STDIO_HIVE_INTEGRATION=1 \
MCP_STDIO_HIVE_HOST=<host> \
MCP_STDIO_HIVE_PORT=<port> \
MCP_STDIO_HIVE_DATABASE=<database> \
MCP_STDIO_HIVE_TABLE=<table> \
MCP_STDIO_HIVE_USERNAME=<user> \
MCP_STDIO_HIVE_PASSWORD=<password> \
uv run pytest -m integration
```

任何凭据值都不会出现在捕获的 stdout、stderr、报告或提交文件中。

## 架构

进程启动、请求、错误与关闭流程请参见 `docs/architecture/runtime-flow.md`；模块归属、依赖方向和插件边界请参见 `docs/architecture/modules.md`。

项目采用模块化单体与垂直插件切片，并遵循 Clean Architecture 依赖方向：MCP 工具适配器调用应用服务；服务依赖领域模型和网关接口，而不依赖 FastMCP 或 PyHive；外部适配器实现网关接口。
