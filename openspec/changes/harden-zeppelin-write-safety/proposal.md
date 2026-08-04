## Why

The Zeppelin write-safety gate treats every SQL write keyword (including `DROP` and `TRUNCATE`) uniformly through a single database allowlist. Because `tmp_dc_ep` is allowlisted, `DROP TABLE tmp_dc_ep.my_table` is currently accepted - the gate cannot forbid destructive DDL even on an approved database. The gate is also inlined inside `add_paragraph`, coupling safety policy to use-case orchestration and making it impossible to extend or reorder checks independently.

## What Changes

- Add a SQL forbidden-keyword blacklist: statements whose leading keyword is in `sql_forbidden_keywords` (default `DROP`, `TRUNCATE`) are rejected with `INVALID_INPUT` **regardless of target database**, checked before the database allowlist. DML and `CREATE`/`ALTER` remain governed by the existing `tmp_dc_ep` database allowlist (Plan A).
- Decouple the write-safety gate from `add_paragraph` into a mandatory, configurable, multi-level `ParagraphSafetyHook` injected into the application service. The interpreter allowlist, SQL blacklist, SQL database allowlist, and sh command allowlist become ordered, single-responsibility checkers; `add_paragraph` keeps only input validation and calls `hook.enforce()` as the sole path to the gateway.
- Add the `sql_forbidden_keywords` setting (env `ZEPPELIN_SQL_FORBIDDEN_KEYWORDS`), validated and overridable like the other safety settings.

## Capabilities

### New Capabilities
<!-- None - this change hardens an existing capability. -->

### Modified Capabilities
- `zeppelin-notebook-tools`: the write-safety gate requirement gains a forbidden-keyword blacklist ahead of the database allowlist, a new `sql_forbidden_keywords` setting, and an enforced multi-level hook as the gating mechanism.

## Impact

- `src/mcp_stdio/plugins/zeppelin/config.py` - new `sql_forbidden_keywords` field + validator.
- `src/mcp_stdio/plugins/zeppelin/models.py` - new `validate_sql_forbidden_keywords` pure function.
- `src/mcp_stdio/plugins/zeppelin/safety.py` - new module: `ParagraphChecker` protocol, four checkers, `ParagraphSafetyHook` composite, `build_default_safety_hook` factory.
- `src/mcp_stdio/plugins/zeppelin/service.py` - `add_paragraph` drops inline gating; depends on injected `ParagraphSafetyHook`.
- `src/mcp_stdio/plugins/zeppelin/plugin.py` - composition root builds the hook from settings and injects it.
- Tests: new `test_safety.py`; updates to `test_models.py`, `test_service.py`, `test_config.py`; architecture contract tests pass unchanged (`safety.py` is not in the infrastructure import set).
