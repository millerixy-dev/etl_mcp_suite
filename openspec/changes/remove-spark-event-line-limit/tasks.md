## 1. Aggregate-only event budgets

- [x] 1.1 RED: add synthetic tests for >8 MiB source/output records, offline inspect/query, exact budget/EOF, aggregate input and redaction-growth output overflow. GREEN: remove the fixed record cap in both readers and bound each read by remaining total + 1. REFACTOR: remove unused imports, synchronize README/architecture documentation. Verify with `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark tests/contract/test_spark_stdio.py`, then independent review.

## 2. Completion verification

- [x] 2.1 Run fresh complete unit/contract suite, lint, type check, package build, console smoke, `openspec validate --changes --strict` and `openspec validate --specs --strict`; record results and any live-test limitations before marking complete.
