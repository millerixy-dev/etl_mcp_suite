## Context

The Zeppelin write-safety gate (`ParagraphSafetyHook` in `safety.py`) inspects paragraph content before it reaches the gateway. The SQL checkers (`SqlForbiddenKeywordChecker`, `SqlWriteTargetChecker`) gate only interpreters whose name contains `sql`. Execution-capable interpreters like `spark` can run arbitrary Scala/Python code, including `spark.sql("INSERT OVERWRITE TABLE dwd_dc_ep...")` that executes Hive DML/DDL. Two compounding gaps allow this to bypass the gate:

1. **Guard mismatch**: `"sql" in interpreter.lower()` is `False` for `"spark"`, so both SQL checkers skip entirely.
2. **Keyword mismatch**: even without the guard, `_SQL_LEADING_KEYWORD` matches `spark` (the body's first token), not `INSERT` (inside the string argument). The SQL is embedded in a string literal that the validator never inspects.

An agent successfully wrote to `dwd_dc_ep` (non-allowlisted) via this vector.

## Goals / Non-Goals

**Goals:**
- Close the `spark.sql("...")` bypass: extract static SQL from `sql()` string-literal arguments in any interpreter and apply the same forbidden-keyword + write-target validation.
- Defense-in-depth: scan ALL interpreters, not just a configurable subset, so new execution-capable interpreters are covered by default.
- Zero new configuration: reuse existing `sql_forbidden_keywords` and `sql_write_allowed_databases`.
- Pure, independently testable extraction function in `models.py`.

**Non-Goals:**
- Full static analysis of Scala/Python code (data-flow, taint tracking).
- Detecting interpolated or dynamically constructed SQL (`s"...$var"`, `f"...{var}"`, `val q = "..."; spark.sql(q)`).
- Blocking SQL via non-`sql()` APIs (e.g., `spark.read.jdbc`, `beeline -e` in `sh`).
- Runtime hooking or Zeppelin interpreter-level permissions.

## Decisions

### D1: Regex extraction via `\bsql\s*\(` word boundary

Match any `sql(` call at a word boundary (`\bsql\s*\(` with `re.IGNORECASE`). This covers `spark.sql(`, `sqlContext.sql(`, `session.sql(`, and bare `sql(` (Zeppelin's built-in helper). It does not match `mysql(`, `do_sql(`, or `my_sql(` because `_` and word characters before `sql` prevent a word boundary.

**Alternatives considered:**
- `spark\.sql\s*\(`: too narrow (misses `sqlContext.sql`, bare `sql`).
- Full AST parsing of Scala/Python: disproportionate complexity for a static-string gate; still cannot resolve interpolation.

### D2: Three string-literal patterns

Extract from three argument forms, tried in order:
1. Triple-quoted: `\bsql\s*\(\s*"""([\s\S]*?)"""` - Scala/Python multi-line.
2. Double-quoted: `\bsql\s*\(\s*"((?:[^"\\]|\\.)*)"` - single-line, with escape handling.
3. Single-quoted: `\bsql\s*\(\s*'((?:[^'\\]|\\.)*)'` - Python single-quote.

Each match's capture group is the raw SQL text. The function returns a `list[str]`; empty list means no embedded SQL found (paragraph passes this checker).

**Why not a unified regex**: triple-quoted strings can contain unescaped `"` and newlines, requiring a separate non-greedy `[\s\S]*?` pattern. Combining into one regex is fragile; three focused patterns are clearer and independently testable.

### D3: New `EmbeddedSqlChecker` in the safety chain

Insert a new `EmbeddedSqlChecker` between `SqlWriteTargetChecker` and `ShCommandChecker`:

```
1. InterpreterAllowlistChecker     (unchanged)
2. SqlForbiddenKeywordChecker      (unchanged - "sql" interpreters only)
3. SqlWriteTargetChecker           (unchanged - "sql" interpreters only)
4. EmbeddedSqlChecker              (NEW - all interpreters)
5. ShCommandChecker                (unchanged)
```

The checker runs for ALL interpreters (no guard). For each `sql()` call found, it calls `validate_sql_forbidden_keywords` then `validate_sql_write_target` on the extracted text. If no `sql()` calls are found, it is a no-op.

**Why all interpreters**: a `spark.sql` interpreter body could also contain `spark.sql()` calls (unusual but possible); scanning it is harmless defense-in-depth. A `sh` interpreter body with `sql("...")` is unlikely but if present, should be gated. The cost is one regex scan per paragraph - negligible.

### D4: Reuse existing validation functions, no new config

`EmbeddedSqlChecker` calls the same pure functions (`validate_sql_forbidden_keywords`, `validate_sql_write_target`) already used by the SQL checkers. No new `ZeppelinSettings` field is needed. The checker is constructed from existing `sql_forbidden_keywords` and `sql_write_allowed_databases` values.

### D5: Extraction function in `models.py`

`extract_embedded_sql(body: str) -> list[str]` is a pure function with no imports beyond `re`. It sits alongside the other validators and is independently unit-testable. The checker in `safety.py` is a thin strategy layer over it, consistent with the existing checker pattern.

## Risks / Trade-offs

- **[Interpolated strings bypass the gate]** `spark.sql(s"INSERT INTO $db.$table")` is not a static string literal; the regex will not extract it. -> **Mitigation**: document the limitation in the spec and in the checker's docstring. The existing interpreter allowlist is the outermost defense - operators can remove `spark` from `allowed_interpreters` if they require a hard block.
- **[False negatives from dynamic construction]** `val q = "..."; spark.sql(q)` stores SQL in a variable. -> **Mitigation**: same as above; static analysis has inherent limits.
- **[False positives from non-SQL `sql()` calls]** A Python paragraph might call `pandas.read_sql("SELECT ...")` or `sqlalchemy.sql("...")`. -> **Mitigation**: the extracted text is validated through the same write-keyword gate; a `SELECT` passes, and only write/forbidden keywords are rejected. The `read_sql` pattern matches `\bsql\s*\(` because `read_sql` has `_sql` - wait, `_` is a word char, so `\b` does not match between `_` and `s` in `read_sql`. `read_sql(` is NOT matched. Only bare `.sql(` and `sql(` at word boundaries match.
- **[Performance]** One regex scan per `add_paragraph` call. -> **Mitigation**: paragraph bodies are bounded to 1 MiB (`max_paragraph_body_bytes`); three compiled regex scans over ≤1 MiB is sub-millisecond.

## Migration Plan

1. Add `extract_embedded_sql` to `models.py` with unit tests.
2. Add `EmbeddedSqlChecker` to `safety.py` with unit tests.
3. Insert the checker into `build_default_safety_hook`.
4. Add contract/service tests for the `spark.sql()` bypass scenarios.
5. No config migration, no breaking changes to existing behavior - paragraphs that previously passed still pass unless they contain embedded SQL targeting non-allowlisted databases (which was the bypass).
6. Rollback: remove the checker from `build_default_safety_hook`; the function and checker remain dead code.

## Open Questions

- None at this time. The design reuses existing patterns and config.
