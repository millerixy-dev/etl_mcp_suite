# Design

## Context

The Zeppelin write-safety gate (delivered by `deliver-zeppelin-plugin-slice`) inspects paragraph bodies inside `add_paragraph` via a module-level `_gate_paragraph_content` helper. It treats every SQL write keyword - `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `LOAD` - uniformly through one database allowlist (`sql_write_allowed_databases`, default `tmp_dc_ep`). Because `tmp_dc_ep` is allowlisted, `DROP TABLE tmp_dc_ep.my_table` and `TRUNCATE TABLE tmp_dc_ep.my_table` are currently accepted. The interpreter allowlist, SQL target check, and sh command check are also inlined in the service alongside use-case orchestration, and the safety configuration is passed into the service constructor as bare tuples.

## Goals / Non-Goals

**Goals:**
- Forbid destructive DDL (`DROP`, `TRUNCATE`) on every database, including approved ones, via a configurable blacklist checked before the database allowlist.
- Decouple the write-safety gate from `add_paragraph` into a mandatory, injectable, multi-level hook so policy is separable from use-case orchestration and independently testable.
- Keep DML and `CREATE`/`ALTER` governed by the existing `tmp_dc_ep` database allowlist (Plan A).
- Make the blacklist configurable with a safe default and env-var override.

**Non-Goals:**
- Gating `run_paragraph`. Content is validated at `add_paragraph` time (where the body is known); `run_paragraph` only executes already-accepted paragraphs. This matches the previously agreed design.
- A blacklist for non-SQL interpreters beyond the existing sh allowlist.
- Archiving `deliver-zeppelin-plugin-slice` or moving the zeppelin spec into `openspec/specs/`.

## Decisions

### 1. New `safety.py` module (application-layer policy)

A dedicated `safety.py` holds the hook abstraction, the checkers, the composite, and a factory. It depends only on `models.py` (pure functions) and the standard library - no `httpx`, `mcp`, or `pyhive`. The architecture contract test (`import_rules.py`) forbids `service.py` from importing `{http_client, plugin, pyhive, tools}`; `safety` is not in that set, so `service.py` may import it. This is a justified split: four checkers plus a protocol and composite are substantial enough to warrant a focused file, and it keeps `service.py` focused on use-case orchestration.

### 2. Multi-level checker chain

```
ParagraphChecker (Protocol)
  check(interpreter: str, body: str) -> None   # raises ValueError on reject

  1. InterpreterAllowlistChecker(allowed)        # migrated from add_paragraph
  2. SqlForbiddenKeywordChecker(forbidden)        # NEW blacklist, any DB
  3. SqlWriteTargetChecker(allowed_databases)     # existing whitelist
  4. ShCommandChecker(allowed_commands)            # existing

ParagraphSafetyHook(checkers)
  enforce(interpreter, body) -> None              # ordered; first reject wins
```

Each checker is a frozen dataclass built from configuration and delegates to a pure function in `models.py`. The composite runs checkers in order; the first rejection terminates the chain. Order is normative: the forbidden-keyword check (gate 2) runs before the database allowlist (gate 3), so `DROP TABLE tmp_dc_ep.foo` is rejected by the blacklist rather than passed by the whitelist.

### 3. Injection and the sole path to the gateway

`ZeppelinNotebookService` takes a `ParagraphSafetyHook` via its constructor instead of the bare `allowed_interpreters` / `sql_write_allowed_databases` / `sh_allowed_commands` tuples. `add_paragraph` keeps only input validation (opaque ID, title, body length, shebang parsing) and then calls `self._safety_hook.enforce(interpreter, body)`. The gateway call follows only after `enforce` returns; there is no code path from `add_paragraph` to the gateway that bypasses the hook. The module-level `_gate_paragraph_content` helper is removed.

### 4. Composition root

`plugin.py` calls `build_default_safety_hook(settings)` to assemble the four checkers from `ZeppelinSettings` in the canonical order and injects the hook into the service. This keeps `plugin.py` thin and the assembly testable in isolation.

### 5. New `sql_forbidden_keywords` setting

`ZeppelinSettings.sql_forbidden_keywords` defaults to `("DROP", "TRUNCATE")`. The field validator normalizes entries to uppercase, validates each against `[A-Z][A-Z_]*`, and rejects duplicates - reusing the existing `_validate_unique_tokens` helper with an uppercase-keyword pattern. Env override `ZEPPELIN_SQL_FORBIDDEN_KEYWORDS` follows the same `<PREFIX>_<FIELD>` precedence as the other settings (highest priority). A new pure function `validate_sql_forbidden_keywords(body, forbidden)` in `models.py` splits the body on `;`, takes each statement's leading keyword, uppercases it, and rejects when it matches the forbidden set; it does not inspect the target database.

### 6. Plan A categorization

- Blacklisted (always rejected): `DROP`, `TRUNCATE`.
- Whitelisted to `tmp_dc_ep`: `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `ALTER`, `LOAD`.

`CREATE` and `ALTER` stay on the database allowlist because temporary-table workflows need `CREATE TABLE tmp_dc_ep.x AS ...` and partition management needs `ALTER`. `DROP` and `TRUNCATE` are irreversible bulk destruction and are forbidden unconditionally.

## Risks / Trade-offs

- [Keyword parsing is statement-prefix based, not a full SQL parser] -> This is the same approach as the existing `validate_sql_write_target`. It covers the leading-keyword form reliably; obfuscated SQL is out of scope for v1 and is mitigated by the interpreter allowlist (only allowlisted interpreters ever reach the gate) and the deny-by-default sh policy.
- [Gating only at `add_paragraph`, not `run_paragraph`] -> Paragraphs created outside this MCP server are not re-checked at run time. Accepted as a known limitation per the agreed design; re-checking would require fetching paragraph content before running, a larger change explicitly deferred.
- [Stricter default rejects previously-accepted `DROP`/`TRUNCATE` on `tmp_dc_ep`] -> This is the intended hardening. Operators who need to allow `DROP` on `tmp_dc_ep` can set `ZEPPELIN_SQL_FORBIDDEN_KEYWORDS` to a narrower list, but the safe default is deny.
