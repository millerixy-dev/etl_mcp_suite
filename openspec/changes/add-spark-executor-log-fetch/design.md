## Context

动机见 proposal.md。现有 `spark` 插件已实现 eventlog 下载、离线检索和性能指标五个工具及私有 L3 证据，已有 httpx、strict Pydantic models、错误边界、环境秘密、Knox 登录与目录锁。用户已选择保存脱敏本地文件并返回路径和摘要。

2026-10-13 工程经济性审查后的范围调整：先验证一个用户指定的 stdout 页面；不预建多部署兼容层。后续工具只使用部署确认的 NodeManager 路径和观察到的 HTML 形态，root 从既有 history_server_url 的 /sparkhistory mount 派生。大小上限固定，详细溯源放 manifest，缺 executor 不自动重下载 eventlog，完整 EOF 末行不因缺换行被丢弃。

2026-10-13 对用户指定的真实 ZIP 做只读核验：Spark `2.4.7.7.1.7.1000-141`，Driver 和五个 executor 的 stdout/stderr 原始 URL 均指向 `http://<node>:8042/node/containerlogs/<container>/<owner>/<stream>?start=-4096`；当前脱敏对该样本的 URL 没有改变。截图选中 Driver；用户给出的最终 URL 是同网关 `/jobhistory/joblogs/<nodeId>/<container>/<entity>/<owner>/stdout?scheme=http&host=<history-host>&port=19888`。样本与截图不是同一个 application/attempt；未声称完成该生产网关的端到端认证读取。

## Goals / Non-Goals

**Goals:** 以精确 application/attempt/executor/stream 获取一份有界尾部证据；身份及容器来自 eventlog；可处理已退出容器的聚合日志跳转；结果不包含日志正文。

**Non-Goals:** 见 proposal.md。首版限定 POSIX、YARN 容器日志和已引用的 NodeManager/JobHistory HTML 形态；不处理多个同名聚合日志版本、不补猜缺失身份，不改 eventlog 的脱敏白名单。

## Decisions

### 1. 从事件取得 URL，沿网关跳转取得节点标识

选择 eventlog URL → 配置的 NodeManager 网关 → 受控 JobHistory redirect → HTML 正文。直接拼 JobHistory 地址需要额外维护 NodeId 与上游历史服务地址；直连内网 NodeManager 不符合当前网关访问方式。两者均不作为首版后备路线。Spark UI 的 executor Logs 就用这些 URL；Driver 与普通 executor 必须分开定位。

| Endpoint / entity | Verified contract | Primary source |
| --- | --- | --- |
| eventlog ZIP | GET `<history_server_url>/api/v1/applications/{application_id}/{attempt_id}/logs`；内部复用现有下载能力 | [Spark 2.4.7 REST API](https://archive.apache.org/dist/spark/docs/2.4.7/monitoring.html#rest-api) |
| Driver 日志入口 | ApplicationStart 的 `Driver Logs[log_type]` | [JsonProtocol applicationStartToJson](https://github.com/apache/spark/blob/v2.4.7/core/src/main/scala/org/apache/spark/util/JsonProtocol.scala) |
| Executor 日志入口 | ExecutorAdded 的 `Executor ID`、`Executor Info.Log Urls[log_type]`；先选择最后一个匹配ID的注册事件，再校验其中URL，不能退回旧容器 | [JsonProtocol executorAddedToJson/executorInfoToJson](https://github.com/apache/spark/blob/v2.4.7/core/src/main/scala/org/apache/spark/util/JsonProtocol.scala) |
| NodeManager 原始入口 | HTTP(S) `/node/containerlogs/{container}/{owner}/{log_type}`，`start=-N` 取尾部，缺省约 4 KiB，HTML 正文在 pre | [ContainerLogsPage](https://github.com/apache/hadoop/blob/rel/release-3.1.1/hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-nodemanager/src/main/java/org/apache/hadoop/yarn/server/nodemanager/webapp/ContainerLogsPage.java) |
| Knox YARNUI 网关入口 | `<gateway_root>/yarn/nodemanager/node/containerlogs/{container}/{owner}/{log_type}?start=-N&scheme=S&host=H&port=P` | [YARNUI rewrite.xml](https://github.com/apache/knox/blob/master/gateway-service-definitions/src/main/resources/services/yarnui/2.7.0/rewrite.xml) |
| Knox YARNUIv2 网关入口 | `<gateway_root>/yarnuiv2/node/containerlogs/...`；protocol/host/port 和原 query 被保留 | [SparkHistoryUI containerlogs rewrite](https://github.com/apache/knox/blob/master/gateway-service-definitions/src/main/resources/services/sparkhistoryui/2.3.0/rewrite.xml) |
| NodeManager redirect | application 不在本机且聚合启用时，307 Location 来自 `yarn.log.server.url`，追加 NodeId、container、container、owner、log_type，并保留 query | [NMWebAppFilter](https://github.com/apache/hadoop/blob/rel/release-3.1.1/hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-nodemanager/src/main/java/org/apache/hadoop/yarn/server/nodemanager/webapp/NMWebAppFilter.java) |
| JobHistory/Knox 聚合日志 | 上游 `/jobhistory/logs/{nodeId}/{container}/{entity}/{owner}/{log_type}`；网关 `/jobhistory/joblogs/...`，Location 改写带 scheme/host/port | [HsWebApp](https://github.com/apache/hadoop/blob/rel/release-3.1.1/hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-hs/src/main/java/org/apache/hadoop/mapreduce/v2/hs/webapp/HsWebApp.java)、[Knox JobHistoryUI rewrite](https://github.com/apache/knox/blob/master/gateway-service-definitions/src/main/resources/services/jobhistoryui/2.7.0/rewrite.xml)、[YARNUI Location rewrite](https://github.com/apache/knox/blob/master/gateway-service-definitions/src/main/resources/services/yarnui/2.7.0/rewrite.xml) |
| 聚合 HTML 元数据和正文 | Log Type、Log Upload Time、Log Length、Showing N bytes，后接 pre；多个同名块不自动合并 | [TFileAggregatedLogsBlock](https://github.com/apache/hadoop/blob/rel/release-3.1.1/hadoop-yarn-project/hadoop-yarn/hadoop-yarn-common/src/main/java/org/apache/hadoop/yarn/logaggregation/filecontroller/tfile/TFileAggregatedLogsBlock.java) |
| 认证 | 沿用现有已验证的空 POST + Basic → Knox Cookie，登录本身不跟随 Location | [Knox SSO](https://apache.github.io/knox/config_knox_sso/)、现有 change 的 design.md/verification.md |

引用版本证明源协议，不证明生产部署启用某条 route；表中两条网关路径只作参考来源，不要求实现两套兼容分支。NodeManager路径由部署显式配置，首版解析以真实stdout验证观察到的形态为准。`8042` 是 URL 的 Web 端口；`8041` 是 redirect 中的 NodeId 端口；截图 executor Address 是 BlockManager 端口。不能互相替代。container 的 epoch、application、attempt 均来自原 URL，不能拼 `executor_id + 1`。

### 2. 一个新增工具，显式 attempt，始终获取新的日志证据

拟新增公共接口：

`fetch_spark_executor_log(application_id, attempt_id, executor_id, log_type="stderr", tail_bytes=65536)`

| Input | Type | Default | Validation / meaning |
| --- | --- | --- | --- |
| application_id | strict string | required | ASCII `application_[0-9]+_[0-9]+`，最多 128 字符，沿用现有 validator |
| attempt_id | strict string | required | canonical positive decimal `[1-9][0-9]{0,9}`；调用者明确选择 YARN attempt，无 null/latest |
| executor_id | strict string | required | `driver` 或 canonical nonnegative decimal `0|[1-9][0-9]{0,19}` |
| log_type | strict string enum | stderr | 仅 stdout/stderr；默认 stderr 服务故障定位 |
| tail_bytes | strict integer | 65536 | 1–1048576，固定上限；bool/string 不作为整数 |

所有参数在 service/MCP 边界同时校验，未知字段 INVALID_INPUT；不接受 URL、文件路径、headers、认证或 TLS。每次调用都下载日志；不设 refresh/cache_hit，不以旧日志回答当前请求。eventlog 仍可按现有来源/身份/hash规则复用。

成功结果 `SparkExecutorLogFetchResult` 的全部字段如下（合成值）：

```json
{
  "application_id": "application_1700000000000_0042",
  "attempt_id": "2",
  "executor_id": "driver",
  "container_id": "container_e83_1700000000000_0042_02_000001",
  "log_type": "stderr",
  "requested_tail_bytes": 65536,
  "fetched_at": "2026-10-13T08:00:00Z",
  "coverage": "tail",
  "local_path": "/var/tmp/mcp-spark-l3/executor-logs/application_1700000000000_0042/attempt-2/driver/00000000000040008000000000000001/stderr.log",
  "size_bytes": 64000,
  "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "manifest_path": "/var/tmp/mcp-spark-l3/executor-logs/application_1700000000000_0042/attempt-2/driver/00000000000040008000000000000001/manifest.json"
}
```

公共结果共12项：application_id、attempt_id、executor_id、container_id、log_type、requested_tail_bytes、fetched_at、coverage、local_path、size_bytes、sha256、manifest_path。coverage为tail/complete/unknown，分别表示已知省略了前部、确认取得全部或无法判断；不能把未知当完整。source_kind、source_size_bytes、event_log_path/hash及边界处理细节只记录manifest，不扩大公共契约。零字节真实日志合法，SHA-256对保存字节计算；不返回正文或凭据。

### 3. 配置和兼容性

下表包含本工具使用的全部部署字段；`executor_log_*` 为本提案新增字段，其他字段沿用现有契约。

| Field | Type | Default | Range | Required |
| --- | --- | --- | --- | --- |
| version | int | — | 固定 1 | 文件模式是 |
| plugin | string | — | 固定 spark | 文件模式是 |
| settings.history_server_url | string | — | HTTPS，<=2048，无 userinfo/query/fragment，沿用现有严格 mount 校验 | 是 |
| settings.cache_dir | string | — | <=4096 的专用 POSIX 绝对路径，拒绝 symlink；进程独占 | 是 |
| settings.verify_tls | strict bool | true | true/false，沿用显式部署开关 | 否 |
| settings.ca_bundle_path | string/null | null | 可读可信 PEM 绝对路径，配置时本地验证 | 否 |
| settings.knox_sso_url | string/null | null | 与 history origin 相同的 HTTPS endpoint，<=2048，无 query/userinfo/fragment | Basic 模式是 |
| settings.request_timeout_seconds | float | 300.0 | >0、<=900；整个新工具的一份 deadline | 否 |
| settings.max_bytes | int | 268435456 | 1–1073741824；仅内部 eventlog 原有 ZIP/JSONL 上限 | 否 |
| settings.executor_log_node_manager_path | string/null | null | <=512，网关root下的已确认绝对path，末尾为/node；拒绝query、fragment、控制字符、反斜杠、traversal；null禁用新工具 | 使用新工具时是 |
| settings.executor_log_allowed_upstreams | list[string] | [] | 1–128个唯一http(s)://host:port规则，允许单DNS标签通配符，无path/query/userinfo/fragment，显式端口1–65535 | path非null时是 |
| secrets.gateway_cookie | env reference / SecretStr/null | null | 非空秘密值，无 CR/LF/NUL，与 Basic 互斥 | Cookie 模式是 |
| secrets.username | env reference / SecretStr/null | null | 沿用既有 Basic 成对、非空、无冒号/控制字符规则 | Basic 模式是 |
| secrets.password | env reference / SecretStr/null | null | 沿用既有 Basic 成对、非空、无控制字符规则 | Basic 模式是 |

只新增上述两项设置。启用时history_server_url必须以/sparkhistory结尾，去掉该suffix得到gateway root，避免重复配置。path=null且upstreams=[]保持旧配置兼容；半配置返回CONFIG_ERROR；本能力贡献fetch_spark_executor_log；启动注册已实现Spark能力的精确工具并集，不混入其他插件工具，不联网。响应固定8MiB、保存正文固定1MiB、最多三次日志GET跳转；上限不是新的配置项。实际请求始终同HTTPS origin和gateway mount，上游allowlist同原严格规则。

文件模式 YAML（占位部署，secrets 只填环境变量名）：

```yaml
version: 1
plugin: spark
settings:
  history_server_url: https://history.example.invalid:8443/gateway/analytics/sparkhistory
  cache_dir: /var/tmp/mcp-spark-l3
  ca_bundle_path: /etc/mcp/spark-ca.pem # 私有 CA；使用公共信任可省略
  executor_log_node_manager_path: /yarn/nodemanager/node # 示例；须替换为部署已确认的路径
  executor_log_allowed_upstreams:
    - "http://*.nodes.example.invalid:8042" # NodeManager Web，仅一个节点标签
    - "http://jobhistory.example.invalid:19888" # JobHistory，显式配置
  # 正文固定上限1MiB，HTML固定上限8MiB；保持既有TLS设置。
secrets:
  gateway_cookie: SPARK_GATEWAY_COOKIE
```

```sh
# Cookie 由安全环境注入；实现 task 同步提供 docs/examples/spark-executor-logs.yaml 和等价 JSON。
uv run --locked mcp-stdio --plugin spark --config docs/examples/spark-executor-logs.yaml
```

等价 JSON 文件：

```json
{
  "version": 1,
  "plugin": "spark",
  "settings": {
    "history_server_url": "https://history.example.invalid:8443/gateway/analytics/sparkhistory",
    "cache_dir": "/var/tmp/mcp-spark-l3",
    "ca_bundle_path": "/etc/mcp/spark-ca.pem",
    "executor_log_node_manager_path": "/yarn/nodemanager/node",
    "executor_log_allowed_upstreams": ["http://*.nodes.example.invalid:8042", "http://jobhistory.example.invalid:19888"]
  },
  "secrets": {"gateway_cookie": "SPARK_GATEWAY_COOKIE"}
}
```

环境变量映射（list 按现有 JSON list env 解码）：

| Env | Field |
| --- | --- |
| SPARK_HISTORY_SERVER_URL | settings.history_server_url |
| SPARK_CACHE_DIR | settings.cache_dir |
| SPARK_VERIFY_TLS | settings.verify_tls |
| SPARK_CA_BUNDLE_PATH | settings.ca_bundle_path |
| SPARK_KNOX_SSO_URL | settings.knox_sso_url |
| SPARK_REQUEST_TIMEOUT_SECONDS | settings.request_timeout_seconds |
| SPARK_MAX_BYTES | settings.max_bytes |
| SPARK_EXECUTOR_LOG_NODE_MANAGER_PATH | settings.executor_log_node_manager_path |
| SPARK_EXECUTOR_LOG_ALLOWED_UPSTREAMS | settings.executor_log_allowed_upstreams |
| SPARK_GATEWAY_COOKIE | secrets.gateway_cookie 的环境秘密值 |
| SPARK_USERNAME | secrets.username 的环境秘密值 |
| SPARK_PASSWORD | secrets.password 的环境秘密值 |

```sh
export SPARK_HISTORY_SERVER_URL='https://history.example.invalid:8443/gateway/analytics/sparkhistory'
export SPARK_CACHE_DIR='/var/tmp/mcp-spark-l3'
export SPARK_CA_BUNDLE_PATH='/etc/mcp/spark-ca.pem'
export SPARK_EXECUTOR_LOG_NODE_MANAGER_PATH='/yarn/nodemanager/node'
export SPARK_EXECUTOR_LOG_ALLOWED_UPSTREAMS='["http://*.nodes.example.invalid:8042","http://jobhistory.example.invalid:19888"]'
# Cookie 或完整 Basic 三变量由秘密管理环境注入；Basic 模式另设下面的非敏感 SSO 地址。
# export SPARK_KNOX_SSO_URL='https://history.example.invalid:8443/gateway/knoxsso/api/v1/websso'
uv run --locked mcp-stdio --plugin spark
```

### 4. 精确身份和受控 URL 策略

应用服务先校验输入/配置，然后经新 gateway 在同一 deadline 内按原 eventlog gateway lookup/download 取得单一 attempt 的已校验文件；只读扫描遵循 remove-spark-event-line-limit 的已批准策略：按剩余 max_bytes 总量预算加 1 字节读取，无独立事件行上限，验证事件 application/attempt，取末次匹配 Driver/Executor 注册事件。只读解析不额外保存索引。若缺该executor/stream，返回NOT_FOUND，并提示可用现有eventlog工具显式refresh；本工具不自动重下载整份eventlog。不重新读取其它 attempt，不调用其它 MCP tool，不调用其它插件。原 eventlog client 的网络规则不放宽。

只接受原 HTTP(S) NodeManager `/node/containerlogs/{container}/{owner}/{stream}`，或已是同配置网关的认可日志路径。路径分段解码验证后重新编码；owner 是 URL 的路径值，最多 256、无控制字符/分隔符；禁止替换成登录用户名。container须匹配 YARN container 格式（允许epoch），解析出的 application数字组成及attempt整数须与请求相同；epoch、补零、完整原字符串保留。容器路径与 log_type 不一致、被脱敏成占位符或身份冲突均失败，不修补。原 URL 的上游 authority 必须命中allowlist；丢弃原 start/end，设置start=-tail_bytes；未知 query、重复参数、userinfo/fragment 均拒绝。

构造的实际请求只发往gateway HTTPS origin，用派生root + 配置node_manager_path + `/containerlogs/...`；query中scheme/host/port来自已验证原authority。不探测候选路径、不直连内部host。

日志 GET 默认 follow_redirects=False。只由新 adapter 显式处理 302/303/307/308，最多三次跳转、环检测。相对 Location 用当前 URL 解析；只允许同 gateway root 的上述 NodeManager route或`/jobhistory/joblogs/{nodeId}/{container}/{entity}/{owner}/{stream}`。NodeManager重定向仍固定原host/port；JobHistory上游由Location带入且须命中allowlist，首次固定后不得变化。每一步重复校验身份、日志类型、owner、query及authority；JobHistory entity须等于container，nodeId主机须等于原NodeManager主机，NodeId端口从Location取得并只验证有效范围，绝不从8042推导8041。允许start、scheme、host、port；start统一重写为-tail_bytes，拒绝end、重复/未知参数（不接受扩大范围的跳转）。

SSO/login Location 映射 AUTHENTICATION_FAILED，不自动重新登录；其它不允许跳转映射 UNEXPECTED_RESPONSE，不能发出下一请求。这个受控GET跳转许可只属于新工具；fetch_spark_event_log仍不跟随任何redirect。

### 5. 认证、HTML、范围和错误

认证复用现有 Cookie/Basic规则。日志读取网络段Basic至多登录一次，originalUrl沿用现有History根地址，_login的download_url参数用于校验Cookie是否适用于本次日志GET；Authorization只到配置SSO POST，不到GET。内部eventlog下载若需要网络，仍使用自己的既有认证交换；两段共享同一外层deadline，不能重置预算。Cookie显式发送到受信网关，jar按域/path规则匹配；收集本次获得的Cookie为脱敏值，退出/取消/关闭清空。禁止浏览器credential提取、密码重试、后台续期、环境代理及HTTP wire logging。仅日志GET可按上一节跳转。

HTML原字节只在有界内存处理，不落盘；httpx流式读 actual bytes，identity编码，逐请求及累计日志响应受固定8MiB上限限制。使用标准库HTMLParser/entity解码，不执行脚本、加载资源或遵循HTML/meta-refresh指令。首版只接受UTF-8已识别NodeManager/聚合HTML日志页，一份明确匹配stream的pre正文；识别登录form、外部h1错误和身份title/元数据，与pre正文严格分开。聚合页依据Log Type/Log Length等元数据定位；同stream多个内容块拒绝，不冒充一份完整日志。身份由已校验的请求URL及未改变身份的响应URL约束；若HTML提供身份元数据则须一致，但不要求不存在的页头字段。真实JobHistory页面可无页头container，其模板可能含空白pre；须将Log Type/Log Length元数据与其后的正文pre关联，只统计内容块，不能把模板空白块当作多版本。无recognized页结构即失败，不把任意pre或HTTP200当成功。完整页且明确长度0的空pre可成功。

如果解码出的源正文超过请求的tail_bytes，说明上游没有遵守范围，返回UNEXPECTED_RESPONSE，不以脱敏后的字节数推算源范围，也不扩大保留内容。UTF-8尾部可能从字符/逻辑行中间开始。仅对取得的日志片段做固定凭据脱敏与已知secret替换；当明确源长度大于返回片段、确认字节起点非零时，保守丢弃首个逻辑行以避免保留可能截断的凭据前缀；没有这种证据时不丢首行；完整读取到EOF的末行保留并脱敏，即使没有换行。UTF-8不完整边界须安全处理，处理细节放manifest；不修复原始内容。固定规则覆盖password/passwd/secret/token/cookie/authorization/credential/access-key/private-key赋值、Basic/Bearer、URL userinfo、Cookie/Set-Cookie及已配置/本次获取秘密；复用现有文本脱敏函数，测试已知秘密与凭据赋值；有界正文先收集再脱敏，不建设流式跨块脱敏状态机。日志正文不应用EnvironmentUpdate白名单。脱敏输出若超过固定1MiB，按完整逻辑行保留尾部并记录coverage=tail；不得因HTML实体或脱敏膨胀突破上限。

| Condition | ToolError category | Retryable |
| --- | --- | --- |
| 无日志网关配置 | CONFIG_ERROR | false |
| 参数/额外字段非法或tail超配置 | INVALID_INPUT | false |
| 缺executor/stream、HTTP404、明确日志缺失 | NOT_FOUND | false；明确聚合尚未完成提示为true |
| 401、SSO redirect、recognized登录HTML | AUTHENTICATION_FAILED | false |
| 403、recognized聚合ACL拒绝 | PERMISSION_DENIED | false |
| TLS/传输失败 | CONNECTION_FAILED | TLS失败false，其它true |
| 超外层deadline（含排队/定位/下载/解析/发布） | TIMEOUT | true |
| 429/5xx、流字节上限、本地IO故障 | UPSTREAM_ERROR | 429/5xx true；上限false；IO按既有映射 |
| URL/身份/redirect/encoding/HTML形态不支持、损坏本地证据 | UNEXPECTED_RESPONSE | false |

shared operation为新增`fetch_spark_executor_log`；安全identifier只含application_id、attempt_id、executor_id、log_type。内部eventlog阶段失败也由外层转成这个operation，保留原category/retryable和已验证identifier，并通过现有ToolError.create生成本次错误的correlation_id，不向调用者泄露错误来自哪个内部adapter。例：

```json
{"category":"NOT_FOUND","operation":"fetch_spark_executor_log","message":"The requested resource was not found.","retryable":false,"identifiers":{"application_id":"application_1700000000000_0042","attempt_id":"2","executor_id":"3","log_type":"stderr"},"correlation_id":"00000000-0000-4000-8000-000000000001"}
```

### 6. 存储、架构和内部接口

沿用cache_dir的既有单进程目录锁；不能由新adapter第二次独立加锁。composition注入同一进程已有eventlog gateway与持有锁的证据root，新adapter不释放别人的锁。新service只依赖领域模型、新gateway；HTTP/HTML/文件工作都属于同一spark slice。首版新增一个聚焦的`executor_logs.py`适配器承载日志访问/解析/发布，复用既有认证及文本脱敏；不预建三个独立模块或额外策略层。只有实际职责/规模需要时才拆分。复用httpx、Pydantic和标准库；不增加依赖、不调用其它插件。

新增内部port为`SparkExecutorLogGateway.fetch(request, *, deadline)`及幂等`close()`：

| Interface input | Type | Meaning |
| --- | --- | --- |
| fetch.request | SparkExecutorLogRequest | 上述五项已校验工具输入，无URL/secret |
| fetch.deadline | float monotonic absolute time | 上层唯一时间预算，包括排队 |
| close | none | 取消/等待owned acquisitions，清Cookie/关闭客户端，不释放外部锁 |

fetch的代表JSON输入为`{"application_id":"application_1700000000000_0042","attempt_id":"2","executor_id":"driver","log_type":"stderr","tail_bytes":65536}`，结果与第2节完整JSON相同；失败使用上节ToolError。close成功无返回值（JSON null）。应用服务内部fetch输入/输出与公共工具同形，增加此port的deadline；MCP adapter只翻译输入输出。具体HTTP/HTML helpers为私有实现，不形成额外工具或稳定接口。

日志存储分离于现有eventlog selector：

```text
<cache_dir>/executor-logs/<application_id>/attempt-<attempt_id>/<executor_id>/<random-id>/
  stderr.log              # 或stdout.log，UTF-8脱敏文本
  manifest.json
```

目录0700，普通文件0600，拒绝symlink/traversal，私有`.part-*`目录生成脱敏文本+manifest后原子rename。新manifest含`format_version=1`、第2节全部结果字段，以及`source_kind`、`source_size_bytes`、`event_log_sha256`和`gateway_root`、`node_manager_path`、脱敏后的`source_url`（仅批准query）和`event_log_path`；source_url不得保留userinfo/凭据，event_log_sha256将来源绑定到实际验证文件。不保存原HTML、Cookie、原正文、额外日志摘要文件。摘要为结构元数据及散列，不作AI总结。

每次UUID新目录，不复用旧日志、不覆盖旧证据。失败/超时/取消只删除本次未发布目录；关闭取消/等待owned工作后关闭客户端，再由现有owner释放cache锁。SHA-256用保存字节重新计算；成功返回前证据须存在、hash匹配。强杀残留.part不被读取复用；不加入GC。

### 7. 测试与实施顺序

按tasks.md执行，严格RED/GREEN/REFACTOR；共享契约、配置、错误先串行定义，之后各适配器仍按依赖顺序验证。测试使用合成events、fake gateways、httpx MockTransport和合成HTML；真实ZIP/日志不提交。重点包括driver vs executor、重复注册、epoch/attempt一致、缺URL不自动刷新、网关query SSRF、redirect环/跨origin/SSO/改变身份、Cookie path及Basic header、HTML200错误/空日志/多个版本、secret跨块/跨行/尾部边界、大小/时间上限、atomic发布与shutdown锁。affected suite及stdio/architecture通过后执行全套质量检查。

## Risks / Trade-offs

- [部署路由/HTML可能与引用版本不同] → route显式配置，形态不支持失败，使用认证环境执行opt-in真实验证，不把来源核验当作端到端通过。
- [聚合日志尚未生成或已清理] → NOT_FOUND及明确retryable；不轮询、不推导成功/失败。
- [eventlog没有URL或脱敏改变了URL] → 安全失败；不放宽环境秘密政策以“修复”身份。
- [尾部丢弃不完整行会得到较短甚至空文件] → 返回字节数和coverage，边界处理细节只存manifest；不能宣称包含全文。
- [HTML包含多个上传版本] → 首版拒绝歧义，后续如需支持必须新规格明确版本选择/合并口径。
- [日志内容的固定脱敏无法理解所有业务隐私] → 只保存私有本地证据，不把正文放入MCP结果；不承诺通用业务数据匿名化。
- [同网关query也能控制后端host] → 所有原authority和redirect上游均受scheme/host/port allowlist，实际网络目的地固定HTTPS gateway。

## Migration Plan

实施只增加一个工具和可选配置。旧配置启动仍无网络请求，eventlog功能保留；未启用网关时新tool返回CONFIG_ERROR。README与两个架构视图同步描述已实现Spark能力的工具并集、同锁与仅新工具受控redirect。真实stdout验证阶段不注册新工具、不改生产代码；验证用私有临时脚本直接调用既有SparkHttpClient认证和脱敏函数。部署先配置可信CA、已确认route和最小allowlist，再opt-in验证Driver及一个executor的stderr和原子证据。回滚到旧版本同时删除新增executor_log_*配置，旧版本strict配置会拒绝这些新字段；既有eventlog证据不迁移，新增私有日志目录不会被旧eventlog查找器当作缓存。

## First Validation Gate

本轮只执行tasks.md的1.1：复用SparkHttpClient._ensure_client/_login及既有文本脱敏函数，GET用户已提供的同源JobHistory stdout地址，start=-65536，响应上限8MiB，保存正文上限1MiB。URL由已授权人工验证上下文固定，不进入MCPschema。默认不跟随redirect；任何跳转先检查是否登录/同源认可路径，记录安全结果，不自动探测其它服务。

输入为既有SparkSettings/SparkSecrets和固定用户URL，配置/秘密来自已授权Spark认证来源；结果为下例的私有文件摘要，仅本地验证使用：

```json
{"application_id":"application_1783000588461_687089","attempt_id":"2","executor_id":"driver","log_type":"stdout","local_path":"/private/cache/stdout.log","size_bytes":1024,"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","manifest_path":"/private/cache/manifest.json"}
```

先运行现有认证/脱敏相关单测，临时解析程序用合成HTML断言识别真实stdout、拒绝登录页和保留EOF末行，再进行真实请求。只输出HTTP状态、正文结构/长度、身份、私有权限和hash；不输出HTML、Cookie或日志正文。认证成功但没有stdout正文不算通过；最终必须独立重读脱敏文件并验证hash及已知秘密缺席。未获得认证或真实日志时任务保持未完成，并在verification.md记录具体障碍。原始HTML仅在有界内存，不落盘，临时验证脚本完成后删除。

验证中观察到的部署事实：HTTP200 HTML共8923字节，两个pre分别为2字节空白和4404字节stdout，Log Length=4404；container不在页头/链接属性中，仅在日志正文中。正文内的ID不得作为身份验证依据。临时解析器必须使用经过校验的已授权请求URL约束身份，并按stdout标签关联内容块。
