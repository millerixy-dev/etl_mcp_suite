## Why

已注册的 DolphinScheduler MCP 在真实 3.1.7 服务上暴露了两个与既有契约不一致的行为：`list_objects` 没有按请求分页，且 `get_object(task_instance)` 因详情响应形状解析失败而返回 `UNEXPECTED_RESPONSE`。这使调用方无法可靠地浏览资源或检查任务实例，需以回归测试固定并修复。

## What Changes

- 使 `list_objects` 对所有对象类型一致地应用经校验和上限约束后的 `page_no` 与 `page_size`，并返回与该页相符的 items、`total_count` 和 `truncated`。
- 修复 task-instance 详情查询对 DolphinScheduler 3.1.7 响应的安全解析，使合法目标返回规范化的任务实例属性，而非 `UNEXPECTED_RESPONSE`。
- 为两项真实问题加入不依赖线上服务的回归测试；继续拒绝未知响应形状，并保持安全错误与结果边界。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `dolphinscheduler-scheduling-tools`: 明确 `list_objects` 的页边界语义，并要求 task-instance 详情路径兼容已验证的 DolphinScheduler 3.1.7 任务列表响应形状。

## Non-Goals

- 不增加、删除或重命名 MCP tools。
- 不改变 `start_workflow` 的执行语义、认证方式、配置模型或共享 core。
- 不将不受支持或未知的上游响应降级为成功结果。

## Impact

- 修改 DolphinScheduler 插件的 service 与 HTTP adapter（如根因确认需要），以及对应 unit/contract tests。
- 不新增第三方依赖，不修改 Hive 或 Zeppelin 插件。
- 上游影响限定为已有 DolphinScheduler 3.1.7 REST 调用的结果映射与本地分页。
