# Spark credential redaction implementation plan

Use superpowers:executing-plans inline. OpenSpec tasks.md is the only completion checklist.

**Goal:** Keep complete secret values private without corrupting URL query delimiters.
**Architecture:** Interpret the explicit Cookie header in SparkSecrets; keep downstream normalization opaque and idempotent.
**Tech stack:** Python >=3.10, uv, existing pytest/httpx mocks. No dependencies or public schema changes.

## Task 1.1 micro-plan

Files: modify src/mcp_stdio/plugins/spark/config.py and files.py; create tests/unit/plugins/spark/test_credential_redaction.py; update test_files.py to consume the explicit configuration boundary.

Interfaces: `SparkSecrets.redaction_values -> tuple[str, ...]`, `credential_values(values: tuple[str, ...]) -> tuple[str, ...]` unchanged. Values are complete opaque strings.

1. Add failing source-semantics tests using only synthetic credentials. Core assertions:
   ```python
   values = credential_values(SparkSecrets(username=SecretStr("demo"), password=SecretStr("password")).redaction_values)
   assert "=" not in values
   assert credential_values(("opaque==",)) == ("opaque==",)
   ```
   Also test quoted multi-pair headers, idempotence, full secret removal, actual `=` password, and real event/log adapters with a mock HTTP transport. The latter downloads an archive with Driver Logs, preserves `?start=-4096` and `left_id=right_id`, then follows the controlled NodeManager/JobHistory path and verifies published redacted text.
2. Run `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_credential_redaction.py`; expect failures for inferred fragments and malformed driver URL, not setup errors.
3. Replace the helper body with `return tuple(sorted({value for value in values if value}, key=len, reverse=True))`. In SparkSecrets, after collecting raw secrets, add:
   ```python
   if self.gateway_cookie is not None:
       for pair in self.gateway_cookie.get_secret_value().split(";"):
           _, separator, item = pair.partition("=")
           if separator and item.strip().strip('"'):
               values += (item.strip().strip('"'),)
   ```
   Keep Basic encoding creation unchanged. Update the old raw-header test to obtain its secret tuple through SparkSecrets.
4. Re-run the focused file, then `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark`. Expect all pass. Review for duplicated parsing, changed security behavior, dependency violations; keep URL guards unchanged.

## Task 2.1 micro-plan

No runtime edits planned. Record verification in this change's verification.md.
Run `PYTHONPATH=src uv run --locked pytest -q`, `uv run --locked ruff check .`, `uv run --locked pyright`, `uv build`, `uv run --locked --no-editable mcp-stdio --help`, `openspec validate --changes --strict`, `openspec validate --specs --strict`, and `git diff --check`. Expected: pass; opt-in live tests skipped unless explicitly configured.

Read the configured spark_dev launcher privately; launch through MCP SDK with a private independent cache to avoid taking another process's lock. Call fetch_spark_event_log with refresh=true for application_1783000588461_680191 attempt 1, then fetch_spark_executor_log for driver stderr. Record safe metadata and independent upstream errors only. Do not rewrite old evidence or expose credentials. Review the final diff, excluding the user's YAML edit.

Self-review: both requirements covered; complete secrets protected, acquired cookies opaque, no minimum-length exemption, old evidence unchanged. No public interface or setting additions.
