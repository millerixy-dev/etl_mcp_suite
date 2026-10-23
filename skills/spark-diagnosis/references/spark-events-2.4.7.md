# Spark 2.4.7 事件语义参考

按问题查相应章节，不必把整份参考载入工作上下文。范围是 Apache Spark 2.4.7 常用诊断事件；厂商版本、未知 Event/Reason 和缺失字段以实际证据为准。本参考解释事实，不把事件直接分类为根因。

## 名称、字段与证据范围

下表使用 event log 的完整 `Event` 值。核心事件由 [JsonProtocol](https://github.com/apache/spark/blob/v2.4.7/core/src/main/scala/org/apache/spark/util/JsonProtocol.scala) 序列化；其他事件可能是完整类名。先用 inspect 的 event_types 核对实际名称；如果 event_types_omitted 非零，列表不穷尽，可用 query 浏览或按已核实的完整名称检索。

字段路径描述 JSON 中的位置，**不是 query 参数名**。当前 query 只提供声明过的直接 ID 筛选，不能搜索任意嵌套字段。`details` 也是固定投影：例如 JobStart 省略 Stage Infos，Stage 生命周期省略 RDD Info/Accumulables，SQLExecutionStart 省略 sparkPlanInfo。扩大 max_detail_chars 只能扩大同一投影，不能恢复被省略/脱敏字段。已返回的未知事件 JSON 可回读，但仍受文本预算约束。

## 应用、Job 与 Stage

事件触发含义依据 [SparkListener](https://github.com/apache/spark/blob/v2.4.7/core/src/main/scala/org/apache/spark/scheduler/SparkListener.scala)。

| Event | 表示什么、关键字段 | 取证用途与下一步 |
| --- | --- | --- |
| `SparkListenerLogStart` | 日志版本元信息：Spark Version | 核实版本；不是应用执行开始时间 |
| `SparkListenerApplicationStart` | 应用开始：Timestamp、App ID、App Attempt ID、App Name | 确定应用 attempt 和观察起点；manifest 身份须一致 |
| `SparkListenerApplicationEnd` | 应用结束：Timestamp | 与 Start 计算观察耗时；没有成功/失败结果，不能证明 YARN 终态 |
| `SparkListenerJobStart` | Job 提交：Job ID、Submission Time、Stage IDs；Properties.spark.sql.execution.id 可关联 SQL | 先读直接 Job ID 和 Stage IDs，再分别查 JobEnd/Stage；共享 Stage 不独占属于一个 Job |
| `SparkListenerJobEnd` | Job 结束：Job ID、Completion Time、Job Result.Result；JobFailed 可带 Exception | 判断该 Job 观察结果，读异常及后续相关 Job；不直接升级为整个应用的根因 |
| `SparkListenerStageSubmitted` | Stage attempt 提交：Stage Info.Stage ID / Stage Attempt ID、Submission Time、Parent IDs | 与同组 Completed/TaskEnd 查关联；提交不保证最终成功 |
| `SparkListenerStageCompleted` | Stage attempt 结束，成功或失败均可出现：Stage Info.Completion Time / Failure Reason | 核实失败文本和后续 attempt；Completed 名称本身不证明成功，缺失字段保持未知 |

`attempt_id` 是应用 attempt；`stage_attempt_id` 是阶段 attempt；Task Info.Attempt 是 Task 尝试号。`task_id` 匹配 Task Info.Task ID，**不是** Task Info.Index（分区索引）。重试和推测执行可能有同一 Index、不同 Task ID；不要按 Index 冒充直接 Task ID，也不把事件样本计数当作去重分区数。

## Task、executor 与存储

| Event | 表示什么、关键字段 | 取证用途与限制 |
| --- | --- | --- |
| `SparkListenerTaskStart` | Task attempt 启动：顶层 Stage ID / Stage Attempt ID；Task Info 的 Task ID、Index、Attempt、Executor ID、Launch Time、Speculative | 查 TaskEnd；不按时间邻近推断 Job/SQL 归属 |
| `SparkListenerTaskGettingResult` | Driver 开始远程获取 Task 结果：Task Info.Getting Result Time | 关注结果获取阶段；不是 Shuffle Read，也不代表失败。没有顶层 Stage ID，不能假设 stage_id 筛选可命中；可用 task_id |
| `SparkListenerTaskEnd` | Task attempt 结束：Task End Reason、Task Info、可能缺失的 Task Metrics | 查原因、同 Stage 重试及 executor；结束不等于成功，失败 Task 的指标可能为空 |
| `SparkListenerExecutorAdded` | Driver 注册 executor：Executor ID、Timestamp、Executor Info.Host / Total Cores | 查看执行资源进入时点；不能从一条 Added 推出全程并发容量 |
| `SparkListenerExecutorRemoved` | Driver 移除 executor：Executor ID、Timestamp、Removed Reason | 与相关 Task/恢复查故障链；退出原因不足时不能认定 OOM 或节点故障 |
| `SparkListenerBlockManagerAdded` / `SparkListenerBlockManagerRemoved` | BlockManager 加入/离开：Block Manager ID、Timestamp | 查存储服务生命周期；Removed 不等于全部 RDD/Shuffle 数据丢失 |
| `SparkListenerBlockUpdated` | Block 状态更新：Block Updated Info 内的 Block ID、Block Manager ID、Storage Level、Memory Size / Disk Size | 依日志配置可能缺失；内部 executor ID 不被当前直接 ID 提取，按 Event/ref 读取，不能用 executor_id 保证命中 |
| `SparkListenerUnpersistRDD` | 用户取消 RDD 持久化：RDD ID | 是缓存生命周期事实，不独立证明故障；无 rdd_id 查询参数 |
| `SparkListenerEnvironmentUpdate` | 环境/配置更新 | 当前缓存仅保留允许的 Spark Properties 值；其他信息已脱敏，不能补回或视为默认配置 |

Executor/Node 的 Blacklisted、Unblacklisted 及 ForStage 事件表示排除/重新启用调度对象，不能单独证明节点永久不可用。Spark 2.4.7 走通用序列化时使用完整类名，例如 `org.apache.spark.scheduler.SparkListenerExecutorBlacklisted`；字段通常是 `executorId`、`stageId` 等 camelCase，当前直接 ID 筛选不提取这些字段。先核实 inspect 名称，再按 Event/ref 阅读，不能把类名简写或自行转换字段作为合法关联。

## Task End Reason：原因值不是事件名

下列值位于 `SparkListenerTaskEnd` 的 Task End Reason.Reason；用 `task_end_reason` 精确筛选。依据 [TaskEndReason](https://github.com/apache/spark/blob/v2.4.7/core/src/main/scala/org/apache/spark/TaskEndReason.scala)；附加字段名称见 JsonProtocol。

| Reason | 含义 | 应读字段与下一证据 |
| --- | --- | --- |
| `Success` | 该 Task attempt 成功 | Task Info / Task Metrics；仍检查相关 Stage/Job，单个成功不能掩盖页外失败 |
| `FetchFailed` | 获取 Shuffle 数据失败 | Message、Shuffle ID、Map ID、Reduce ID、Block Manager Address；查 Stage 重试、数据提供方和 executor 退出证据，不能直接断言网络/OOM |
| `ExceptionFailure` | Task 执行出现异常 | Class Name、Description、Stack Trace / Full Stack Trace；读具体异常及恢复，不把错误包装当作最初原因 |
| `ExecutorLostFailure` | Task 因执行它的 executor 丢失而失败 | Executor ID、Exit Caused By App、Loss Reason；与 Removed Reason 及外部退出信息核实；不是特定退出码 |
| `TaskKilled` | Task 被终止 | Kill Reason；可能伴随取消或其他 attempt 完成，先查触发背景与 Job 结果 |
| `Resubmitted` | Task 需要重新提交，例如已成功的 Shuffle map 输出丢失 | 查看重执行及恢复；不是用户重新提交整个应用 |
| `TaskResultLost` | Task 结果丢失，需要重执行 | 查结果获取与重试；不能仅凭该值确定存储或网络根因 |
| `TaskCommitDenied` | Task 提交被拒绝 | 内部 Job ID、Partition ID、Attempt Number；不是顶层 Job ID，不能用它直接认定整个 Job 失败 |
| `UnknownReason` | Spark 定义的未知失败原因 | 原因仍未知，查其他事件；与工具的 UNKNOWN 缺失标签分开 |

工具把缺失/无效原因表示为 `UNKNOWN`，它不是 Spark 的 `UnknownReason` 枚举。若厂商也使用字面 UNKNOWN，须回读正文辨别，不能只由原因计数推断字段缺失。没有映射的 Reason 保留原值，不臆造含义。

FetchFailed 的 Map ID、Reduce ID、Shuffle ID 是 Shuffle 坐标，不是当前 Task ID；Block Manager Address 指向数据提供方，Task Info.Executor ID 是运行失败 Task 的 executor，两者可能不同。

## SQL execution 与指标关联

完整事件名和字段依据 [SQLListener](https://github.com/apache/spark/blob/v2.4.7/sql/core/src/main/scala/org/apache/spark/sql/execution/ui/SQLListener.scala)。

| Event | 含义、字段 | 查询与解释边界 |
| --- | --- | --- |
| `org.apache.spark.sql.execution.ui.SparkListenerSQLExecutionStart` | SQL execution 开始：executionId、time、description、details、physicalPlanDescription、sparkPlanInfo | 当前 query 返回前五项，不返回 sparkPlanInfo；description/details 不保证是完整 SQL 原文 |
| `org.apache.spark.sql.execution.ui.SparkListenerSQLExecutionEnd` | SQL execution 结束：executionId、time | 没有成功结果或异常字段；查关联 JobEnd 和外部错误证据 |
| `org.apache.spark.sql.execution.ui.SparkListenerDriverAccumUpdates` | Driver 侧 SQL accumulator 更新：executionId、accumUpdates | 可按 execution_id 取事件；accumulator ID 需结合计划指标元信息解释，不能只看数字认定指标/单位 |

SQL→Job 用 JobStart.Properties.spark.sql.execution.id，拿到顶层 Job ID 后再查 JobEnd。JobEnd 不携带这个 SQL execution ID，直接用 execution_id 筛 JobEnd 会漏掉它。SQL 计划指标并不都是 Task Metrics 中的字段；当前缺少映射时明确证据缺口。

## 原始 Task Metrics 与单位

字段来源为 JsonProtocol；含义依据 [TaskMetrics](https://github.com/apache/spark/blob/v2.4.7/core/src/main/scala/org/apache/spark/executor/TaskMetrics.scala) 和 [ShuffleWriteMetrics](https://github.com/apache/spark/blob/v2.4.7/core/src/main/scala/org/apache/spark/executor/ShuffleWriteMetrics.scala)。不要把所有带 Time 的原始字段都当毫秒。

| 原始位置 | 单位/含义 | 取证注意 |
| --- | --- | --- |
| Task Info.Launch Time / Finish Time | 时间戳 ms | 有效结束时间减开始时间；0/缺失/逆序结束时间不构造耗时 |
| Task Metrics.Executor Run Time | ms，包含 Shuffle 获取时间 | 不与 Fetch Wait 相加当作耗时拆解 |
| Task Metrics.JVM GC Time | ms，Task 执行期间的 JVM GC 时间 | 高 GC 是核实入口，不单独证明 OOM |
| Task Metrics.Shuffle Read Metrics.Fetch Wait Time | ms，Shuffle 获取等待 | 单一等待值不证明网络故障 |
| Task Metrics.Executor CPU Time / Executor Deserialize CPU Time | ns | 与 ms 指标比较前需换算，不能当墙钟耗时 |
| Task Metrics.Shuffle Write Metrics.Shuffle Write Time | ns | 不与毫秒指标直接比较；当前六项聚合不包含该字段 |
| Task Metrics.Input Metrics.Bytes Read | bytes，外部输入读取量 | 不等于 Shuffle Read |
| Task Metrics.Shuffle Read Metrics.Remote Bytes Read / Local Bytes Read | bytes | 当前 shuffle_read_bytes 两分量均有效才求和；缺分量不是零 |
| Task Metrics.Memory Bytes Spilled / Disk Bytes Spilled | bytes | 表示溢写量，不等于 JVM 堆占用或最终文件体积 |

性能工具的六项输出固定为 duration_ms、executor_run_time_ms、jvm_gc_time_ms、input_bytes、shuffle_read_bytes、shuffle_fetch_wait_ms，来自有效 Success TaskEnd 样本；其抽样、缺失和 nearest-rank 口径见 Skill 的性能分支。其他原始指标只能在当前返回的 Task Metrics 中阅读，不能发明 order_by 值或额外聚合工具。

## 是否实际写入日志

依据 [EventLoggingListener](https://github.com/apache/spark/blob/v2.4.7/core/src/main/scala/org/apache/spark/scheduler/EventLoggingListener.scala)：ExecutorMetricsUpdate 回调不写入 event log；BlockUpdated 取决于 block 更新日志配置。能在类定义中找到某事件，不保证日志中存在它，也不保证缓存保留其所有字段。

未见事件、没有结束事件、遗漏的类型列表或被裁剪正文都属于证据范围限制。引用使用当前脱敏 snapshot.sha256 和物理行号，不能指向原始 ZIP、别的 attempt 或刷新后的日志。
