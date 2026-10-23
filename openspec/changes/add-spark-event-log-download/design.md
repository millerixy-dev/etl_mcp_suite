## Context

动机见 proposal.md。现有运行器采用固定插件、严格配置、环境秘密引用与共享 ToolError。实际样例 ZIP 约 88 KB，展开约 1.2 MB、584 条事件，Spark 版本为 `2.4.7.7.1.7.1000-141`；用户的日志通常小于 100 MB。未登录客户端会收到 HTTP 200 HTML 登录页。自动工具消费环境注入的 Cookie 或 Basic 凭据；2026-10-13 已通过实际 MCP 调用验证 Knox 登录、下载与缓存复用，详见 verification.md。

## Goals / Non-Goals

**Goals:** 交付一个同步请求语义的下载工具，生成后续诊断工具可读取的本地 JSONL 和来源清单，支持跨会话直接复用。

**Non-Goals:** 见 proposal.md。首版只支持 POSIX 本地主机和已验证的单文件 JSONL 格式；不建设通用缓存或日志修复框架。

## Decisions

### 1. 沿用插件边界，复用现有依赖

新增 `src/mcp_stdio/plugins/spark/`。配置、领域模型、gateway、service、tools、plugin 沿用现有垂直切片；外部 HTTP adapter 与一个本地文件处理模块分别负责网络和 ZIP/JSONL/清单。仅在职责或体量需要时拆分文件，不预建 snapshot/object/repository/GC 层。

service 校验输入并通过 gateway 决定复用或下载，不依赖 HTTP、文件适配器或 FastMCP；tools 只转换契约。仅 registry 引入具体插件。复用直接依赖 httpx，ZIP、JSON、散列、目录和锁使用 Python 3.10 标准库。

### 2. 上游与处理接口

| 资源/实体 | 契约 | 一手来源 |
| --- | --- | --- |
| application 的全部日志 | GET `<base>/api/v1/applications/{application_id}/logs`，返回 ZIP | [Spark 2.4.7 REST API](https://archive.apache.org/dist/spark/docs/2.4.7/monitoring.html#rest-api) |
| 指定 attempt 的日志 | GET `<base>/api/v1/applications/{application_id}/{attempt_id}/logs`，返回 ZIP | 同上；[ApiRootResource](https://github.com/apache/spark/blob/v2.4.7/core/src/main/scala/org/apache/spark/status/api/v1/ApiRootResource.scala) |
| 单文件 JSONL、LogStart、文件名 | application ID 与可选 attempt 后缀，可带 `.inprogress` | [EventLoggingListener](https://github.com/apache/spark/blob/v2.4.7/core/src/main/scala/org/apache/spark/scheduler/EventLoggingListener.scala) |
| ApplicationStart/End | 身份来自 App ID / App Attempt ID；ApplicationEnd 不代表 YARN 最终状态 | [JsonProtocol](https://github.com/apache/spark/blob/v2.4.7/core/src/main/scala/org/apache/spark/util/JsonProtocol.scala) |
| ZIP 与 HTTP | 公开 zipfile API 的成员读取/CRC；HTTPX streaming 与 TLS | [Python zipfile](https://docs.python.org/3.10/library/zipfile.html)、[HTTPX API](https://www.python-httpx.org/api/)、[HTTPX TLS](https://www.python-httpx.org/advanced/ssl/) |

支持用户确认的 Knox SSO Basic 登录协议（实际 login.html 的 knoxauth.js，2026-10-13 已检查）；[Knox 官方 SSO 文档](https://apache.github.io/knox/config_knox_sso/)描述 Basic 认证后签发 SSO Cookie。不查询 application listing 或猜测 latest attempt。

### 3. 配置与环境秘密

| Field | Type | Default | Range | Required |
| --- | --- | --- | --- | --- |
| version | int | — | 固定 1 | 文件模式是 |
| plugin | string | — | 固定 spark | 文件模式是 |
| settings.history_server_url | string | — | HTTPS 绝对 URL，最多 2048 字符，无 userinfo/query/fragment；保留网关 mount | 是 |
| settings.cache_dir | string | — | 最多 4096 字符的绝对专用本地目录，无控制字符，拒绝 symlink 根 | 是 |
| settings.verify_tls | bool | true | false 显式跳过证书及主机名校验，仅部署配置 | 否 |
| settings.knox_sso_url | string or null | null | 同 History Server origin 的 HTTPS SSO endpoint，无 query/fragment/userinfo，最多 2048 字符 | Basic 登录时是 |
| settings.ca_bundle_path | string or null | null | 绝对可读可信 PEM CA 文件 | 否 |
| settings.request_timeout_seconds | float | 300.0 | 大于 0 且至多 900 | 否 |
| settings.max_bytes | int | 268435456 | 1–1073741824；分别限制 ZIP、展开源总量、输出 JSONL 总量 | 否 |
| secrets.username | env reference / SecretStr or null | null | 与 password 成对，非空，无冒号/控制字符 | Basic 登录时是 |
| secrets.password | env reference / SecretStr or null | null | 与 username 成对，非空，无控制字符 | Basic 登录时是 |
| secrets.gateway_cookie | env reference / SecretStr or null | null | 文件只填环境变量名；解析出的 Cookie 非空且不含 CR/LF/NUL | 否 |

这里包含七项 settings 和三项可选 secret，version/plugin 沿用运行器。无 instance_id、独立连接超时、TTL、总缓存容量或可调 ZIP 元数据参数。沿用未知字段拒绝和文件/env 验证；配置检查不访问网络。未配置认证时允许匿名部署；网关认证可注入 Cookie，或使用下面的 Basic 配置。

文件示例：

```yaml
version: 1
plugin: spark
settings:
  # 保留网关路径，不包含 /api/v1 或登录参数。
  history_server_url: https://history.example.invalid:8443/gateway/analytics/sparkhistory
  # 每个活动实例使用自己的专用目录。
  cache_dir: /var/tmp/mcp-spark-l3
  # 私有 CA 使用可信 PEM；公共受信证书可省略。
  ca_bundle_path: /etc/mcp/spark-ca.pem
  verify_tls: true  # 仅明确需要跳过证书校验时设为 false
  # 超时和大小上限可省略，使用表中的默认值。
secrets:
  gateway_cookie: SPARK_GATEWAY_COOKIE
```

```sh
# Cookie 已通过安全环境注入，不将值粘贴进文件或命令。
uv run --locked mcp-stdio --plugin spark --config docs/examples/spark.yaml
```

实现时提供等价 JSON 配置和沿用该命令的 MCP host 启动示例。环境变量映射：

| 环境变量 | 字段 |
| --- | --- |
| SPARK_HISTORY_SERVER_URL | settings.history_server_url |
| SPARK_CACHE_DIR | settings.cache_dir |
| SPARK_VERIFY_TLS | settings.verify_tls |
| SPARK_CA_BUNDLE_PATH | settings.ca_bundle_path |
| SPARK_REQUEST_TIMEOUT_SECONDS | settings.request_timeout_seconds |
| SPARK_MAX_BYTES | settings.max_bytes |
| SPARK_KNOX_SSO_URL | settings.knox_sso_url |
| SPARK_USERNAME | secrets.username 的秘密值 |
| SPARK_PASSWORD | secrets.password 的秘密值 |
| SPARK_GATEWAY_COOKIE | secrets.gateway_cookie 的秘密值 |

```sh
export SPARK_HISTORY_SERVER_URL='https://history.example.invalid:8443/gateway/analytics/sparkhistory'
export SPARK_CACHE_DIR='/var/tmp/mcp-spark-l3'
export SPARK_CA_BUNDLE_PATH='/etc/mcp/spark-ca.pem'
# 如明确需要跳过证书校验：export SPARK_VERIFY_TLS=false
# SPARK_GATEWAY_COOKIE 预先安全注入，其余使用默认值。
uv run --locked mcp-stdio --plugin spark
```

沿用 core 的优先级：文件值 → 通用 MCP_STDIO 覆盖 → SPARK 前缀覆盖；secret 始终保持私有。TLS 默认验证，私有 CA 用显式 SSLContext；固定 trust_env=False、follow_redirects=False，不消费环境代理或隐式 CA override。部署可通过 verify_tls=false / SPARK_VERIFY_TLS=false 显式关闭证书与主机名校验；此时 HTTPX verify=False，ca_bundle_path 不参与连接（如配置仍须通过本地 PEM 验证）。HTTPS、固定 origin、无跳转保持不变。无调用者 headers、URL、TLS 或 output-path 控制。

### 3a. Knox Basic 登录

匿名、显式 gateway_cookie、Basic 三种模式由配置确定：username/password 必须成对；不能与 gateway_cookie 同时设置；knox_sso_url 与 Basic 凭据同时存在，否则本地 CONFIG_ERROR。SSO URL 必须与 history_server_url 同 origin（scheme/host/effective port），沿用严格 URL 校验。无新依赖，无认证 MCP 工具，无磁盘 Cookie 文件，不自动读取个人凭据路径。

每次实际下载前向 knox_sso_url POST 空 body，query originalUrl 为配置的 History Server 根地址（末尾 /），通过 HTTPX BasicAuth 发送 Authorization。登录和下载共享原总 deadline、TLS 配置，trust_env=False、follow_redirects=False。仅登录请求包含 Basic header；下载 GET 使用 Cookie jar 的域/路径匹配。缓存命中不登录。

登录接受 200/204/302/303/307/308 且必须得到适用于下载 URL 的 Cookie，绝不跟随 Location。401/缺 Cookie/其他 3xx 为 AUTHENTICATION_FAILED；403 为 PERMISSION_DENIED；429/5xx 为可重试 UPSTREAM_ERROR；其他状态为不可重试 UPSTREAM_ERROR。登录正文不读取、不记录。登录成功只表示可继续下载，最终仍需有效 ZIP/身份校验，不凭状态码判定端到端成功。每次下载只登录一次，不做重试、自动续期或失败密码重试。

登录和下载的响应 Cookie 在 receive finally 清空；本次取得的 Cookie 值仅作为临时脱敏上下文传给 ZIP/JSONL/manifest 处理，处理结束丢弃。用户名、密码及 Basic 编码值加入已有脱敏集合，不得进入结果/普通日志/L3 文件。客户端关闭时清空 Cookie。

文件模式（secrets 是环境变量名）：
```yaml
version: 1
plugin: spark
settings:
  history_server_url: https://history.example.invalid:8443/gateway/analytics/sparkhistory
  cache_dir: /var/tmp/mcp-spark-l3
  knox_sso_url: https://history.example.invalid:8443/gateway/knoxsso/api/v1/websso
secrets:
  username: SPARK_USERNAME
  password: SPARK_PASSWORD
```
启动：`uv run --locked mcp-stdio --plugin spark --config /absolute/path/to/spark.yaml`。
环境模式：
```sh
export SPARK_HISTORY_SERVER_URL='https://history.example.invalid:8443/gateway/analytics/sparkhistory'
export SPARK_KNOX_SSO_URL='https://history.example.invalid:8443/gateway/knoxsso/api/v1/websso'
export SPARK_CACHE_DIR='/var/tmp/mcp-spark-l3'
# SPARK_USERNAME/SPARK_PASSWORD 从秘密管理环境注入；不能同时设置 SPARK_GATEWAY_COOKIE。
uv run --locked mcp-stdio --plugin spark
```

### 4. 一个工具，直接返回文件位置

`fetch_spark_event_log` 输入：

| 参数 | 类型 | 默认 | 语义/校验 |
| --- | --- | --- | --- |
| application_id | string | 必填 | ASCII `application_[0-9]+_[0-9]+`，最多 128 字符 |
| attempt_id | string or null | null | 非空时 `[A-Za-z0-9_-]{1,128}`；null 下载上游提供的全部 attempts，不自动选 latest |
| refresh | bool | false | false 先复用；true 总是下载 |

成功结果名为 `SparkEventLogFetchResult`，每项文件名为 `SparkEventLogFile`。字段全部固定，示例值为合成数据：

```json
{
  "application_id": "application_1700000000000_0042",
  "requested_attempt_id": "1",
  "cache_hit": false,
  "downloaded_at": "2026-10-12T08:00:00Z",
  "manifest_path": "/var/tmp/mcp-spark-l3/application_1700000000000_0042/attempt-1/00000000000040008000000000000001/manifest.json",
  "files": [
    {
      "attempt_id": "1",
      "local_path": "/var/tmp/mcp-spark-l3/application_1700000000000_0042/attempt-1/00000000000040008000000000000001/eventlog-0001.jsonl",
      "spark_version": "2.4.7.7.1.7.1000-141",
      "size_bytes": 1100000,
      "sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "source_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "event_count": 584,
      "application_end_seen": true
    }
  ]
}
```

下载时间为 UTC RFC3339；命中保留原下载时间，仅 cache_hit 改为 true。files 按 attempt（null 在前、其余字典序）排序，客户端模式 attempt 可为 null。sha256 标识保存的脱敏字节，source_sha256 标识原始成员字节，均为 64 位小写 hex；不把摘要作为目录或抽象 log_ref。size_bytes 为输出大小，event_count 为记录数，spark_version 原样记录至多 128 个 `[A-Za-z0-9._-]` 字符。成功意味着所选文件全部校验并保存；不再返回 READY、snapshot_id、expires_at、selection、source_freshness 或 parse_coverage。缺 ApplicationEnd 仅返回 false，不推断成功、失败或仍运行。

service 的 `SparkEventLogGateway` 只有以下接口；HTTP/文件处理函数属于适配器内部实现，不另建可替换存储协议：

| 方法 | 输入参数 | 结果 |
| --- | --- | --- |
| lookup | application_id、attempt_id，同工具校验；deadline 为内部 monotonic 截止点 | SparkEventLogFetchResult（cache_hit=true）或 null |
| download | application_id、attempt_id，同工具校验；deadline 同上 | SparkEventLogFetchResult（cache_hit=false） |
| close | 无 | null，幂等关闭 HTTP client 并释放目录锁 |

lookup/download 的输入 JSON 例为 `{"application_id":"application_1700000000000_0042","attempt_id":"1"}`；结果复用上面的完整 JSON，lookup miss 与 close 返回 `null`。失败使用共享 ToolError，不传递 HTTP 对象、Cookie 或原始事件。

### 5. 下载与标准库校验

一次 GET 流式写入本次私有 .part。按实际响应字节计数，不仅信 Content-Length；拒绝非 identity HTTP Content-Encoding。总 deadline 覆盖排队、缓存检查、HTTP、逐成员/逐行处理和发布；每个受限处理块设取消检查点，HTTP 各阶段超时不得超过剩余预算。配置的 Cookie 只发送给固定 origin，不跟随 redirect；显式 Cookie 模式不刷新或复用响应 Cookie，Basic 模式按下述一次调用生命周期处理。建立 HTTP client 前启用现有 wire-log suppression。

使用 ZipFile 的公开 API，不写 EOCD/central-directory 解析器，不调用 extractall。首版固定最多 16 个成员；按 remove-spark-event-line-limit 的已批准变更，取消独立单行上限，读取按剩余展开总量预算加 1 字节探测溢出，输出继续检查累计总量；ZIP 元数据内存由已接收 ZIP 上限间接约束，承认不提供独立 metadata 内存上限。逐成员实际展开量计数，读到 EOF 触发 CRC 检查。只接受 stored/deflate ZIP 普通文件，拒绝加密、symlink、目录、绝对/嵌套/穿越路径与重复成员/attempt。输出使用工具生成的文件名，不使用成员名作为落盘路径。

成员须为 UTF-8 JSONL，每条是带非空有界 Event 的 object。必须包含一致的 LogStart 与 ApplicationStart，App ID、可选 attempt 和源 basename 匹配请求及 Spark 单文件命名；允许 .inprogress 后缀。不接受事件文件自身 codec 或 rolling layout。记录 Spark Version，不按 patch 白名单拒绝；首版以已验证的 2.4.7 格式为兼容依据，未知自定义事件只做结构校验、不解释语义。

任何非法 JSON/UTF-8 或截断尾行都失败，不尝试修复。合法完整 JSON 末行无需换行；缺 ApplicationEnd 允许保存。全部 attempts 各自保存、任一成员失败则整次不发布。

### 6. 最小凭据脱敏

由于仓库禁止将凭据写入持久快照，输出为脱敏 JSONL，不保留原始 ZIP。按记录流式处理，无策略版本、插件式规则或迁移机制：

- 递归将不区分大小写的 password/passwd/secret/token/cookie/authorization/credential/access-key/private-key 及常见点/下划线命名变体对应值改为 [REDACTED]；字符串中的同类赋值和 URL 凭据也脱敏。配置 Cookie 全值和各 Cookie 值在所有字符串中替换。
- EnvironmentUpdate 的 Spark Properties 仅保留 spark.app.id、spark.master、spark.submit.deployMode、spark.executor.memory、spark.executor.cores、spark.executor.instances、spark.driver.memory、spark.driver.cores、spark.default.parallelism、spark.sql.shuffle.partitions、spark.dynamicAllocation.enabled、spark.dynamicAllocation.minExecutors、spark.dynamicAllocation.maxExecutors、spark.yarn.executor.memoryOverhead；其余属性值及其他环境属性组的值统一脱敏。允许值仍经过上述检查。
- 保持事件结构、行序和数值指标；一条源记录对应一条紧凑 UTF-8 JSONL 记录。已知秘密不能进入结果、清单、文件路径或日志，无法安全序列化则失败。

不持久保存原始 JSON/ZIP 是现有凭据约束的直接要求；不在本 change 扩展到通用隐私分类或诊断分析。

### 7. 一个下载目录、一份清单

cache_dir 专用且私有（目录 0700、文件 0600）；根目录采用标准库 fcntl 非阻塞排他锁，另一活动进程使用同根时本地 CONFIG_ERROR。锁随进程退出释放；不增加 instance_id、owner.json 或独立 namespace 层。进程内获取串行，关闭时释放自己的客户端和锁。

```text
cache_dir/
  .lock
  .part-<random-id>/                   # 当前调用的临时 ZIP、JSONL、清单
  <application_id>/all|attempt-<id>/<random-id>/
    eventlog-0001.jsonl               # 全部 attempts 时每成员一个文件
    manifest.json
```

JSONL 在下载后的逐行校验/脱敏阶段生成于临时目录；全部成员成功后写清单，移除原始 ZIP，再同文件系统 rename 整个目录发布。失败或取消删除本次临时目录，不覆盖或删除以前成功的目录。进程被强杀可能留下 .part，永不作为命中候选，用户可手工清理；不实现 crash recovery、对象回滚图或 fsync 耐断电事务。

manifest 只包含 format_version=1、规范化 history_server_url 与成功结果中除 cache_hit 外的所有字段。manifest_path/local_path 必须位于本次目录；清单/JSONL 不能是 symlink。不额外生成索引、owner、摘要旁车或事件统计文件。

refresh=false 查找同 history_server_url、application_id、requested_attempt_id 的最新下载清单，检查结构、文件存在性与 sha256，再直接返回；没有候选才下载。损坏候选返回 UNEXPECTED_RESPONSE，调用者可 refresh=true 重新获取。all 与指定 attempt 不互相冒充；不同来源不能命中。旧人工文件/未知目录不自动导入或删除。

refresh=true 新建一个下载目录，即使内容相同也不去重。保留历史目录直到用户清理，不做 TTL、容量回收或 offline 模式。单次 max_bytes 和文件系统写入错误提供边界；不承诺全局磁盘配额。保存的数据不是上游最新性保证，需要更新时显式 refresh。

### 8. 安全错误

新增 ToolOperation.FETCH_SPARK_EVENT_LOG 与 application_id/attempt_id 安全白名单，沿用现有错误字段和 MCP 序列化。

已核对安装的 MCP SDK：FastMCP 参数模型默认忽略 extra，且在校验前尝试 JSON 字符串转换。stdio server 使用 SDK 的 func_metadata 参数模型，在调用 FastMCP 前验证原始参数；模型 extra=forbid、hide_input_in_errors=True，Spark 参数以严格类型注解声明。tools/list 发布闭合输入 schema。失败转换为固定 INVALID_INPUT ToolError，不输出原始 ValidationError。此通用边界不引入插件 import、配置项或依赖；其他插件保留已有声明类型的校验语义。

注册后将已验证的参数模型装入 SDK tool 的 FuncMetadata 子类，关闭二次 JSON 字符串预解析，保留既有输出 schema/model/wrap 行为，确保字面 attempt "null" 与 JSON null 不混淆。当前 SDK 的 tool-manager lookup 是内部接口，受精确输入/输出和 stdio 回归测试保护；升级 SDK 时必须复核此处。

| 条件 | category | retryable |
| --- | --- | --- |
| 非法配置/CA/Cookie、目录锁冲突、非 POSIX | CONFIG_ERROR | false |
| 无效参数 | INVALID_INPUT | false |
| 401、3xx、HTTP 200 HTML 登录页 | AUTHENTICATION_FAILED | false |
| 403、文件权限拒绝 | PERMISSION_DENIED | false |
| 404 | NOT_FOUND | false |
| TLS 信任失败 / 其他连接失败 | CONNECTION_FAILED | false / true |
| 总超时 | TIMEOUT | true |
| 429/5xx | UPSTREAM_ERROR | true |
| 其他 HTTP、大小超限、磁盘写入失败 | UPSTREAM_ERROR | false |
| ZIP/CRC/事件/身份非法、缓存损坏 | UNEXPECTED_RESPONSE | false |

```json
{
  "category": "AUTHENTICATION_FAILED",
  "operation": "fetch_spark_event_log",
  "message": "Authentication failed.",
  "retryable": false,
  "identifiers": {"application_id": "application_1700000000000_0042", "attempt_id": "1"},
  "correlation_id": "00000000-0000-4000-8000-000000000001"
}
```

无原始响应正文、Cookie、headers、SQL 内容、异常 repr 或堆栈。取消继续传播并清理，不转换为成功或发起重试。

## Risks / Trade-offs

- [已有 Cookie 过期、私有 CA 未配置] → 明确认证/连接错误，部署维护登录会话与信任链；用户可显式关闭校验，但连接不再验证服务器身份。
- [源日志尾行损坏] → 首版报错，修复策略留给后续需求。
- [标准 ZipFile 构建元数据时的内存放大] → 仅固定受信 History Server，限制完整 ZIP 大小和处理成员数；独立 metadata 预检后置。
- [多次 refresh 增加磁盘占用] → 用户管理专用目录；不为首版引入 GC。强杀残留也手工清理。
- [缓存陈旧或脱敏移除部分环境信息] → 下载时间、显式 refresh、源/输出摘要说明实际证据；不伪造源字节一致性或最终状态。
- [后续分析需要其他版本/压缩格式] → 后续能力另行扩展，下载工具不预建适配器框架。

## Migration Plan

部署准备可信 CA、安全环境 Cookie 和专用 cache_dir；通过现有 mcp-stdio 启动 spark。原三个插件无需配置迁移。人工下载文件保留原位，首版重新下载生成自己的清单。回滚时停止 Spark 实例并移除 host 配置，本地证据由用户保留或清理。

## Verification

按 tasks.md 串行 TDD；HTTP 测试负责传输/auth/TLS，文件测试负责 ZIP/JSONL/脱敏/发布，service 与 stdio 测试负责精确契约和跨会话复用。使用合成日志与 mock transport，不提交真实日志。完整 unit/contract、lint、类型、构建、console smoke 与 strict OpenSpec 验证继续保留；真实下载仅环境显式 opt-in，缺少条件记录 skipped。
