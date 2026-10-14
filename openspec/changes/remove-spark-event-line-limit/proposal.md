## Why

A valid Spark event can exceed the implementation's fixed 8 MiB JSONL record cap while the whole log remains within max_bytes. A real acquisition failed for this reason. The user approved removing the separate record cap while retaining aggregate budgets and sequential processing.

## What Changes

- Accept input and sanitized records larger than 8 MiB during acquisition and offline scans.
- Bound each read by the remaining configured total budget plus one overflow-detection byte; retain aggregate input/output checks.
- Cover large records, exact budgets and overflow with synthetic regression tests; document the memory trade-off.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `spark-event-log-download`: add aggregate-only event record budgeting to the existing, not-yet-archived capability. Synchronize its original active requirement/design to remove the contradictory 8 MiB statement.
- `spark-event-log-inspection`: apply the same aggregate-only policy to the verified reader shared by inspection, query and metrics.

## Impact

Spark files/inspection_reader adapters, synthetic tests, README and architecture descriptions. No tool schema, dependency, configuration default or persisted format changes. Prior unrelated working-tree edits must be preserved.

## Non-Goals

No new size setting, parser replacement, automatic retry, credential changes, broader memory manager or diagnosis of the downloaded application.
