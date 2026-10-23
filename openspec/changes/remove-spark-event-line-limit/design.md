## Context

The acquisition adapter checks both source and sanitized record lengths against MAX_LINE_BYTES; the shared offline reader imports the same constant. The old download capability remains active rather than in main specs. Its resource requirement and design are synchronized alongside this additive delta, preserving other pending edits.

## Goals / Non-Goals

Honor the user-approved aggregate-only policy in both adapters, without changing MCP contracts, JSON parsing, redaction, identity checks, CRC, hashes, member limits or output projection budgets. No additional runtime option or dependency.

## Decisions

Use `stream.readline(max_bytes - total_source + 1)` during extraction and `stream.readline(settings.max_bytes - size + 1)` during offline reading. Check the updated total before JSON parsing. At an exact budget boundary the next one-byte read distinguishes EOF from overflow. Total acquisition input accounting spans all members. Sanitized output continues to have its separate aggregate check, including when redaction increases bytes.

Remove MAX_LINE_BYTES and all three per-record checks. An arbitrary larger constant would repeat the compatibility problem; unbounded readline would lose early overflow protection. Retain sequential parsing and bounded tool result text. The common verified reader serves inspect/query and performance tools.

## Configuration and interfaces

No settings or tool contracts are added. The affected existing setting is:

| Field | Type | Default | Range | Required |
| --- | --- | --- | --- | --- |
| settings.max_bytes | int | 268435456 | 1–1073741824 inclusive | No |

Minimal file example, saved as `/tmp/spark-budget.yaml` for a deployment that allows anonymous access:

```yaml
version: 1
plugin: spark
settings:
  history_server_url: https://history.example.invalid
  cache_dir: /var/tmp/mcp-spark-l3
  max_bytes: 268435456 # Separate ZIP, expanded input and saved JSONL totals.
```

```sh
uv run --locked mcp-stdio --plugin spark --config /tmp/spark-budget.yaml
```

| Environment variable | Field |
| --- | --- |
| SPARK_HISTORY_SERVER_URL | settings.history_server_url |
| SPARK_CACHE_DIR | settings.cache_dir |
| SPARK_MAX_BYTES | settings.max_bytes |

```sh
SPARK_HISTORY_SERVER_URL=https://history.example.invalid \
SPARK_CACHE_DIR=/var/tmp/mcp-spark-l3 SPARK_MAX_BYTES=268435456 \
uv run --locked mcp-stdio --plugin spark
```

Existing fetch, inspect/query and metrics parameter tables and named result JSON examples are incorporated from `../add-spark-event-log-download/design.md`, `../add-spark-event-log-inspection/design.md` and `../archive/2026-10-14-add-spark-performance-metrics/design.md`. They remain unchanged; this change introduces no interface or endpoint. The previously verified upstream sources for the same ZIP API and event format are recorded in download design section 2; this local byte-budget adjustment makes no new upstream assumptions.

## Risks / Trade-offs

Large JSON records create higher transient memory usage (decoded strings, parsed objects, redaction and serialization copies). Aggregate byte limits are not RSS limits. This is the user's accepted MVP trade-off; continue to bound reads by the remaining budget and avoid loading the whole file at once.

## Migration

Restart the MCP child process to load changed code. Existing valid evidence needs no migration. Previously rejected acquisitions can be retried. Rollback restores the prior record cap and may reject large records again.
