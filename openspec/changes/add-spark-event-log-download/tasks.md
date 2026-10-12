## 1. 最小契约

- [x] 1.1 RED → GREEN → REFACTOR：先测试五项 settings/可选 Cookie 的文件及 env-only 配置、三参数输入、SparkEventLogFetchResult/SparkEventLogFile 和安全错误，再实现 config/models/gateway 与共享 operation/identifier 最小扩展；验证 `uv run --locked pytest tests/unit/plugins/spark/test_config.py tests/unit/plugins/spark/test_models.py tests/unit/core/test_errors.py`。无 Snapshot、cache_policy 或新增错误类别。

## 2. 下载与文件处理

- [x] 2.1 RED → GREEN → REFACTOR：用 mock transport 先验证两条 GET/mount、环境 Cookie、TLS/CA、无重定向/环境代理、HTML-200/状态安全映射、实际字节上限、超时与响应关闭，再实现 lazy HTTP adapter 和既有 wire-log suppression；验证 `uv run --locked pytest tests/unit/plugins/spark/test_http_client.py`。不自动登录或重试。
- [x] 2.2 RED → GREEN → REFACTOR：用合成 ZIP 先验证 CRC、普通安全 basename、固定成员/行及 max_bytes 上限、JSONL/LogStart/ApplicationStart 身份、single/all/null attempts、缺 ApplicationEnd 允许和坏尾行拒绝，再实现标准 ZipFile 逐成员读取；验证 `uv run --locked pytest tests/unit/plugins/spark/test_files.py -k 'archive or identity or record or limit'`。不写 ZIP 格式解析器或修复算法。
- [x] 2.3 RED → GREEN → REFACTOR：先用合成秘密验证递归字段/字符串、Cookie、URL、EnvironmentUpdate 固定白名单脱敏，以及行序、数值和源/输出摘要，再实现流式 JSONL 输出；验证 `uv run --locked pytest tests/unit/plugins/spark/test_files.py -k 'redact or digest'`，再运行整个 test_files.py。无脱敏策略框架或原始 ZIP 持久化。
- [ ] 2.4 RED → GREEN → REFACTOR：先测试私有目录/根锁、单下载目录+manifest、整目录 rename、失败/取消清理、exact source/selection 复用、hash 损坏检测与 refresh 新目录，再实现最小本地保存/lookup；验证 `uv run --locked pytest tests/unit/plugins/spark/test_cache.py`。不实现 owner marker、对象库、去重、TTL、配额、GC 或强杀恢复。

## 3. 接入 MCP

- [ ] 3.1 RED → GREEN → REFACTOR：用 fake gateway 先验证输入拒绝、默认 lookup 命中/未命中、refresh 跳过 lookup、原下载时间、结果/错误和总 deadline，再实现 service；验证 `uv run --locked pytest tests/unit/plugins/spark/test_service.py`，服务不得导入 HTTP、文件实现或 MCP。
- [ ] 3.2 RED → GREEN → REFACTOR：先验证唯一工具的精确 schema、安全序列化、插件资源关闭、registry/CLI 和 import boundaries，再接入 tools/plugin、固定 spark 注册及类型/help；验证 `uv run --locked pytest tests/unit/plugins/spark/test_tools.py tests/unit/plugins/spark/test_plugin.py tests/unit/test_registry.py tests/unit/core/test_bootstrap.py tests/contract/test_architecture.py`。装配不增加网络启动行为。
- [ ] 3.3 RED → GREEN → REFACTOR：先通过 stdio/mock transport 验证一次下载→文件可读→跨会话命中、失败输出、EOF 关闭、protocol-only stdout 与 redacted stderr，再补齐调用链；另沿用现有 opt-in gate 提供一个真实下载测试，缺环境跳过；验证 `uv run --locked pytest tests/contract/test_spark_stdio.py tests/contract/test_subprocess_smoke.py tests/integration/test_opt_in.py`。传输/文件细节由上面的单元测试负责，不复制完整测试矩阵。

## 4. 文档与验收

- [ ] 4.1 同步 README.md、README.zh-CN.md、Spark YAML/JSON 配置及 MCP host/env-only 示例、两份 docs/architecture 文档、AGENTS.md 插件范围；说明可信 CA、环境 Cookie、host timeout、JSONL 生成时机/脱敏、缓存不保证最新性、refresh 和用户清理；以 `uv run --locked pytest tests/unit/plugins/spark/test_config.py` 检验配置示例并对照 design/specs。示例不含真实主机、日志或秘密。
- [ ] 4.2 做任务范围与整变更审查后执行 fresh verification：`uv sync --locked`、`uv run --locked pytest`、`uv run --locked ruff check .`、`uv run --locked pyright`、`uv build`、`uv run --locked mcp-stdio --help`，以及临时缓存/不可达源的 Spark console EOF smoke（不联网）；运行 `openspec validate add-spark-event-log-download --strict`、`openspec validate --changes --strict`、`openspec validate --specs --strict`。真实测试仅在 `MCP_STDIO_SPARK_INTEGRATION=1`、`MCP_STDIO_SPARK_APPLICATION_ID`、可选 `MCP_STDIO_SPARK_ATTEMPT_ID` 和部署 SPARK 配置/秘密齐备时运行 `uv run --locked pytest -m integration tests/integration/test_spark_server.py`；否则记录 skipped。本 change 的 verification.md 保存实际命令/结果，必需检查通过才完成。

以上十项为唯一实现清单。严格按任务依赖执行 TDD，不为已后置能力补建接口、配置或测试。

