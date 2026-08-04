## ADDED Requirements

### Requirement: Explain write-safety rejections
When the write-safety hook rejects a paragraph, the `add_paragraph` tool SHALL return an `INVALID_INPUT` error whose `explanation` concisely names the fired rule and the safe identifier that caused the rejection. The explanation SHALL identify whether the rejection came from the interpreter allowlist, the SQL forbidden-keyword blacklist, the SQL write-target database allowlist, or the sh command allowlist, and SHALL name the relevant safe identifier (interpreter name, SQL keyword, target database, or sh command). The explanation MUST NOT contain credentials, the paragraph body, or unbounded upstream content.

#### Scenario: Explain a forbidden-keyword rejection
- **WHEN** a SQL interpreter paragraph contains `DROP TABLE tmp_dc_ep.my_table` and `sql_forbidden_keywords` includes `DROP`
- **THEN** the tool error explanation names the forbidden-keyword rule and the keyword `DROP`

#### Scenario: Explain a write-target rejection
- **WHEN** a SQL interpreter paragraph contains `INSERT INTO other_db.my_table` and `sql_write_allowed_databases` is `["tmp_dc_ep"]`
- **THEN** the tool error explanation names the write-target rule and the database `other_db`

#### Scenario: Explain an interpreter rejection
- **WHEN** a paragraph uses an interpreter not in `allowed_interpreters`
- **THEN** the tool error explanation names the interpreter allowlist rule and the rejected interpreter name

#### Scenario: Explain an sh command rejection
- **WHEN** an `sh` interpreter paragraph starts with `rm` and `sh_allowed_commands` is `["echo"]`
- **THEN** the tool error explanation names the sh command rule and the command `rm`
