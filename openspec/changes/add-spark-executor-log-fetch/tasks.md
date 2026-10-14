## 1. 先完成真实 stdout 验证

- [x] 1.1 复用既有Spark认证和文本脱敏，先运行`PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_knox_auth.py tests/unit/plugins/spark/test_files.py`；临时解析程序先用合成stdout/登录HTML/无换行EOF样例验证识别与脱敏，再向用户给定的Driver JobHistory stdout地址做有界真实GET。仅在认证、真实stdout解析、私有文件发布、独立SHA-256/秘密缺席验证全部通过后完成；把确认的HTML/状态/范围语义和准确结果记录在本change的verification.md。本任务不注册新MCP工具、不修改生产代码；受阻保持未完成。

## 2. 基于真实验证交付最小工具（RED → GREEN → REFACTOR）

- [x] 2.1 先为严格五项输入、12项结果、两项新增配置、旧配置兼容、新ToolOperation/安全identifier及fake gateway service写失败测试并确认RED，再实现最小契约/服务。验证：`PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_executor_logs.py tests/unit/plugins/spark/test_config.py tests/unit/core/test_errors.py tests/contract/test_architecture.py`。
- [x] 2.2 基于1.1确认的HTML形态和部署路径，先写Driver/Executor URL定位、缺URL不自动刷新、容器/attempt一致、同网关受控跳转、上游allowlist、Cookie/Basic范围、HTML200错误、固定字节上限和EOF末行保留的失败测试；实现一个聚焦的日志adapter，复用认证/脱敏而不预建双版本兼容层。验证：`PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_executor_logs.py tests/unit/plugins/spark/test_knox_auth.py tests/unit/plugins/spark/test_http_client.py tests/unit/plugins/spark/test_files.py`；eventlog仍拒绝redirect。
- [x] 2.3 先写私有权限、symlink/traversal、原子发布、hash/manifest、一份deadline和取消清理、共享目录锁及已实现Spark能力精确工具并集的stdio失败测试，再接入最小证据保存和composition；详细溯源留manifest，不增缓存状态。验证：`PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark tests/contract/test_spark_stdio.py tests/contract/test_architecture.py tests/unit/test_registry.py`。

## 3. 文档与发布验证

- [ ] 3.1 用配置例子测试验证文件/env模式，添加stdout/stderr调用和两项配置的YAML/JSON示例，同步README.md、README.zh-CN.md、docs/architecture/runtime-flow.md和modules.md。验证：`PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_config.py tests/unit/test_package.py`及按design逐项核对输入/结果/网关边界。
- [ ] 3.2 为明确opt-in的真实stdio日志测试写门禁失败测试，再实现integration：仅在`MCP_STDIO_SPARK_EXECUTOR_LOG_INTEGRATION=1`及application/attempt/executor、日志网关/认证环境齐备时运行。验证：`PYTHONPATH=src uv run --locked pytest -q tests/integration/test_opt_in.py`；具备环境时另运行`PYTHONPATH=src uv run --locked pytest -m integration tests/integration/test_spark_executor_logs.py`，否则记录skipped。
- [ ] 3.3 整变更审查后fresh验证：`uv sync --locked`、`PYTHONPATH=src uv run --locked pytest -q`、`uv run --locked ruff check .`、`uv run --locked pyright`、`uv build`、`PYTHONPATH=src uv run --locked mcp-stdio --help`、不可达localhost配置的Spark EOF smoke；`openspec validate add-spark-executor-log-fetch --strict`、`openspec validate --changes --strict`、`openspec validate --specs --strict`、`git diff --check`。verification.md记录准确命令/结果及live通过或skipped；全部门禁通过才完成tool交付。
