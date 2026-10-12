# mcp-stdio

[English](README.md) | 简体中文

一个轻量级、基于插件的 MCP（Model Context Protocol）stdio Server。每个子进程只加载一个内置插件，并且只向 MCP Host 暴露该插件的工具。

内置插件包括：用于只读 HiveServer2 元数据查询（数据库、表、字段、分区与可选 DDL）的 **Hive schema plugin**、**Zeppelin 笔记本执行**、**DolphinScheduler 调度**，以及 **Spark event log 下载**。

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

## 本地开发环境与生产环境隔离

以下是部署指引；只有安装 release 并显式切换 MCP 注册入口后，现有服务才完成迁移。

源码检出目录和 Codex MCP 运行目录必须分离：

```text
开发检出目录：/absolute/path/to/hive_cli_mcp_stdio
生产根目录：  /absolute/path/to/hive-cli-mcp-stdio-prod
```

开发目录用于源码、worktree、`.venv`、测试和 editable 安装。Codex 的生产 MCP 注册只能指向
生产根目录中的不可变 wheel release，不能指向源码目录、开发 `.venv`、editable uv tool，也不能
通过 `PYTHONPATH` 引用源码目录。因此，`./scripts/install-skills-codex.sh --with-mcp` 属于开发
工作流，不能把它生成的 editable MCP 注册作为本地生产运行环境。

从已提交且已跟踪文件无修改的版本创建 release，并按 `uv.lock` 安装生产依赖：

```bash
set -e
PROJECT_DIR=/absolute/path/to/hive_cli_mcp_stdio
PROD_ROOT=/absolute/path/to/hive-cli-mcp-stdio-prod
RELEASE_ID="$(date +%Y%m%d%H%M%S)-$(git -C "$PROJECT_DIR" rev-parse --short=12 HEAD)"
RELEASE_DIR="$PROD_ROOT/releases/$RELEASE_ID"

test -z "$(git -C "$PROJECT_DIR" status --porcelain --untracked-files=no)"
mkdir -p "$RELEASE_DIR/dist"

uv build --project "$PROJECT_DIR" --wheel --out-dir "$RELEASE_DIR/dist"
uv export \
  --project "$PROJECT_DIR" \
  --locked \
  --no-dev \
  --no-emit-project \
  --format requirements.txt \
  --output-file "$RELEASE_DIR/runtime-requirements.txt"

uv venv --python 3.12 "$RELEASE_DIR/venv"
uv pip install \
  --python "$RELEASE_DIR/venv/bin/python" \
  --requirement "$RELEASE_DIR/runtime-requirements.txt"

WHEEL_PATH="$(find "$RELEASE_DIR/dist" -maxdepth 1 -name '*.whl' -print -quit)"
uv pip install \
  --python "$RELEASE_DIR/venv/bin/python" \
  --no-deps \
  "$WHEEL_PATH"

"$RELEASE_DIR/venv/bin/mcp-stdio" --help
ln -sfn "$RELEASE_DIR" "$PROD_ROOT/current"
```

这些命令将源码打包，并把程序和锁定版本的依赖安装到独立生产环境中：

| 命令 | 作用及关键参数 |
| --- | --- |
| `uv build --project ... --wheel --out-dir ...` | 将 `--project` 指定的项目打包成 `.whl` 文件，输出到 `--out-dir`。wheel 包含项目代码，第三方依赖需要单独安装。 |
| `uv export --project ... --locked --no-dev --no-emit-project --format requirements.txt --output-file ...` | 从 `uv.lock` 导出依赖。`--locked` 在需要更新锁文件时拒绝继续；`--no-dev` 排除开发依赖组；`--no-emit-project` 不导出项目自身。`--format` 指定 requirements 格式，`--output-file` 指定输出文件。 |
| `uv venv --python 3.12 ...` | 使用 Python 3.12，在指定路径创建隔离的虚拟环境，每个 release 拥有自己的环境。 |
| `uv pip install --python ... --requirement ...` | 安装导出的依赖。`--python` 指定目标环境的 Python 解释器，`--requirement` 指定依赖清单文件。 |
| `uv pip install --python ... --no-deps "$WHEEL_PATH"` | 将项目 wheel 安装到同一个环境。`--no-deps` 跳过依赖解析和安装，因为前一步已经安装了锁定版本的依赖。 |

`uv pip` 是 uv 提供的包安装接口，不是调用系统的 `pip`。安装 wheel 会把打包后的代码安装到
release 环境中，而不像 editable 安装那样引用开发源码；后续修改源码不会改变该已安装版本。

最后两条不是 uv 命令：`mcp-stdio --help` 检查命令行入口能否启动，但不会验证 Zeppelin
连接；`ln -sfn` 更新 `current` 符号链接，使其指向新 release。已经运行的 MCP 进程仍需
重启，才会加载新版。

以下示例使用 Codex 中显式的环境变量配置，并且不传 `--config`。项目级
`.codex/config.toml` 会保存明文凭据，因此已被 Git 忽略，并且必须使用 `chmod 600` 限制为
当前用户可读写。三个项目 MCP 注册统一使用同一个生产入口：

```toml
[mcp_servers.hive]
command = "/absolute/path/to/hive-cli-mcp-stdio-prod/current/venv/bin/mcp-stdio"
args = ["--plugin", "hive"]

[mcp_servers.hive.env]
HIVE_HOST = "<hive-host>"
HIVE_USERNAME = "<hive-user>"
HIVE_PASSWORD = "<hive-password>"

[mcp_servers.zeppelin]
command = "/absolute/path/to/hive-cli-mcp-stdio-prod/current/venv/bin/mcp-stdio"
args = ["--plugin", "zeppelin"]

[mcp_servers.zeppelin.env]
ZEPPELIN_BASE_URL = "<zeppelin-base-url>"
ZEPPELIN_USERNAME = "<zeppelin-user>"
ZEPPELIN_PASSWORD = "<zeppelin-password>"
ZEPPELIN_ALLOWED_INTERPRETERS = "[\"spark.sql\", \"spark.pyspark\"]"
ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS = "[\"<actual-setting-id>\"]"

[mcp_servers.dolphinscheduler]
command = "/absolute/path/to/hive-cli-mcp-stdio-prod/current/venv/bin/mcp-stdio"
args = ["--plugin", "dolphinscheduler"]

[mcp_servers.dolphinscheduler.env]
DOLPHINSCHEDULER_BASE_URL = "<dolphinscheduler-base-url>"
DOLPHINSCHEDULER_TOKEN = "<dolphinscheduler-token>"
```

```bash
chmod 600 "$PROJECT_DIR/.codex/config.toml"
```

确认模块从生产 release 加载，然后重启 MCP 子进程，使 Codex 读取新的 `current` 指向：

```bash
"$PROD_ROOT/current/venv/bin/python" -c \
  'import pathlib, mcp_stdio; print(pathlib.Path(mcp_stdio.__file__).resolve())'
codex mcp list --json
```

保留历史 release 以便回滚。把 `current` 重新指向上一版，再重启 MCP 子进程即可，不需要源码
检出目录或重新安装依赖：

```bash
ln -sfn "$PROD_ROOT/releases/<previous-release>" "$PROD_ROOT/current"
```

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

安装器管理一个带标记的配置块，其中包含 `mcp_servers.hive`、`mcp_servers.zeppelin` 和 `mcp_servers.dolphinscheduler`。它使用 Codex 的 `env_vars` 将变量名从启动 Codex 的环境传入；不会将凭据值、Python 路径、虚拟环境路径或 `PYTHONPATH` 写入 TOML 文件。启动 Codex 前请导出必需变量：

Codex 也支持在 `[mcp_servers.<name>.env]` 中直接配置字面值，但这些值会以明文保存在 `.codex/config.toml`。安装器刻意不为凭据生成这种形式。

仅为说明 TOML 语法，下面是 Hive 的字面环境变量示例。不要将真实值写入或提交该文件；真实凭据仍推荐使用上方安装器生成的 `env_vars` 转发方式：

```toml
[mcp_servers.hive.env]
HIVE_HOST = "<hive-host>"
HIVE_USERNAME = "<your-ldap-user>"
HIVE_PASSWORD = "<your-ldap-password>"
```

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
export DOLPHINSCHEDULER_BASE_URL=http://<ds-host>:12345/dolphinscheduler
# 可选的 DolphinScheduler API 令牌：
export DOLPHINSCHEDULER_TOKEN=<dolphinscheduler-api-token>
```

缺少 `HIVE_HOST`、`HIVE_USERNAME`、`HIVE_PASSWORD`、`ZEPPELIN_BASE_URL` 或 `DOLPHINSCHEDULER_BASE_URL` 时，安装器只会提示缺失的变量名，安装仍会成功，以便稍后再配置启动环境。使用 `--force --with-mcp` 重复执行会刷新受管理的 Skill，并替换唯一一个受管理 TOML 块，同时保留其他 Codex 设置。未标记的 Hive、Zeppelin 或 DolphinScheduler 配置表被视为用户自管内容，绝不会被覆盖。

### 向 Codex 添加 DolphinScheduler MCP Server

Codex 安装器在使用 `--with-mcp` 时会自动创建该条目：

```toml
[mcp_servers.dolphinscheduler]
command = "mcp-stdio"
args = ["--plugin", "dolphinscheduler"]
env_vars = [
  "DOLPHINSCHEDULER_BASE_URL",
  "DOLPHINSCHEDULER_TOKEN",
]
```

`DOLPHINSCHEDULER_BASE_URL` 为必需项，必须是没有凭据的绝对 `http` 或 `https` URL；部署使用上下文路径时也必须带上它，例如 `http://ds-host:12345/dolphinscheduler`。`DOLPHINSCHEDULER_TOKEN` 为可选项，仅按变量名转发，绝不能将其值写入 TOML 文件。

### 向 Trae 添加三个 MCP Server

Trae 安装器同样支持 `--with-mcp`。它会安装可编辑工具，并在 `<项目>/.trae/mcp.json` 创建 **Hive、Zeppelin 与 DolphinScheduler** 三个服务条目：

```bash
./scripts/install-skills-trae.sh --project-root /path/to/project --with-mcp
```

该 JSON 配置只包含 `mcp-stdio` 命令与插件参数，不包含环境变量值。请在启动 Trae 前导出必需的 `HIVE_*`、`ZEPPELIN_*` 和 `DOLPHINSCHEDULER_*` 变量。为保护用户配置，安装器会拒绝覆盖已经存在的 `.trae/mcp.json`。

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

## Zeppelin 工具契约

Zeppelin 进程精确暴露九个工具。所有 ID 都是大小写敏感的不透明字符串；调用方必须原样保留，
不能根据解释器名称、setting 名称或 paragraph 内容猜测 setting ID。

| 工具 | 参数 | 精确返回字段 |
| --- | --- | --- |
| `list_notebooks` | 无 | `nodes: NotebookTreeNode[]` |
| `create_notebook` | `name: string` | `notebook_id`、`name` |
| `add_paragraph` | `notebook_id: string`、`title: string`、`body: string` | `notebook_id`、`paragraph_id`、`title`、`interpreter` |
| `run_paragraph` | `notebook_id: string`、`paragraph_id: string` | `notebook_id`、`paragraph_id`、`status` |
| `get_paragraph_status` | `notebook_id: string`、`paragraph_id: string` | `notebook_id`、`paragraph_id`、`status` |
| `get_paragraph_result` | `notebook_id: string`、`paragraph_id: string` | `notebook_id`、`paragraph_id`、`status`、`outputs`、`truncated`、`error` |
| `get_interpreter_bindings` | `notebook_id: string` | `notebook_id`、`bindings` |
| `restart_interpreter` | `setting_id: string`，可选 `notebook_id: string \| null = null` | `setting_id`、`name`、`group`、`status` |
| `cancel_paragraph` | `notebook_id: string`、`paragraph_id: string` | `notebook_id`、`paragraph_id` |

嵌套返回结构：

- `NotebookTreeNode` 包含 `notebook_id: string | null`、`name: string`、`path: string` 和递归的
  `children: NotebookTreeNode[]`。
- paragraph 的 `status` 是 `PENDING`、`RUNNING`、`FINISHED`、`ERROR`、`CANCELLED` 或
  `UNKNOWN` 之一。
- 每个 paragraph 输出包含 `kind` 和 `text`；`kind` 是 `TEXT`、`TABLE`、`HTML`、`ANGULAR`
  或 `IMG` 之一。`error` 为 null 或 `{ "message": string }`；`truncated=true` 表示达到已配置的
  输出上限。
- 每个 interpreter binding 精确包含 `setting_id`、`name`、`interpreters: string[]`、
  `selected: boolean` 和 `restart_allowed: boolean`。`restart_allowed` 只表示本地 allowlist
  判断，不代表上游授权或 interpreter 健康状态。

### Interpreter 发现与重启

按以下三个显式步骤执行 notebook 范围重启：

1. 使用可读的 notebook ID 调用 `get_interpreter_bindings`。
2. 选择 `selected` 和 `restart_allowed` 都为 true 的 binding，并使用其精确 `setting_id`。
3. 使用该 `setting_id` 和同一个 `notebook_id` 调用 `restart_interpreter`。

发现结果示例：

```json
{
  "notebook_id": "note-1",
  "bindings": [
    {
      "setting_id": "spark_prod",
      "name": "Spark Production",
      "interpreters": ["spark", "sql", "pyspark"],
      "selected": true,
      "restart_allowed": true
    }
  ]
}
```

notebook 范围重启的调用与结果示例：

```json
{
  "arguments": {
    "setting_id": "spark_prod",
    "notebook_id": "note-1"
  },
  "result": {
    "setting_id": "spark_prod",
    "name": "Spark Production",
    "group": "spark",
    "status": "READY"
  }
}
```

`ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS` 是由精确 setting ID 组成的 JSON 数组，默认拒绝
所有重启。服务在登录、HTTP、ticket 或 WebSocket 请求之前检查 allowlist。发现 binding 不要求
具备重启权限；本地禁止重启的 binding 仍会返回，并带有 `restart_allowed=false`。

省略 `notebook_id` 或显式传 null 会保留旧的 setting 范围重启。notebook 模式失败时不会丢弃
notebook 上下文或回退到 setting 范围重启；两种模式都不会自动重试重启或重新执行 paragraph。
Zeppelin 可能在多个 notebook 之间共享同一个 interpreter 进程，因此 notebook 上下文不能保证
影响范围完全隔离。

MCP Host 连接仍是本地 stdio 上的 JSON-RPC。notebook 和 paragraph 操作通过出站 Zeppelin HTTP
完成；binding 发现还会在同一个用户 session 中使用经过认证且有边界的出站 WebSocket 查询。
进程不会开放 MCP HTTP、SSE 或 WebSocket 监听端口。

### Zeppelin 配置示例

等价的 [YAML](docs/examples/zeppelin.yaml) 与 [JSON](docs/examples/zeppelin.json) 示例中，`secrets` 只包含环境变量名称，不包含凭据。由启动环境提供成对的用户名和密码后运行：

```bash
uv run --locked mcp-stdio --plugin zeppelin --config docs/examples/zeppelin.yaml
```

仅环境变量启动的等价配置（凭据仍由外部提供）：

```bash
export ZEPPELIN_BASE_URL='https://zeppelin.example.invalid/zeppelin/api'
export ZEPPELIN_REQUEST_TIMEOUT_SECONDS='30'
export ZEPPELIN_ALLOWED_INTERPRETERS='["spark_prod.sql"]'
export ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS='["spark_prod"]'
uv run --locked mcp-stdio --plugin zeppelin
```

执行前缀与精确重启设置 ID 使用相互独立的白名单，默认均拒绝。所有集合覆盖（`ALLOWED_INTERPRETERS`、`RESTARTABLE_INTERPRETER_SETTINGS`、`SQL_WRITE_ALLOWED_DATABASES`、`SQL_FORBIDDEN_KEYWORDS`、`SH_ALLOWED_COMMANDS`）在 `ZEPPELIN_` 前缀下使用 JSON 数组。插件前缀覆盖优先于 `MCP_STDIO__SETTINGS__<FIELD>`，再优先于文件和默认值。启动与工具列表读取均不访问网络。发现功能要求 REST base 以 `/api` 结尾：只将该末尾路径映射为 `/ws`（HTTP→WS，HTTPS→WSS），保留源站与反向代理前缀；模糊挂载在联网前失败。

不要把解释器重启当作通用重试；结果仅确认上游报告状态，不保证 Spark 健康或恢复成功。

## DolphinScheduler 配置与工具

DolphinScheduler 插件支持带版本号的 YAML/JSON 配置文件，也支持仅用环境变量启动。完整的非敏感示例见 [`docs/examples/dolphinscheduler.yaml`](docs/examples/dolphinscheduler.yaml) 与 [`docs/examples/dolphinscheduler.json`](docs/examples/dolphinscheduler.json)。

仅用环境变量启动时，配置基础 URL，并按需配置令牌：

```bash
export DOLPHINSCHEDULER_BASE_URL=http://<ds-host>:12345/dolphinscheduler
export DOLPHINSCHEDULER_TOKEN=<dolphinscheduler-api-token> # 可选
uv run mcp-stdio --plugin dolphinscheduler
```

使用配置文件时，`secrets.token` 写入的是环境变量名称 `DOLPHINSCHEDULER_TOKEN`，不是令牌值：

```bash
export DOLPHINSCHEDULER_TOKEN=<dolphinscheduler-api-token>
uv run mcp-stdio --plugin dolphinscheduler \
  --config docs/examples/dolphinscheduler.yaml
```

该进程暴露 `get_server_status`、`list_objects`、`get_object`、`search_objects`、`start_workflow`、`get_task_log` 与 `extract_log_links`。`start_workflow` 在 `dry_run=0` 时会启动工作流；使用 `dry_run=1` 可只做校验、不实际执行，实际启动前必须获得用户批准。其余工具均为只读；结果和任务日志均有边界，服务不提供对象创建、更新、删除、暂停、恢复或停止操作。

## Spark event log 下载

Spark 只暴露 `fetch_spark_event_log(application_id, attempt_id=None, refresh=False)`。
它下载配置的 Spark History Server ZIP，校验身份、CRC 和 JSONL，脱敏后保存 JSONL 与一份
清单，后续诊断工具直接读取本地路径。首版格式以已验证的 Spark 2.4.7 单文件 JSONL 为依据。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| application_id | 必填 | YARN ID，例如 `application_1700000000000_0042` |
| attempt_id | null | 指定 attempt；省略时下载上游提供的全部 attempts |
| refresh | false | 默认复用；true 重新下载到新目录 |

未知参数和非法原始类型会被拒绝，错误不回显参数值。调用者不能指定 URL、输出目录、
凭据或 TLS 设置。

| 设置 | 默认值 | 含义 |
| --- | --- | --- |
| history_server_url | 必填 | HTTPS 根地址，保留网关路径，不带 `/api/v1`、凭据或 query |
| cache_dir | 必填 | 绝对专用本地目录；支持 POSIX macOS/Linux |
| verify_tls | true | 显式设为 false 时跳过证书和主机名校验 |
| ca_bundle_path | null | 私有证书所需的可信可读 PEM CA |
| request_timeout_seconds | 300 | 整个调用含查缓存、排队和处理的时间预算，最多 900 秒 |
| max_bytes | 268435456 | 分别限制 ZIP、展开源文件总量和输出 JSONL 总量 |

使用 [spark.yaml](docs/examples/spark.yaml) 或 [spark.json](docs/examples/spark.json)。
通过安全环境注入已有登录 Cookie 到 `SPARK_GATEWAY_COOKIE`，配置文件只写变量名。
匿名部署可以省略 secret 引用。默认校验证书；如明确需要跳过，可设置
`export SPARK_VERIFY_TLS=false`（或 YAML `verify_tls: false`），然后重启 MCP 进程。
此时 HTTPS 仍加密，但不验证服务器身份；已配置的 CA 仍须通过本地校验，连接时不使用。
工具不会自动登录。

```sh
uv run --locked mcp-stdio --plugin spark --config docs/examples/spark.yaml
```

只用环境变量启动：

```sh
export SPARK_HISTORY_SERVER_URL='https://history.example.invalid:8443/gateway/analytics/sparkhistory'
export SPARK_CACHE_DIR='/var/tmp/mcp-spark-l3'
export SPARK_CA_BUNDLE_PATH='/etc/mcp/spark-ca.pem'
# SPARK_GATEWAY_COOKIE 已安全注入；可选覆盖：
# SPARK_REQUEST_TIMEOUT_SECONDS、SPARK_MAX_BYTES。
uv run --locked mcp-stdio --plugin spark
```

MCP host 使用前文的已安装 release 入口，通过 host 的安全环境向子进程传入 Cookie：

```json
{
  "mcpServers": {
    "spark": {
      "command": "/absolute/path/to/hive-cli-mcp-stdio-prod/current/venv/bin/mcp-stdio",
      "args": ["--plugin", "spark", "--config", "/absolute/path/to/spark.yaml"]
    }
  }
}
```

本地 MCP 是 stdio，HTTPS 是向 History Server 发起的上游连接。host 的工具超时应大于
配置的整次调用预算。

结果字段为 `application_id`、`requested_attempt_id`、`cache_hit`、`downloaded_at`、
`manifest_path`、`files`。每个文件记录 `attempt_id`、`local_path`、`spark_version`、
`size_bytes`、`sha256`、`source_sha256`、`event_count`、`application_end_seen`。
两个摘要分别对应脱敏输出和原始成员字节；ApplicationEnd 不代表 YARN 最终状态。

JSONL 在下载后的校验/脱敏阶段生成于私有暂存目录。全部成员通过后移除 ZIP，
将整个目录 rename 发布到：

```text
<cache_dir>/<application_id>/all|attempt-<id>/<random-id>/
  eventlog-0001.jsonl
  manifest.json
```

清单包含结果中除 `cache_hit` 外的字段，以及 `format_version=1` 和规范化源地址。
不保留原始 ZIP、未脱敏 JSON、索引或摘要旁车文件。事件行序和数值指标保留；
凭据字段及白名单以外的环境属性脱敏。压缩/滚动 event log 和损坏尾行直接报错。

只有同来源、同 attempt 选择且文件摘要正确才命中，保留原下载时间且不联网；
缓存不保证上游最新性。refresh 产生新目录，旧证据保留。目录跨会话存在，直到你手工清理，
首版没有 TTL、去重或 GC。同根目录只能由一个活动进程使用。失败、取消和正常关闭清理
本次暂存目录；强杀残留的 `.part-*` 不参与复用，可手工清理。

真实下载测试需要显式设置 `MCP_STDIO_SPARK_INTEGRATION=1`、
`MCP_STDIO_SPARK_APPLICATION_ID`、可选 `MCP_STDIO_SPARK_ATTEMPT_ID` 和
SPARK URL/cache/Cookie/CA 部署环境，再运行：

```sh
uv run --locked pytest -m integration tests/integration/test_spark_server.py
```

## 进程隔离

每个 `mcp-stdio` 进程只加载一个插件。各进程不共享内存、凭据、连接、活动缓存或可变运行时状态。Spark 的持久证据允许前一目录所有者退出后被后续进程复用。某个插件进程失败时，独立启动的其他插件进程不受影响。

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
