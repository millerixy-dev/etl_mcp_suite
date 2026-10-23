# OpenSpec task 3.1 verification report

Implemented gateway-only `SparkInspectionService`, explicit strict inspect/query MCP signatures, required nullable attempt, per-operation safe errors and original monotonic deadline. Public metadata and details are redacted as a whole, then revalidated as their named closed result model; internal labels/counting/matching are untouched. Runtime retains sole download cache ownership and closes the local inspector before download cleanup, including inspector-close failure. Fetch behavior and direct-test constructor compatibility remain intact.

RED evidence: initial focused service/tools/plugin/stdio/architecture run: 22 expected failures, 26 passed. Separate strict-schema/full-result-redaction/stdio run: 6 expected failures, 4 passed. Lifecycle failure-order regression: 1 expected failure. Causes were missing service, missing tools, missing inspection infrastructure import guards and unsupported lifecycle argument.

Fresh final verification (2026-10-13): every UV invocation used the required same-shell `chflags nohidden .venv/lib/python3.12/site-packages/_editable_impl_hive_cli_mcp_stdio.pth` prefix.

```sh
uv run --locked pytest tests/unit/plugins/spark tests/contract/test_spark_stdio.py tests/contract/test_architecture.py
```

Result: **332 passed in 17.69s**. Includes fake-gateway input/domain-error/timeout/cancellation cleanup; full metadata/vendor credential redaction and fail-closed snapshot identity; exact tools/input/result shapes; actual stdio download → inspect → single-line expanded query → digest mismatch → safe unknown arguments; restart with zero HTTP and unchanged cached evidence; clean stdio shutdown; architecture guards including package aliases. HTTP is mocked, no real credentials or upstream calls.

```sh
uv run --locked ruff check src/mcp_stdio/core/errors.py src/mcp_stdio/plugins/spark/service.py src/mcp_stdio/plugins/spark/tools.py src/mcp_stdio/plugins/spark/plugin.py tests/unit/plugins/spark/test_service.py tests/unit/plugins/spark/test_tools.py tests/unit/plugins/spark/test_plugin.py tests/contract/test_spark_stdio.py tests/contract/import_rules.py tests/contract/test_architecture.py
uv run --locked pyright src/mcp_stdio/core/errors.py src/mcp_stdio/plugins/spark/service.py src/mcp_stdio/plugins/spark/tools.py src/mcp_stdio/plugins/spark/plugin.py tests/unit/plugins/spark/test_service.py tests/unit/plugins/spark/test_tools.py tests/unit/plugins/spark/test_plugin.py tests/contract/test_spark_stdio.py tests/contract/import_rules.py tests/contract/test_architecture.py
```

Results: **All checks passed**; **0 errors, 0 warnings, 0 informations**. Pyright also printed an informational available-version notice. `git diff --check` returned exit 0.

Full change validation/build and task checkbox are controller-owned under task 4.1. Real backend integration is skipped; not requested and no live credentials used. No README/docs/Skill/installer modifications are part of this task's commit.
