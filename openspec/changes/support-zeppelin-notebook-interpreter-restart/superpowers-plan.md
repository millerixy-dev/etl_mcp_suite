# Zeppelin Notebook Interpreter Restart — Per-task Micro-plans

## Global Constraints

- OpenSpec change `support-zeppelin-notebook-interpreter-restart` is the source of truth; tasks run in `tasks.md` order.
- Use Python 3.10-compatible syntax and `uv run --locked` for verification.
- Follow strict RED -> GREEN -> REFACTOR TDD and commit each task separately.
- Preserve opaque setting IDs exactly; do not trim, case-fold, coerce scalars, or apply the paragraph interpreter-name regex.
- Keep paragraph interpreter validation unchanged and default restart permission to deny.
- Do not touch unrelated untracked `.codex` files or introduce network access during configuration validation.

### Task 1: OpenSpec 1.1 — Opaque restart setting IDs in configuration

**OpenSpec task:** `1.1 Following Apply preflight, write and run failing tests for opaque restart IDs (including numeric-leading/reserved characters), exact allowlist comparison, cross-field ID length, no scalar coercion, JSON-array env overrides, and unchanged paragraph interpreter validation; implement the minimal config/model changes and refactor with tests green.`

**Files:**

- Modify: `tests/unit/plugins/zeppelin/test_config.py`
- Modify only if an uncovered model regression requires it: `tests/unit/plugins/zeppelin/test_models.py`
- Modify: `src/mcp_stdio/plugins/zeppelin/config.py`
- Do not modify service, gateway, HTTP, tool, or plugin wiring in this task.

**RED:**

1. Add focused tests proving `restartable_interpreter_settings` preserves IDs such as `2AY6GV7Q3` and `../spark?scope=note#v1`, compares duplicates case-sensitively, rejects empty/control-containing/overlong IDs, and rejects numeric/boolean entries without coercion.
2. Add a cross-field test showing a setting ID longer than a configured `max_opaque_id_chars` is rejected while the same ID is accepted when the bound permits it.
3. Add a plugin-prefixed environment override test using `ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS` and a lower-priority generic override/file value; verify exact JSON-array strings and precedence. Include an invalid scalar override case.
4. Retain or add a model assertion that paragraph interpreter names still reject numeric-leading/reserved syntax while `validate_opaque_id` accepts it.
5. Run `uv run --locked pytest tests/unit/plugins/zeppelin/test_config.py tests/unit/plugins/zeppelin/test_models.py -q` and record the expected failures caused by the existing interpreter regex and list-element coercion.

**GREEN / REFACTOR:**

1. Replace only the restart allowlist conversion/validation path with strict string collection handling. Keep the existing tuple conversion behavior for the other typed collections.
2. Validate each restart ID as a non-empty, control-free opaque string and enforce uniqueness by exact case-sensitive value.
3. Add model-level cross-field validation against `max_opaque_id_chars` so field order and environment/file input paths behave identically.
4. Keep configuration error text fixed and value-free; preserve immutable tuple output and no-network loading.
5. Refactor helpers only where it reduces duplication without changing other setting semantics.

**Verification:**

- Required: `uv run --locked pytest tests/unit/plugins/zeppelin/test_config.py tests/unit/plugins/zeppelin/test_models.py -q`
- Also run: `uv run --locked ruff check src/mcp_stdio/plugins/zeppelin/config.py tests/unit/plugins/zeppelin/test_config.py tests/unit/plugins/zeppelin/test_models.py`
- Commit the task with a focused message and write TDD evidence to the assigned implementation report.
