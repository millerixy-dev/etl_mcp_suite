## 1. Core ToolError explanation field

- [x] 1.1 Add optional `explanation: str | None` to `ToolError` (field + `create` param) and emit it in `to_dict` when non-empty, with core error tests (TDD).

## 2. Zeppelin specific rejection messages

- [x] 2.1 Make `validate_sql_forbidden_keywords`, `validate_sql_write_target`, `validate_sh_command`, and `InterpreterAllowlistChecker` produce messages naming the rule and safe identifier, with model/safety tests (TDD).

## 3. Service propagation

- [x] 3.1 Capture the rejection reason as `explanation` in `add_paragraph` (and the missing-shebang path), update service tests to assert the explanation reaches the tool error (TDD).

## 4. Final verification

- [x] 4.1 Run the full unit + contract suite, `ruff check`, `pyright`, and strict `openspec validate --changes` and `--specs`.
