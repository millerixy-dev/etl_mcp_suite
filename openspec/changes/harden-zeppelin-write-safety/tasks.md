## 1. Domain forbidden-keyword rule

- [x] 1.1 Add `validate_sql_forbidden_keywords(body, forbidden_keywords)` pure function to `models.py` with unit tests (TDD): reject `DROP`/`TRUNCATE` regardless of database, allow `INSERT`/`CREATE`/`ALTER`, multi-statement detection, case-insensitive leading keyword, `SELECT` unaffected.

## 2. Configuration

- [x] 2.1 Add `sql_forbidden_keywords` field to `ZeppelinSettings` (default `("DROP", "TRUNCATE")`) with validator (uppercase normalization, `[A-Z][A-Z_]*` syntax, duplicate rejection) and `ZEPPELIN_SQL_FORBIDDEN_KEYWORDS` env override, with config tests (TDD).

## 3. Safety hook module

- [x] 3.1 Create `safety.py` with the `ParagraphChecker` protocol and four checker implementations (`InterpreterAllowlistChecker`, `SqlForbiddenKeywordChecker`, `SqlWriteTargetChecker`, `ShCommandChecker`) with unit tests (TDD).
- [x] 3.2 Add `ParagraphSafetyHook` composite (ordered `enforce`, first reject wins) and `build_default_safety_hook(settings)` factory with unit tests (TDD): verify blacklist runs before whitelist so `DROP TABLE tmp_dc_ep.x` is rejected.

## 4. Service decoupling

- [x] 4.1 Refactor `ZeppelinNotebookService` to accept an injected `ParagraphSafetyHook`, remove the module-level `_gate_paragraph_content` helper and the bare safety config tuples, and call `hook.enforce()` as the sole path to the gateway in `add_paragraph`; update service tests (TDD) to assert the hook is mandatory and not bypassable.

## 5. Composition root

- [x] 5.1 Wire `plugin.py` to build the hook via `build_default_safety_hook(settings)` and inject it into the service; update wiring/contract tests (TDD).

## 6. Final verification

- [x] 6.1 Run the full unit + contract suite, `ruff check`, `pyright`, and strict `openspec validate --changes` and `--specs`; confirm the architecture contract test still passes with `safety.py` present.
