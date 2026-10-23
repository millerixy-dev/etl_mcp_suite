# Review: aggregate-only Spark event budgets

Base: `43765dc413c3ba4c7b287f41e547ccda63ce8782` (HEAD). Target: scoped working-tree changes. Read-only repository review; no tests were run and no repository files were changed.

## Scope and evidence

Reviewed the remove-spark-event-line-limit design, tasks, micro-plan and both capability deltas; the working-tree diff and surrounding code in files.py and inspection_reader.py; all nine parametrized cases initially in test_event_budgets.py, then re-reviewed their final move into test_files.py and test_inspection.py; both README additions and architecture additions. The move preserves all assertions and removes the cross-module private helper import. The micro-plan file list is synchronized. Traced inspection/query and both metrics functions to VerifiedEventLogReader.read. Checked the intentionally synchronized download resource requirement and design sentence; excluded the unrelated preexisting download specification changes and executor work.

The parent reports RED with two old-cap failures and seven passes, then GREEN with nine passes, followed by 462 passing Spark tests before the test-only relocation. This report does not independently assert test execution or completion of broader verification.

## Strengths

- The implementation removes exactly the three independent per-record checks and the unused constant/import. No new option, dependency, schema, or architecture change is introduced.
- Both readers request remaining aggregate budget plus one byte, update accounting and reject overflow before JSON parsing. The counter invariant keeps the requested read size positive. An exact-limit file gets a one-byte EOF probe; an additional byte produces a safe failure.
- Acquisition source and sanitized output counters remain outside the member loop, preserving archive-wide aggregation. Output overflow is checked before writing. Existing identity checks, CRC-triggering EOF reads, hashing and event counts remain in place.
- Offline inspection, query, stage metrics and task distribution use the same verified reader. Its initial file-size check and final metadata/hash/count checks remain intact; visitor accumulation does not yield a successful result before verified EOF.
- Tests cover a source and serialized output record above 8 MiB, source/output exact boundaries with and without a source final newline, cross-member source overflow, overflow before parsing an invalid tail, redaction growth, large offline query projections, and offline total-boundary behavior. The positive large record preserves source/output digest and record count checks. README and architecture descriptions match the change and disclose transient memory costs.

## Issues

### Critical

None found in scope.

### Important

None found in scope.

### Minor

1. `openspec/changes/remove-spark-event-line-limit/superpowers-plan.md:19` names the shared API as `VerifiedEventReader.scan(...)`, but the actual existing API is `VerifiedEventLogReader.read(...)` in inspection_reader.py. This is only a stale plan reference; implementation and metrics wiring use the correct API. Correcting the reference keeps the implementation source documents navigable and avoids suggesting a nonexistent interface.

## Existing limitation / follow-up

The parent reports that a contiguous 8 MiB `x` string exposed quadratic work in the existing `_USERINFO` redaction regex (`files.py:37`), and changed the size fixture to whitespace-separated `node ` text. Code inspection confirms that the regex itself is unchanged by this diff and that checkpoints occur between records, not inside synchronous regex execution. The size fixture still exercises removal of the byte cap, but it does not establish acceptable processing time for arbitrary large strings. Preserve the planned disclosure and track the redaction performance/deadline limitation separately; this review did not reproduce or benchmark it and does not classify it as a newly introduced code defect.

## Assessment

Ready to proceed with completion verification: **Yes**. No blocking implementation issue was found. The aggregate-only policy and shared offline behavior match the approved requirement. Correct the minor plan API reference and finish the fresh full verification required by task 2.1 before claiming the overall change complete.

Controller follow-up: corrected the micro-plan reader name to VerifiedEventLogReader.read; no production change required.
