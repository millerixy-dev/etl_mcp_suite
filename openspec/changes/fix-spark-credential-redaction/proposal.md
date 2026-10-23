## Why

Spark 把所有凭证都按 Cookie header 拆分。Basic Base64 以 `==` 结尾时，会把单个 `=` 加入秘密集合，破坏 event log 的 Driver Logs URL、SQL 等证据，导致日志下载在请求前失败。

## What Changes

- 仅在配置层对明确的 gateway_cookie header 提取完整 Cookie 值。
- 用户名、密码、Basic 编码和 HTTP 客户端返回的 Cookie 值始终作为不可拆分的秘密。
- 用合成凭证验证 event log 到 Driver 日志的完整路径及脱敏安全。
- 已发布快照保持不可变；显式 refresh 重新生成证据。

## Capabilities

### New Capabilities
- `spark-credential-redaction`: 按来源解释秘密，避免凭证语法污染诊断证据。

### Modified Capabilities
无。

## Non-Goals

不改变认证、MCP schema、URL 校验、缓存锁、缓存格式或持久文件迁移；不增加依赖。

## Impact

Spark config.py、files.py 及其单元测试；现有调用方继续消费 tuple[str, ...]，无需新增公共参数。
