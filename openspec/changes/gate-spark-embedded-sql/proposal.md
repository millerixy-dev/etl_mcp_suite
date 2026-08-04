## Why

The Zeppelin write-safety gate only inspects SQL for interpreters whose name contains `sql`. Execution-capable interpreters such as `spark` can run arbitrary Scala/Python code, including `spark.sql("INSERT OVERWRITE TABLE dwd_dc_ep...")` calls that execute Hive DML/DDL against non-allowlisted databases. Because the `spark` interpreter name does not contain `sql`, both the forbidden-keyword and write-target checkers skip it entirely, and even if they ran, the body's leading keyword is `spark` (not `INSERT`), so the embedded SQL inside the string argument is never inspected. An agent successfully wrote to `dwd_dc_ep` via this vector, bypassing the `tmp_dc_ep`-only write allowlist.

## What Changes

- Add an embedded-SQL extraction step to the paragraph safety gate: for every interpreter, scan the paragraph body for `sql("...")` / `spark.sql("...")` / `sqlContext.sql("...")` string-literal arguments, extract the SQL text, and validate each extracted statement through the existing forbidden-keyword blacklist and write-target allowlist.
- Introduce a new `EmbeddedSqlChecker` in the safety hook chain (after the SQL-interpreter checkers, before the sh checker) that performs this extraction-and-validate step for all interpreters as defense-in-depth.
- Add a pure `extract_embedded_sql(body) -> list[str]` function in `models.py` that handles triple-quoted (`"""..."""`), double-quoted (`"..."`), and single-quoted (`'...'`) string arguments to any `sql(` call matched at a word boundary.
- Document the inherent limitation: interpolated strings (`s"...$var"` in Scala, `f"...{var}"` in Python) and dynamically constructed SQL are not statically extractable and remain outside the gate's coverage.

## Capabilities

### New Capabilities
<!-- None - this change closes a bypass in an existing capability. -->

### Modified Capabilities
- `zeppelin-notebook-tools`: the "Gate paragraph content" requirement gains an embedded-SQL scanning rule that extracts SQL from `sql()` string arguments in any interpreter and applies the same forbidden-keyword + write-target checks, closing the `spark`-interpreter bypass.

## Impact

- `src/mcp_stdio/plugins/zeppelin/models.py` - new `extract_embedded_sql` pure function + companion regexes.
- `src/mcp_stdio/plugins/zeppelin/safety.py` - new `EmbeddedSqlChecker`; `build_default_safety_hook` inserts it into the chain.
- `src/mcp_stdio/plugins/zeppelin/service.py` - no change (hook injection unchanged, new checker is transparent to the service).
- `src/mcp_stdio/plugins/zeppelin/plugin.py` - no change (hook factory signature unchanged).
- Tests: new unit tests for `extract_embedded_sql` and `EmbeddedSqlChecker`; updated contract/service tests for the `spark.sql()` bypass scenario; architecture tests pass unchanged.
