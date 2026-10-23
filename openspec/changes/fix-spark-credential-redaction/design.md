## Context

See proposal.md. `SparkSecrets` knows which value is a Cookie header; all downstream readers and adapters only need a tuple of complete secrets. Existing interfaces and deployment settings remain unchanged.

## Goals / Non-Goals

Correct source interpretation at one boundary, retain fail-closed URL validation and existing redaction patterns. No new transport, endpoint, setting, dependency, or migration machinery.

## Decisions

1. Move existing cookie-pair extraction into `SparkSecrets.redaction_values`, limited to `gateway_cookie`. Retain the raw header and trimmed/unquoted full values, including padding. Basic credentials remain whole.
2. `credential_values(values)` only removes empty entries, deduplicates, and sorts longest first. All downstream normalization is idempotent; acquired cookie values never need parsing. Reject the alternative of ignoring short secrets: a short actual password must still be protected.
3. Re-download with explicit refresh. Old evidence cannot be reliably restored from `[REDACTED]`. No parser leniency or in-place edits.

## Internal interfaces

| Interface / Input | Type | Meaning |
|---|---|---|
| SparkSecrets.redaction_values / gateway_cookie | SecretStr or None | Explicit configured Cookie header; extract complete pair values once |
| SparkSecrets.redaction_values / username, password | SecretStr or None | Complete opaque secrets and their combined Basic encoding |
| credential_values / values | tuple[str, ...] | Complete opaque secrets, including acquired Cookie values |

Synthetic result JSON: `{"input": ["opaque==", "opaque==", ""], "normalized": ["opaque=="]}`.

## Configuration compatibility

No configurable fields are added or changed. Existing settings, field tables, environment mappings, tool input tables/result examples and verified upstream sources remain those of `../add-spark-event-log-download/design.md` and `../add-spark-executor-log-fetch/design.md`. This fix only changes internal preparation, not upstream behavior.

File example (credentials remain environment variable names):
```yaml
version: 1
plugin: spark
settings:
  history_server_url: https://history.example/gateway/test/sparkhistory
  cache_dir: /tmp/spark-evidence
secrets:
  gateway_cookie: SPARK_GATEWAY_COOKIE # injected by the host
```
Start: `uv run --locked mcp-stdio --plugin spark --config /path/to/spark.yaml`.

Env-only example, with SPARK_GATEWAY_COOKIE already injected:
```sh
SPARK_HISTORY_SERVER_URL=https://history.example/gateway/test/sparkhistory SPARK_CACHE_DIR=/tmp/spark-evidence uv run --locked mcp-stdio --plugin spark
```

| Field | Type | Default | Range | Required | Environment |
|---|---|---|---|---|---|
| history_server_url | str | none | validated HTTPS URL | yes | SPARK_HISTORY_SERVER_URL |
| cache_dir | str | none | absolute private directory | yes | SPARK_CACHE_DIR |
| gateway_cookie | secret | absent | validated Cookie header | no | SPARK_GATEWAY_COOKIE |

## Risks / Trade-offs

- Existing snapshots remain damaged → refresh the affected attempt; keep historical evidence unchanged.
- Opaque secrets can contain punctuation → redact the complete actual secret, never inferred fragments; retain all generic sensitive-key/header filters.
- Live upstream validation may encounter another independent failure → report it separately from local regression evidence.

## Migration Plan

Restart the MCP process to load corrected code, refresh affected event logs, retry Driver log retrieval. Rollback restores prior code; do not modify evidence in place.
