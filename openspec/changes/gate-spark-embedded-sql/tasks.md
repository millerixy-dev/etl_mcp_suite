## 1. Pure extraction function

- [x] 1.1 Write failing unit tests for `extract_embedded_sql` in `test_models.py`: triple-quoted (`"""..."""`), double-quoted (`"..."`), single-quoted (`'...'`), multiple `sql()` calls in one body, no `sql()` calls (empty list), word-boundary edge cases (`mysql(` / `read_sql(` / `do_sql(` must NOT match; `spark.sql(` / `sqlContext.sql(` / bare `sql(` must match)
- [x] 1.2 Implement `extract_embedded_sql(body: str) -> list[str]` in `models.py` with three compiled regexes (`\bsql\s*\(` + string-literal capture), confirm tests pass

## 2. Embedded SQL safety checker

- [x] 2.1 Write failing unit tests for `EmbeddedSqlChecker` in `test_safety.py`: reject embedded write to non-allowlisted db (e.g. `dwd_dc_ep`), reject embedded forbidden keyword (`DROP`), allow embedded read (`SELECT`), allow embedded write to allowlisted db (`tmp_dc_ep`), no-op when no `sql()` calls present, runs for `spark` interpreter (not skipped)
- [x] 2.2 Implement `EmbeddedSqlChecker` in `safety.py` (calls `extract_embedded_sql` then `validate_sql_forbidden_keywords` + `validate_sql_write_target` on each extracted statement), insert into `build_default_safety_hook` chain between `SqlWriteTargetChecker` and `ShCommandChecker`, confirm tests pass

## 3. Service and contract tests

- [x] 3.1 Write failing service test: `spark` interpreter paragraph with `spark.sql("INSERT OVERWRITE TABLE dwd_dc_ep.x SELECT 1")` returns `INVALID_INPUT` with explanation naming write-target rule and database `dwd_dc_ep`
- [x] 3.2 Write failing service test: `spark` interpreter paragraph with `spark.sql("DROP TABLE dwd_dc_ep.x")` returns `INVALID_INPUT` with explanation naming forbidden-keyword rule and keyword `DROP`
- [x] 3.3 Write service tests for pass-through: `spark.sql("SELECT * FROM tmp_dc_ep.t")` accepted, `spark` code without `sql()` accepted, `spark.sql("INSERT INTO tmp_dc_ep.t VALUES (1)")` accepted; confirm all service/contract tests pass

## 4. Final verification

- [x] 4.1 Run full unit + contract suite, `ruff check`, `pyright`, `openspec validate --changes`, `openspec validate --specs`; all green
