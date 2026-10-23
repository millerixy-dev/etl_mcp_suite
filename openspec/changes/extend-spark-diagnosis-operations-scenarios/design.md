## Context

见 proposal.md。现有 `spark-diagnosis` 主文件已规定固定事件快照、Task/Stage/Job 恢复检查、性能分布和容器日志取证；`event-search.md` 与 `container-logs.md` 是按需参考。本次只组织这些既有能力，不增加服务端接口。工作区已有另一变更留下的未提交日志取证内容，修改必须叠加保留。

## Goals / Non-Goals

**Goals:** 用户以运维现象提问时，Agent 能选取最相关场景、形成多个可证伪的根因假设、按证据能力排序查询，并区分局部故障、最终失败、业务结果与证据缺口。

**Non-Goals:** 不让场景表成为自动根因分类器；不设固定阈值或仅凭事件名下结论；不取得队列、节点、存储和业务数据的当前 MCP 未提供的事实。

## Decisions

1. **主文件只放路由，场景细节放 `references/operations-scenarios.md`。** 用户问作业运维表现、候选原因或排查顺序时按需读取。相比把完整矩阵塞进主文件，这减少常规单事件诊断的上下文；相比另建 Skill，复用已建立的快照和引用纪律。
2. **两个独立目录通过稳定 S/R 编号关联。** 第一部分列可观察现象（提交、排队、执行、重试、终态、产出、可观测性）；第二部分列候选根因及对应现象。每条根因写首查证据、可支持它的事实、重要反证/歧义和外部证据缺口。编号是文档导航，不进入 MCP 结果，也不是模型的诊断标签。
3. **按“观察 → 假设 → 验证/反证 → 影响和恢复 → 结论”使用目录。** 同一表现可由多个原因引起；先查直接 ID、时间范围和全体计数，再取关键日志，不批量抓取所有 Executor。已恢复的 Task/Stage 故障不自动解释应用终态失败；输出正确性需要业务证据。缺 YARN/存储/调度侧证据时保留 `inconclusive`。
4. **只引用 Spark 2.4.7 已核实语义。** Stage/Task 指标、GC 和内存工作集依据 [Spark 2.4.7 tuning](https://github.com/apache/spark/blob/v2.4.7/docs/tuning.md)；动态 Executor 依据 [job scheduling](https://github.com/apache/spark/blob/v2.4.7/docs/job-scheduling.md)；YARN 容器日志依据 [running on YARN](https://github.com/apache/spark/blob/v2.4.7/docs/running-on-yarn.md)；事件日志覆盖依据 [monitoring](https://github.com/apache/spark/blob/v2.4.7/docs/monitoring.md)。精确 Event/Reason 和当前投影以 `references/spark-events-2.4.7.md` 及实际工具 schema 为准。
5. **测试文档关系而非措辞。** 单元测试验证主文件链接可解析、每个场景/根因编号唯一、交叉引用都存在，并让每个场景至少有一个候选根因。再人工核对 3 类离线场景：排队无 Task、FetchFailed 后恢复、JobSucceeded 但 Driver 退出；不访问真实集群。

本变更无新增配置项、工具、参数、结果形状或上游端点，故无新增配置字段表、启动示例、接口参数表及结果 JSON；原有接口合同保持在现有 capability spec 和 Skill 参考中。

## Risks / Trade-offs

- **场景清单被误当确定诊断规则** → 明确每项是候选，列出反证和能力缺口，结论沿用现有证据标签。
- **文档扩大后加载成本增加** → 主 Skill 只保留触发路由，详细矩阵按需读。
- **YARN、业务输出和存储事实不可见** → 只说明需要的外部证据，不模拟接口或暗示已核实。
- **与现有未提交改动交叠** → 仅增量编辑主 Skill、测试和 README，审查本次 diff，不回滚或提交其他改动。

## Migration Plan

更新仓库中的规范 Skill 和 README；安装脚本已有递归复制机制，用户之后按既有安装流程更新其客户端副本。回滚本次变更只需移除新增参考与主 Skill 路由，不改变 MCP 服务端或数据。
