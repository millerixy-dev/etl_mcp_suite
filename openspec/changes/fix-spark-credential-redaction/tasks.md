## 1. Correct credential interpretation

- [x] 1.1 RED → GREEN → REFACTOR: add regressions for Basic padding, opaque delimiter-containing credentials, configured Cookie headers and acquired values; update config/files preparation and verify `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark` including real adapter event-to-driver routing through mock HTTP.

## 2. Delivery verification

- [x] 2.1 Run full unit/contract suite, ruff, pyright, build, console smoke and strict OpenSpec validation; refresh application_1783000588461_680191 attempt 1 and retry Driver log via MCP, recording success or exact independent upstream blocker without secrets. Review diff and preserve pre-existing deployment edits.
