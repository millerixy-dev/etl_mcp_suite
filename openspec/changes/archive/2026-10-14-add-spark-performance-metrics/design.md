## Context

见 proposal.md。已有 fetch、inspect、query 和私有 L3 格式不变；`VerifiedEventLogReader` 已支持显式快照的完整单遍验证及 visitor。本期目标为 Spark 2.4.7，典型日志小于 100 MB；Agent 在对话上下文中管理假设与取证循环。

## Goals / Non-Goals

**Goals:** 提供可解释、可复核的 Stage 排名、Task 分布和下一查询入口，让 Agent 定位时间消耗并检查候选原因。

**Non-Goals:** 不新增诊断状态、性能基准或根因规则；不改变原 query 的直接匹配语义；不建立跨 job/SQL 关系、逻辑任务去重、关键路径或全部 Spark UI 状态模型。

## Decisions

### 1. 两个离线工具，复用快照

选择两个确定性工具，而不是把全部 Task 文本交给 Agent 计算，也不增加后端诊断器。应用起止和单 Task 详情沿用 query；不增加同义包装接口。

两个新工具共享下列必填输入，并沿用原验证、来源比对、私有路径、size/hash/event_count/identity 检查；预期摘要属于脱敏 JSONL。每次完整扫描且验证成功后才返回，不隐式下载/刷新，也不写聚合文件。

| 参数 | 类型 | 默认 | 范围/语义 | 必填 |
| --- | --- | --- | --- | --- |
| manifest_path | string | 无 | 绝对路径 ≤4096 字符，无控制字符，在配置 cache_dir 内 | 是 |
| attempt_id | string or null | 无 | [A-Za-z0-9_-]{1,128}；null 只选择实际无 application attempt | 是 |
| expected_sha256 | string | 无 | 64 位小写十六进制，来自 inspect.snapshot.sha256 | 是 |

bool/string 转数字、额外输入、越界值均拒绝。两个工具各有自己的安全 operation 名；输入错误 INVALID_INPUT，缺文件/缺 manifest attempt NOT_FOUND，快照/格式冲突 UNEXPECTED_RESPONSE，时限 TIMEOUT。错误不回显任意路径、正文或原始异常。

snapshot 和 coverage 沿用现有命名结构。所有 ref 是 `{sha256,line}`，绑定脱敏 JSONL 的 1-based 物理行。聚合的可复核范围由 snapshot、固定样本策略、stage/attempt 和计数共同确定；不将一个 ref 冒充全部聚合来源。

### 2. 最小指标和样本口径

固定六个指标，单位直接写入字段名，不接受自定义表达式或分位数参数：

| 字段 | 来源/计算 | 单位 |
| --- | --- | --- |
| duration_ms | Task Info.Finish Time − Launch Time | ms |
| executor_run_time_ms | Task Metrics.Executor Run Time | ms |
| jvm_gc_time_ms | Task Metrics.JVM GC Time | ms |
| input_bytes | Task Metrics.Input Metrics.Bytes Read | bytes |
| shuffle_read_bytes | Shuffle Read Metrics.Remote Bytes Read + Local Bytes Read | bytes |
| shuffle_fetch_wait_ms | Shuffle Read Metrics.Fetch Wait Time | ms |

原始数字必须是严格非负、≤2^63−1 的整数；bool、float、string、缺失和负数均不可用。时间差只在 Launch/Finish 都有效、Finish>0 且 Finish≥Launch 时有效。Shuffle 两个组成字段都有效才求和，两个合法分量之和使用 Python 非负整数，不截断。Task Metrics 对象缺失时其五个指标未知，不影响可计算的 duration。指标未知不导致整个合法事件日志失败。

只有 `Task End Reason.Reason == "Success"` 的 TaskEnd 进入性能样本；每条事件计为一个尝试，不按 partition/index 去重，也不混入失败/取消/未知尝试。计数固定为 task_end_count、successful_task_end_count、non_success_task_end_count、unknown_reason_task_end_count；后面三项和等于第一项，非成功表示明确有效的非 Success 原因，不表示应用失败。

所有指标各自有 valid_count/missing_count，二者之和等于成功样本数。无有效值时 total/min/p50/p95/max 为 null，显式零仍为零。固定 nearest-rank：非空值升序，p50/p95 分别取 1-based ceil(0.50*n)/ceil(0.95*n)，不插值；min/max 为首末值。无需平均值、直方图或其他分位数。

### 3. get_spark_stage_metrics

除共享输入外：

| 参数 | 类型 | 默认 | 范围/语义 | 必填 |
| --- | --- | --- | --- | --- |
| stage_id | int or null | null | [0,2^63−1]；与 stage_attempt_id 同时提供或同时省略 | 否 |
| stage_attempt_id | int or null | null | [0,2^63−1]；明确选择一个 Stage attempt | 否 |
| limit | int | 20 | [1,20] | 否 |

Stage attempt 按事件自身合法 Stage ID/Stage Attempt ID 分组：StageSubmitted/Completed 来自 Stage Info，TaskEnd 来自顶层。组可以只有 TaskEnd 而没有 Stage 生命周期。无法分组的 TaskEnd 不猜测归属，在全文件 unassigned_task_end_count 中披露；该计数不受 Stage 过滤影响。

每组分别保留最后一个 StageSubmitted 与最后一个 StageCompleted 的 ref。生命周期时间优先取最后一个 StageCompleted 的 Stage Info，若没有则取最后一个 StageSubmitted；不跨事件拼装一组时间。submission_time_ms/completion_time_ms 缺失/非法为 null，Stage duration 仅在两者有效且 completion≥submission 时计算；否则 null。输出不推断成功、正在运行、YARN 状态或关键路径。

Task 计数覆盖全文件该组 TaskEnd，Input/Shuffle 总量仅累加成功样本的有效指标，分别返回 MetricTotal（total、valid_count、missing_count）。这是尝试事件的数值合计，不是去重业务输入或应用耗时。

返回 `SparkStageMetricsResult`，精确字段为 snapshot、coverage、matched_stage_attempt_count、unassigned_task_end_count、stages、stages_omitted。Stage 列表按 duration 非 null 优先、duration 降序、stage_id 升序、stage_attempt_id 升序，截取 limit；matched/omitted 在截取前计算。首版不加分页；可 query StageCompleted/Submitted 取得其他直接 ID 后指定该组读取。未匹配返回空列表与零 matched，不变成错误。

Stage 行精确字段见合成示例，ref/null、整数/null、计数和 MetricTotal 结构都是固定合同：

```json
{
  "snapshot":{"application_id":"application_100_1","attempt_id":"1","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
  "coverage":{"application_start_seen":true,"application_end_seen":true},
  "matched_stage_attempt_count":1,
  "unassigned_task_end_count":0,
  "stages":[{
    "stage_id":17,"stage_attempt_id":0,
    "submission_time_ms":1000,"completion_time_ms":901000,"duration_ms":900000,
    "submitted_ref":{"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","line":10},
    "completed_ref":{"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","line":14},
    "task_end_count":3,"successful_task_end_count":2,"non_success_task_end_count":1,"unknown_reason_task_end_count":0,
    "input_bytes":{"total":300,"valid_count":2,"missing_count":0},
    "shuffle_read_bytes":{"total":1000,"valid_count":2,"missing_count":0}
  }],
  "stages_omitted":0
}
```

### 4. get_spark_task_distribution

除共享输入外：

| 参数 | 类型 | 默认 | 范围/语义 | 必填 |
| --- | --- | --- | --- | --- |
| stage_id | int | 无 | [0,2^63−1] | 是 |
| stage_attempt_id | int | 无 | [0,2^63−1] | 是 |
| order_by | string enum | duration_ms | 上述六个固定字段之一 | 否 |
| limit | int | 20 | [1,20] | 否 |

只匹配直接属于该 Stage attempt 的 TaskEnd。全量分类计数先算，六个分布分别覆盖全部成功样本，与 limit/order_by 无关。仅 order_by 指标有效的成功 TaskEnd 可进入 top_tasks，按该指标降序、物理行升序稳定排序。missing-order 值不进入排名；通过该分布 missing_count 披露。ranked_task_count 是截取前候选数，tasks_omitted=ranked_task_count−返回数。无匹配或无成功样本时仍成功返回空分布和空列表，不猜测该 Stage 存在与否。

排名任务返回全部六个指标，以比较同一任务的耗时与数据量，而不是只返回排序字段；其 task_id/executor_id 使用现有直接 ID 校验，缺失为 null，不影响数值样本。包含每条 TaskEnd 的 ref。无任务正文或任意嵌套对象，详情沿用 query 单 ref 回读。

返回 `SparkTaskDistributionResult`，精确结构如下。示例的全部字段必须出现；missing 指标按上述规则返回 null：

```json
{
  "snapshot":{"application_id":"application_100_1","attempt_id":"1","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
  "coverage":{"application_start_seen":true,"application_end_seen":true},
  "stage_id":17,"stage_attempt_id":0,
  "task_end_count":3,"successful_task_end_count":2,"non_success_task_end_count":1,"unknown_reason_task_end_count":0,
  "distributions":{
    "duration_ms":{"valid_count":2,"missing_count":0,"min":100,"p50":100,"p95":900,"max":900},
    "executor_run_time_ms":{"valid_count":2,"missing_count":0,"min":80,"p50":80,"p95":800,"max":800},
    "jvm_gc_time_ms":{"valid_count":2,"missing_count":0,"min":0,"p50":0,"p95":40,"max":40},
    "input_bytes":{"valid_count":2,"missing_count":0,"min":100,"p50":100,"p95":200,"max":200},
    "shuffle_read_bytes":{"valid_count":2,"missing_count":0,"min":100,"p50":100,"p95":900,"max":900},
    "shuffle_fetch_wait_ms":{"valid_count":2,"missing_count":0,"min":10,"p50":10,"p95":400,"max":400}
  },
  "order_by":"duration_ms","ranked_task_count":2,
  "top_tasks":[{
    "task_id":8,"executor_id":"2",
    "ref":{"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","line":13},
    "duration_ms":900,"executor_run_time_ms":800,"jvm_gc_time_ms":40,
    "input_bytes":200,"shuffle_read_bytes":900,"shuffle_fetch_wait_ms":400
  }],
  "tasks_omitted":1
}
```

MetricDistribution 不含 total；MetricTotal 不含分位数，避免 Stage 概览对全部 Stage 保留六组数组。输入/结果是严格命名 DTO，不加通用指标框架。

### 5. 架构与计算成本

在 Spark slice 增加最小指标 DTO 和计算模块，readonly gateway 扩展两个方法，service 负责输入/原 deadline/安全错误，MCP adapter 翻译固定结构。gateway 的两项请求输入/结果即上面两张表和对应 JSON，不另创不同 port 合同。复用现有 SparkInspectionAdapter 的 reader、扫描任务集合和 close；新增 metrics.py 放置 Stage/Task 聚合，避免重复实现一套 worker 生命周期。registry 保持唯一 concrete plugin 导入位置，core 只追加安全 operation 名及允许的 application/attempt identifier。

复用 VerifiedEventLogReader；Stage 扫描只保留每组计数、和与两项 refs。分布扫描只为指定组保存有效数值，优先使用标准库紧凑数值容器；排名仅保存至多 limit 条固定投影。完整 JSON 事件不保留。精确分位数需 O(选定组成功样本数) 的临时数值空间，排序 O(n log n)；不用采样/近似算法掩盖口径。六组数值在返回或取消后释放，不跨请求存活，不是 DiagnosisState。

两个工具与旧 inspector 共享已有专用目录所有权，不独立加锁；每个扫描响应取消/原总时限，runtime 关闭时先取消并等待扫描再释放 owner。沿用脱敏、公有结果校验和私有文件约束；即使新结果几乎全为数字，metadata/executor_id 仍通过既有安全边界。验证摘要失败、取消或超时不得返回部分聚合。

### 6. 配置与来源

无新配置、依赖或 upstream endpoint。继承配置如下；网络字段用于既有 fetch 和离线来源验证，新工具不联网：

| Field | Type | Default | Range | Required |
| --- | --- | --- | --- | --- |
| version / plugin | int / string | 无 | 1 / spark | 文件模式是 |
| secrets | object | 无 | 文件模式必须提供 mapping；无需凭证时为 {} | 文件模式是 |
| settings.history_server_url | string | 无 | 无凭证/query/fragment HTTPS，≤2048 字符 | 是 |
| settings.cache_dir | string | 无 | 专用私有绝对目录，≤4096 字符，非 symlink | 是 |
| settings.verify_tls | bool | true | 仅既有网络获取；false 跳过证书及主机名校验 | 否 |
| settings.ca_bundle_path | string or null | null | 绝对可读 PEM 路径 | 否 |
| settings.knox_sso_url | string or null | null | 同源 HTTPS，≤2048 字符 | Basic 模式是 |
| settings.request_timeout_seconds | float | 300.0 | (0,900]；完整扫描/计算沿用原 deadline | 否 |
| settings.max_bytes | int | 268435456 | [1,1073741824]；选定 JSONL 上限 | 否 |
| secrets.gateway_cookie | env reference or null | null | 非空，无 CR/LF/NUL，与 Basic 互斥 | 否 |
| secrets.username | env reference or null | null | 与 password 成对，非空，无冒号/控制字符 | Basic 模式是 |
| secrets.password | env reference or null | null | 与 username 成对，无控制字符 | Basic 模式是 |

文件示例保存为部署自己的 spark.yaml，只读分析已有证据不需要凭证：

```yaml
version: 1
plugin: spark
settings:
  # 必须匹配已有 manifest 来源；指标调用不会联网。
  history_server_url: https://history.example.invalid:8443/gateway/analytics/sparkhistory
  # 复用已有 L3，同一目录同时只允许一个 Spark 实例持有。
  cache_dir: /var/tmp/mcp-spark-l3
secrets: {}  # 文件模式保留空 mapping，不读取凭证。
```

启动：`uv run --locked mcp-stdio --plugin spark --config /absolute/path/to/spark.yaml`。

环境变量模式：

```sh
export SPARK_HISTORY_SERVER_URL='https://history.example.invalid:8443/gateway/analytics/sparkhistory'
export SPARK_CACHE_DIR='/var/tmp/mcp-spark-l3'
uv run --locked mcp-stdio --plugin spark
```

| 环境变量 | 映射 |
| --- | --- |
| SPARK_HISTORY_SERVER_URL / SPARK_CACHE_DIR | settings.history_server_url / settings.cache_dir |
| SPARK_VERIFY_TLS / SPARK_CA_BUNDLE_PATH | settings.verify_tls / settings.ca_bundle_path |
| SPARK_KNOX_SSO_URL | settings.knox_sso_url |
| SPARK_REQUEST_TIMEOUT_SECONDS / SPARK_MAX_BYTES | settings.request_timeout_seconds / settings.max_bytes |
| SPARK_GATEWAY_COOKIE / SPARK_USERNAME / SPARK_PASSWORD | 对应秘密值，仅受保护环境注入 |

上游字段来源：[Spark 2.4.7 JsonProtocol 的 stageInfoToJson/taskInfoToJson/taskMetricsToJson](https://github.com/apache/spark/blob/v2.4.7/core/src/main/scala/org/apache/spark/util/JsonProtocol.scala)。Stage attempt、TaskSummary/TaskList 和指标说明：[Spark 2.4.7 Monitoring REST API](https://archive.apache.org/dist/spark/docs/2.4.7/monitoring.html)。本实现读取本地事件而不调用这些 REST API，不承诺数值与 Spark UI 的样本/去重口径完全相同。Fetch Wait、GC、Executor Run Time 不解释为可相加的应用时间拆解。

### 7. Skill 与验收

扩展现有 Skill：核实用户问题与应用起止 → 固定快照 → Stage 排名 → 选定 attempt 分布/同一任务指标 → query refs、重试和 executor 证据 → 支持/反证 → 原因或缺口。不存在历史基准时不得声称 48 分钟异常；应用时间包含 Stage 之外的时间，Stage 可能重叠，无法解释的时间明确保留为缺口。

排名/比值只形成候选假设。数据量与耗时同时偏高支持进一步查倾斜；数据量接近而 Fetch Wait 高支持查 Shuffle 获取等待；GC 高支持查相关执行/外部证据。不得单凭这些事实确认倾斜、网络故障、OOM 或资源不足。原 supported/inconclusive/no_observed_failure 适用于故障；慢作业报告无失败时仍须说明可观察性能事实和限制，不能因 JobSucceeded 就终止慢作业调查。

手工演练至少三组，调用实际 MCP 后记录输入、数值、样本数、refs 和结论核对：长尾与大 Shuffle 同现；数据量相近但 Fetch Wait 偏高；有 Stage 重试且部分指标缺失。它们验证选择/反证流程，不宣称合成数据证实真实生产根因。自动测试另覆盖无成功样本、未完成 Stage、排序并列、页外/排名外统计、来源/摘要冲突与取消。

## Risks / Trade-offs

- [成功尝试仍有推测执行重复] → 输出是事件尝试样本，明确不去重，恢复查询由 Agent 执行。
- [最长 Stage 未必决定应用总耗时] → 不汇总为关键路径或应用时间占比，保留起止事件和范围限制。
- [精确分位数需要临时内存] → 只处理选定组且仅保存数值，典型规模验证后再考虑优化，不加持久索引。
- [前 20 排名未展示全部 Stage/Task] → 明示 matched/ranked 和 omitted，Stage 可明确指定；Task 可换固定排序或 query 直接读取。
- [小样本/缺失指标误判] → 每个指标报告 valid/missing 数和固定算法，Skill 不把候选信号直接确认为因果。

## Migration Plan

无缓存迁移与新配置。新增注册和 Skill 后精确工具集为已实现 Spark 能力并集；若仅 download/inspection/本能力实现，则为五个工具，executor-log 可独立增加其工具。回滚移除两项注册及 Skill 性能流程，不触碰已有证据和原三项合同。
