# Spark 作业运维场景：先现象，后候选根因

适用于仓库当前的 Spark 2.4.7 / YARN 批作业诊断。编号只用于在本参考内导航，不是 MCP 字段、自动分类结果或置信度。先确定用户实际观察范围、application/attempt 和时间，再从现象进入候选根因；同一现象可能由多个原因产生。没有 application ID、事件日志或相关外部证据时，先报告可见边界，不猜测终态。

## 一、现象（表现）

| 编号 | 可观察的表现 | 首个分界问题 |
| --- | --- | --- |
| S01 | 提交失败，未获得 application ID，或应用很快退出 | 是否已有可读取的 application attempt？未获 ID 时当前事件工具不能定位该应用；区分提交端、YARN 接受和 Driver 启动。 |
| S02 | 应用显示运行中，却迟迟没有 Job/Task 开始 | 是否有 ApplicationStart、SQLExecutionStart、JobStart？只有外部状态时不要假设 Driver 已执行用户代码。 |
| S03 | Job 已提交，Task 等待；Executor 为零、偏少或反复变化 | JobStart/StageSubmitted 后是否有 TaskStart、ExecutorAdded/Removed？事件只能显示进入的 Executor，不能证明队列为何未分配。 |
| S04 | 大部分 Task 已结束，少数 Task 拖住 Stage | 在同一 Stage attempt 比较完整成功样本的 duration、input、shuffle、fetch wait、GC；先排除重试和缺失指标。 |
| S05 | 多数 Task 或阶段整体偏慢，应用耗时长 | 核实应用观察时间、阶段重叠和阶段外空档；没有可比基准只报告耗时，不宣称退化。 |
| S06 | Task/Stage 反复失败、重试或重算 | 查全体 TaskEnd 原因、后续 Stage attempt、Task Success 与关联 JobEnd，先判定是否恢复。 |
| S07 | Executor 频繁丢失或更替 | 对齐直接 executor ID、移除原因、受影响 Task 与容器证据；动态分配的正常回收与故障分开。 |
| S08 | FetchFailed、Shuffle 获取等待或 Stage 重算 | 区分失败 Task 的执行方与 Shuffle 数据提供方；查后续 attempt 是否成功。 |
| S09 | Job 成功但应用/Driver/调度工作流最终失败，或提交 Job 前退出 | JobSucceeded 只覆盖该 Job；核查 Driver 两条日志流、其他 Job 和外部工作流终态。 |
| S10 | 特定输入、分区或 Task 稳定出现同类异常 | 查 ExceptionFailure 的异常链和明确的 Task/Stage 身份，再与输入范围关联。 |
| S11 | 间歇性超时、连接关闭或读写失败 | 核实操作对象、失败时间和重试结果；连接错误可以是故障后果。 |
| S12 | 应用/Job 显示成功，但输出为空、缺分区或内容异常 | Spark 成功事件不能证明业务正确性；需要输出、输入计数及业务校验。 |
| S13 | History Server、event log 或容器日志缺失，终态不明 | 核查正确 attempt、快照/覆盖范围、日志配置与保留状态；未见事件不等于未发生。 |
| S14 | 与可比历史运行相比明显变慢 | 先确认相同业务范围和可比基准，再比较输入规模、计划、并发、Stage/Task 分布。 |

## 二、候选 root cause 与证伪路径

表中的“支持”表示应寻找的事实，不能跳过反证/歧义与恢复检查。首查列只引用现有 Skill 已声明的事件、性能和容器日志能力；YARN、存储、调度与业务侧证据仅在实际可用且符合请求范围时读取，不发明接口。具体事件字段、筛选和引用方式见 [事件语义](spark-events-2.4.7.md)、[事件搜索](event-search.md) 与 [容器日志取证](container-logs.md)。

| 编号 | 候选根因 | 关联现象 | 首查证据 | 支持条件 | 反证、歧义或能力缺口 |
| --- | --- | --- | --- | --- | --- |
| R01 | 队列容量、配额或集群可用资源不足 | S02、S03、S05 | Job/Stage 已提交却无 TaskStart，ExecutorAdded 时序与数量；若有则查 YARN 分配诊断 | 外部队列/容器证据明确显示资源等待或拒绝，且时间与停滞吻合 | 仅有“零 Executor”不能区分队列、请求配置、启动故障或 Driver 未申请；没有 YARN 证据时不确认。 |
| R02 | Driver/Executor 启动配置、资源请求或依赖包错误 | S01、S03、S07、S09 | 对应 Driver/Executor 容器 stderr/stdout、实际启动异常和配置 | 明确的资源拒绝、类加载/依赖异常或启动错误发生在执行前 | Job 没启动不是证明；无 application ID 或日志时列提交端证据缺口。 |
| R03 | Driver 用户代码在 Job 前失败，或 Driver 资源耗尽 | S01、S02、S09 | Application/SQL/Job 起止事件与 Driver 两条日志流 | Driver 的完整异常链或退出诊断指向具体操作，且没有后续恢复 | 退出码、ApplicationEnd、SQLExecutionEnd 均不独立说明原因或业务成功；Driver 日志若只含包装错误须查另一流。 |
| R04 | 数据源权限、认证或对象可用性问题 | S02、S10、S11、S12 | Job/Task 异常详情及 Driver/Executor 日志中具体操作与对象 | 底层拒绝/认证/找不到对象等异常与该读写操作直接关联 | 权限拒绝可支持操作被拒，不能仅凭堆栈断言哪条策略配置错误；存储侧可用性可能仍需外部证据。 |
| R05 | 脏数据、模式不兼容、UDF 或序列化代码缺陷 | S10、S12 | ExceptionFailure、同分区/Task 尝试与异常链 | 同一操作和输入范围重复触发确定性解析/类型/用户代码异常 | Task ID 是尝试身份，不等于分区 Index；重试后成功或输入范围未证实会削弱确定性判断。 |
| R06 | 数据倾斜或少数分区工作量异常 | S04、S06、S14 | 同一 Stage attempt 的完整 Task 分布、同 Task 的输入/Shuffle/耗时和 refs | 少数 Task 同时承担显著更多数据/计算，慢尾随之出现且没有更强等待/GC 解释 | 单条 top task、缺失数据或仅耗时差距不足以确认；重试/推测样本不能当作去重分区。 |
| R07 | 分区并行度或 SQL 执行策略与数据规模不匹配 | S04、S05、S14 | Job/Stage 的 Task 数、输入/Shuffle 分布、可见物理计划与可比运行 | 计划/分区或输入规模变化与耗时变化吻合，且 Task 证据支持相应瓶颈 | 当前 SQL 计划投影不含全部计划指标；无基准、仅“Task 少”不能直接证明配置错误。 |
| R08 | JVM 堆压力、频繁 GC 或单 Task 工作集过大 | S04、S05、S07 | 同 Task 的 GC/运行时长/数据量与关键 Executor 日志 | 明确 OOM/GC 证据和受影响任务时间线一致 | 高 GC 是候选而非 OOM 证明；容器被杀可能是非堆内存，需退出诊断。 |
| R09 | 容器非堆内存超限或资源管理器终止 | S07、S09 | ExecutorRemoved、ExecutorLostFailure 和可用的 YARN 容器退出诊断 | 退出诊断明确指出内存上限或终止原因，并能对齐受影响身份 | ExecutorRemoved/exit code/启动选项不独立证明 OOM；本 Skill 的事件日志无法测出实际容器峰值。 |
| R10 | Shuffle 文件丢失、磁盘或 Shuffle 服务故障 | S06、S08 | FetchFailed 的数据提供方、Stage 重试、相关 Executor/BlockManager 生命周期和日志 | 提供方/服务/磁盘证据指出数据不可读，后续重算链条吻合 | FetchFailed 本身只证明获取失败，不能独立判定磁盘、服务或网络；检查执行方与提供方是否不同。 |
| R11 | 网络或外部存储服务延迟/故障 | S05、S08、S11 | 同 Task Fetch Wait、异常链及可用的服务侧证据 | 具体连接/读取操作与服务侧故障同时吻合，重试或恢复路径清楚 | 单个等待值、连接关闭或超时可能由 GC、Executor 丢失或服务拥塞引起；缺服务侧证据时保留候选。 |
| R12 | 节点故障、容器抢占或动态分配正常回收 | S07、S08 | ExecutorAdded/Removed 时序、受影响 Task 与 YARN 诊断 | 外部退出原因明确区分节点、抢占和正常回收；关联 Task 影响可见 | 移除事件不等于异常退出；Spark 2.4.7 的动态分配允许空闲 Executor 回收。 |
| R13 | 写出、提交、目标分区或业务参数错误 | S12 | 相关 Job/SQL 事件、Driver 异常、业务输入输出/目标路径校验 | 业务证据明确指出写入目标、提交或参数与预期不符 | JobSucceeded、SQLExecutionEnd 均不证明输出正确；当前 MCP 无通用业务结果读取能力。 |
| R14 | 调度器取消、超时或工作流其他步骤失败 | S09、S11 | 关联 JobEnd、TaskKilled、Driver 日志及可用调度实例终态 | 调度侧明确给出取消/超时来源，与应用时间线和影响范围吻合 | TaskKilled 可由推测执行或其他 attempt 完成触发；Spark Job 成功不等于工作流成功。 |
| R15 | 事件日志未启用、未完整落盘、已清理或选错 attempt | S13 | manifest 的实际 attempts/coverage、ApplicationStart/End、History Server 可用性 | 日志设置、保留/清理或 attempt 身份证据明确解释缺口 | 缺失事件不能证明应用未运行或未失败；日志本身损坏、裁剪和缓存陈旧需分别说明。 |

## 场景使用顺序

1. 用现象定位一至数个 S 编号，先确定观察范围与最小事实；一个问题可能落入多个 S。没有可访问事件快照时只列可用的外部证据与缺口。
2. 从关联 R 中选当前证据可区分的假设，说明本轮查询是为了支持还是排除哪一种原因；沿主 Skill 固定 manifest/attempt/sha256，不因场景表跳过全体计数、直接身份或截断回读。
3. 查后续 Task/Stage/Job 与应用/工作流终态，区分局部故障、恢复、最终失败和业务结果。不要把 `FetchFailed`、`ExecutorRemoved`、高 GC、退出码或单个 JobSucceeded 当作根因或整应用结论。
4. 只有直接证据及关键反证检查足够时报告 supported；缺少所需 YARN、存储、调度或业务证据时报告 inconclusive，并明确下一种证据。没有观察失败时可报告 no_observed_failure，但仍需回答慢作业或结果问题的剩余疑问。

Spark 2.4.7 官方依据：[资源与动态分配](https://github.com/apache/spark/blob/v2.4.7/docs/job-scheduling.md)、[内存与 GC](https://github.com/apache/spark/blob/v2.4.7/docs/tuning.md)、[YARN 容器日志](https://github.com/apache/spark/blob/v2.4.7/docs/running-on-yarn.md)、[事件日志和 History Server](https://github.com/apache/spark/blob/v2.4.7/docs/monitoring.md)、[SQL 性能配置](https://github.com/apache/spark/blob/v2.4.7/docs/sql-performance-tuning.md)。厂商扩展先核实实际版本、事件和工具返回字段。
