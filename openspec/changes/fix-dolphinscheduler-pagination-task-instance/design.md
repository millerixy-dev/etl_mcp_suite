## Context

`dolphinscheduler` 是一个独立的 MCP stdio 插件进程。其 HTTP adapter 将 DolphinScheduler 3.1.7 REST `Result` 数据转换为 gateway 原始模型；应用 service 验证输入、裁剪结果并生成 MCP 结果；tool adapter 不包含上游解析逻辑。

现场验证表明 `GET /projects/list` 的非分页上游集合没有在 service 层按 `page_no`/`page_size` 切片，而 `get_object(task_instance)` 调用 `GET /projects/{projectCode}/process-instances/{processInstanceId}/tasks` 时被 adapter 归类为 `UNEXPECTED_RESPONSE`。同一只读 endpoint 的安全结构探针确认成功 envelope 的 `data` 是对象，含 `taskList` 数组及 `processInstanceState`，而不是现有 adapter 所假设的顶层数组。本设计修复这两个既有契约违例，不改变工具集合或配置。

上游事实来自 Apache DolphinScheduler 3.1.7 的官方 API 文档及源码：[`ProcessInstanceController`](https://github.com/apache/dolphinscheduler/blob/3.1.7/dolphinscheduler-api/src/main/java/org/apache/dolphinscheduler/api/controller/ProcessInstanceController.java) 的 process-instance task-list 路由、[`ProjectController`](https://github.com/apache/dolphinscheduler/blob/3.1.7/dolphinscheduler-api/src/main/java/org/apache/dolphinscheduler/api/controller/ProjectController.java) 的项目列表路由，以及 [3.1.7 官方文档](https://dolphinscheduler.apache.org/en-us/docs/3.1.7)。

## Goals / Non-Goals

**Goals:**

- 对 non-paged 上游集合稳定地应用 1-based `page_no` 与已校验的 `page_size`，并保留真实 `total_count`。
- 让 task-instance 详情路径接受经测试确认的 3.1.7 task-list `data` 形状，随后仅映射安全 `RawTaskInstance` 字段。
- 以离线 mock-transport 和 service 回归测试保护两个路径，不记录或暴露原始响应、headers 或 token。

**Non-Goals:**

- 不修改配置、认证、timeout、结果字段、工具名称或 workflow 执行行为。
- 不把任意 dict/list 当作合法 task-list 响应；未知 envelope 或缺少可识别条目的响应继续失败关闭。
- 不请求或记录生产数据来制作 fixture。

## Decisions

### 1. 由 service 对非分页集合做确定性页切片

`DolphinSchedulerSchemaService._unpaginated` 已是项目和 workflow 等 non-paged 上游结果的唯一归一化点。它将先计算完整安全集合的 `total_count`，再按 `(page_no - 1) * page_size : page_no * page_size` 取页，最后施加 `max_detail_items`。`page_no`/`page_size` 继续反映请求的有效值；当集合在目标页之后仍有条目，或单页因 `max_detail_items` 被截断时，`truncated` 为真。

选择 service 层而非 HTTP adapter：上游端点本身没有分页参数，adapter 应如实返回其集合，分页政策属于应用层。替代方案是在 adapter 伪造 `RawPage`，会把调用方本地分页与上游传输混在一起，且影响 gateway port 的语义。

### 2. task-instance 详情只支持具名、最小化的 task-list 响应形状

adapter 的 `list_task_instances_of_process` 将通过一个专用的、严格的解析入口处理官方 task-list endpoint 的已验证 `data` 形状：`{"taskList": [<task instance>...], "processInstanceState": <ignored value>}`。回归测试使用最小、无业务值的 fixture 固定 `taskList` 容器和 required `id` 字段；解析后仍通过 `_parse_task_instance` 白名单生成 `RawTaskInstance`，忽略 `processInstanceState` 与未知字段。不识别的顶层类型、缺少或非数组的 `taskList`、或无有效 `id` 的元素继续产生安全的 `UNEXPECTED_RESPONSE`。

选择专用解析而不是放宽通用 `_as_list`：该端点可能与其他 list endpoints 的 `data` 形状不同，专用适配器既保留现有 endpoint 的严格性，也把兼容范围限制在此路由。替代方案是通用地递归搜寻任意列表；它可能接受无关或错误的上游数据，违反 fail-closed 原则。

### 3. 回归测试分层且不连接线上服务

- adapter 测试验证 task-list endpoint 的请求路径、已验证形状、正常解析和未知形状拒绝；
- service 测试验证多页 non-paged 结果的 items、`total_count`、`page_no`、`page_size` 与 `truncated`；
- 现有 MCP contract 测试继续确认结果只含安全字段。

这使 response-shape 兼容性留在外部 adapter，分页策略留在 application service，符合当前 Clean Architecture 边界。

## Configuration Compatibility

本次没有新增或修改可配置项；下表固定修复依赖的现有非敏感设置，避免暗中改变其含义。

| Field | Type | Default | Range | Required |
|---|---|---:|---|---|
| `base_url` | string | - | absolute HTTP(S), 无 userinfo/query/fragment | yes |
| `status_path` | string | `/monitor/masters` | 必须以 `/` 开头且无 query/fragment | no |
| `request_timeout_seconds` | float | `30.0` | `> 0` 至 `300` | no |
| `max_response_bytes` | int | `1048576` | `1` 至 `8388608` | no |
| `max_detail_items` | int | `100` | `1` 至 `1000` | no |
| `default_page_size` | int | `10` | `1` 至 `100` | no |
| `max_page_size` | int | `100` | `1` 至 `200` | no |
| `max_log_bytes` | int | `1048576` | `1` 至 `8388608` | no |

文件配置（本次不改字段；`secrets.token` 只填写环境变量名）：

```yaml
# Start: mcp-stdio --plugin dolphinscheduler --config /path/to/dolphinscheduler.yaml
version: 1
plugin: dolphinscheduler
settings:
  base_url: http://ds-host:12345/dolphinscheduler  # DolphinScheduler context path
  default_page_size: 10                             # list/search 的默认页大小
  max_page_size: 100                                # page_size 硬上限
secrets:
  token: DOLPHINSCHEDULER_TOKEN
```

仅环境变量启动方式：

| Field | Environment variable | Required |
|---|---|---|
| `settings.base_url` | `DOLPHINSCHEDULER_BASE_URL` | yes |
| `settings.default_page_size` | `DOLPHINSCHEDULER_DEFAULT_PAGE_SIZE` | no |
| `settings.max_page_size` | `DOLPHINSCHEDULER_MAX_PAGE_SIZE` | no |
| `secrets.token` | `DOLPHINSCHEDULER_TOKEN` | no |

```bash
export DOLPHINSCHEDULER_BASE_URL=http://ds-host:12345/dolphinscheduler
export DOLPHINSCHEDULER_TOKEN='<provided-outside-config>'
mcp-stdio --plugin dolphinscheduler
```

## Tool Interfaces

### `list_objects`

| Parameter | Type | Required | Default | Notes |
|---|---|---:|---|---|
| `object_type` | enum | yes | - | `project`、`workflow`、`node`、`process_instance` 或 `task_instance` |
| `page_no` | int | no | `1` | 1-based；须为正整数 |
| `page_size` | int | no | `default_page_size` | service 先限制到 `max_page_size` |

代表性结果（`page_no=2,page_size=3`）：

```json
{
  "object_type": "project",
  "items": [{"code": 4, "name": "project-4"}],
  "page_no": 2,
  "page_size": 3,
  "total_count": 4,
  "truncated": false
}
```

### `get_object`

| Parameter | Type | Required | Default | Notes |
|---|---|---:|---|---|
| `object_type` | literal | yes | - | 此修复覆盖 `task_instance` |
| `project_code` | int64 | yes | - | DolphinScheduler 项目代码 |
| `process_instance_id` | int | yes | - | task-instance 的父实例 |
| `task_instance_id` | int | yes | - | 要匹配的 task-instance |

代表性结果：

```json
{
  "object_type": "task_instance",
  "object": {
    "id": 77,
    "name": "safe-task",
    "task_type": "SHELL",
    "state": "SUCCESS",
    "process_instance_id": 5
  }
}
```

## Risks / Trade-offs

- [上游部署的 task-list 响应与 3.1.7 形状不同] → 仅接受测试确认的形状并返回安全 `UNEXPECTED_RESPONSE`；不做宽松递归兼容。
- [请求页超出总数] → 返回空 `items`、真实 `total_count` 和 `truncated=false`，使调用方能决定是否继续翻页。
- [`max_detail_items` 小于有效 `page_size`] → 仍限制输出，并将 `truncated=true`，防止大页绕过结果边界。

## Migration Plan

1. 先落地两个离线 RED 回归测试。
2. 以最小 adapter/service 变更通过测试。
3. 运行相关单测、完整测试、静态检查和严格 OpenSpec 验证。
4. 部署后可用 `list_objects(page_size=3)` 与一个已知 task instance 进行只读验证；若异常，回滚该修复提交即可恢复既有行为。

## Open Questions

无。
