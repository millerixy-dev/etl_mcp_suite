# macOS 快速上手

面向新用户,在 macOS 上从零安装并跑通 `mcp-stdio` 的最短路径。版本一交付 `hive`
(只读元数据)与 `zeppelin`(可执行,带安全门控)两个插件;`dolphinscheduler` 为占位,
暂不可用。每个插件各自一个独立子进程,互不共享凭据、连接与缓存。

## 1. 安装前置依赖

项目唯一使用 [uv](https://docs.astral.sh/uv/) 管理依赖与虚拟环境,无需手动安装 Python:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

macOS 自带的 Python 无需配置,uv 会按 `requires-python>=3.10` 自动管理解释器。

## 2. 克隆并同步依赖

```bash
git clone https://github.com/millerixy-dev/etl_mcp_suite.git hive_cli_mcp_stdio
cd hive_cli_mcp_stdio
uv sync --frozen
```

`uv sync --frozen` 严格按提交的 `uv.lock` 还原可复现环境,并装好 `mcp-stdio` 控制台入口。

冒烟测试:

```bash
uv run mcp-stdio --help
```

> 若 `uv run` 报缓存权限错误,按 README 的回退方式直接跑 venv 解释器:
> `PYTHONPATH=src .venv/bin/python -m mcp_stdio --help`。

## 3. 通过环境变量配置(推荐)

凭据只走环境变量,绝不写入配置文件、工具参数或日志。可省略 `--config`,完全用
`<PREFIX>_<FIELD>` 启动;环境变量优先级最高,也可叠加 `--config` 只放非敏感项。

列表类字段用 **JSON 数组字符串** 表示(如 `'["spark","sh"]'`)。

### Hive 插件(前缀 `HIVE`,只读元数据)

```bash
export HIVE_HOST=<hive-host>          # 必填
export HIVE_PORT=10000                 # 可选,默认 10000
export HIVE_DATABASE=default           # 可选,默认 default
export HIVE_CACHE_TTL_SECONDS=30       # 可选,默认 30
export HIVE_USERNAME=<ldap-user>       # 必填
export HIVE_PASSWORD=<ldap-password>   # 必填
```

直连 stdio 验证(会返回握手 `serverInfo.name=mcp-stdio`):

```bash
uv run mcp-stdio --plugin hive --debug
```

### Zeppelin 插件(前缀 `ZEPPELIN`,可执行 + 安全门控)

```bash
export ZEPPELIN_BASE_URL=http://<zeppelin-host>:8089   # 必填,http/https,不含凭据
export ZEPPELIN_USERNAME=<user>    # 可选,与 PASSWORD 成对出现
export ZEPPELIN_PASSWORD=<pass>    # 可选
# 安全相关(均有合理默认,按需覆盖):
export ZEPPELIN_ALLOWED_INTERPRETERS='["spark","sh"]'      # 解释器默认拒绝,需显式放行
export ZEPPELIN_SQL_FORBIDDEN_KEYWORDS='["DROP","TRUNCATE"]'  # 黑名单,任何库都拒
export ZEPPELIN_SQL_WRITE_ALLOWED_DATABASES='["tmp_dc_ep"]'   # DML/CREATE/ALTER 仅此库
export ZEPPELIN_SH_ALLOWED_COMMANDS='["ls","cat"]'            # sh 命令默认拒绝
export ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS='["spark"]'  # 可重启的解释器设置
```

直连 stdio 验证:

```bash
uv run mcp-stdio --plugin zeppelin --debug
```

## 4. 接入 MCP 客户端

把命令指向 venv 里的入口,把环境变量放进 `env`。Hive 示例(放入客户端的 mcp 配置,
如 `~/.config/<client>/mcp.json`):

```json
{
  "mcpServers": {
    "hive": {
      "command": "/Users/<you>/hive_cli_mcp_stdio/.venv/bin/python",
      "args": ["-m", "mcp_stdio", "--plugin", "hive"],
      "env": {
        "PYTHONPATH": "/Users/<you>/hive_cli_mcp_stdio/src",
        "HIVE_HOST": "<hive-host>",
        "HIVE_PORT": "10000",
        "HIVE_DATABASE": "default",
        "HIVE_USERNAME": "<ldap-user>",
        "HIVE_PASSWORD": "<ldap-password>"
      }
    }
  }
}
```

Zeppelin 同理,把 `--plugin` 换成 `zeppelin`、`env` 换成 `ZEPPELIN_*`(列表字段用 JSON
数组字符串)。每个插件各自一个 `mcpServers` 条目、一个独立子进程。

## 5. 常见坑

- `CONFIG_ERROR` 报某个变量名缺失 -> 对应必填环境变量没 export,按报错补齐即可,
  错误信息不会泄露任何凭据值。
- `uv run` 缓存权限错误 -> 回退到 `PYTHONPATH=src .venv/bin/python -m mcp_stdio`。
- Zeppelin 解释器调用被拒 -> `ZEPPELIN_ALLOWED_INTERPRETERS` 未放行该解释器;
  门控拒绝会明确说明命中的是黑/白名单。
- 写库被拒 -> 目标库不在 `ZEPPELIN_SQL_WRITE_ALLOWED_DATABASES`,或命中
  `ZEPPELIN_SQL_FORBIDDEN_KEYWORDS` 黑名单。

## 6. 下一步

- 配置文件示例见 `docs/examples/hive.yaml` 与 `docs/examples/hive.json`(非敏感项)。
- 架构与模块边界见 `docs/architecture/runtime-flow.md`、`docs/architecture/modules.md`。
- 完整工具契约与安全说明见 `README.md`。
