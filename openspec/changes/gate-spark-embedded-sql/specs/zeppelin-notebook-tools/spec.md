## MODIFIED Requirements

### Requirement: Gate paragraph content with write-operation safety rules
The `add_paragraph` tool SHALL inspect the paragraph body before sending it to Zeppelin through a mandatory, configurable, multi-level safety hook and reject content that violates configured write-safety rules. The safety hook SHALL be the sole path from `add_paragraph` to the gateway and SHALL NOT be bypassable. For SQL interpreters (any interpreter whose name contains `sql`), statements whose leading keyword is in `sql_forbidden_keywords` (default `DROP`, `TRUNCATE`) SHALL be rejected with `INVALID_INPUT` regardless of target database; this forbidden-keyword check SHALL run before the database allowlist. Remaining SQL write operations (`INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `ALTER`, `LOAD`) SHALL only target tables in databases listed in `sql_write_allowed_databases` (default `tmp_dc_ep`). For the `sh` interpreter, only commands whose first token is in `sh_allowed_commands` (default empty) SHALL be allowed. 

For ALL interpreters (including execution-capable interpreters such as `spark` whose name does not contain `sql`), the safety hook SHALL scan the paragraph body for SQL embedded in `sql("...")` string-literal arguments - matching any `sql(` call at a word boundary, including `spark.sql(`, `sqlContext.sql(`, and bare `sql(` - and extract the SQL text from triple-quoted (`"""..."""`), double-quoted (`"..."`), and single-quoted (`'...'`) string arguments. Each extracted SQL statement SHALL be validated through the same forbidden-keyword blacklist and write-target allowlist as direct SQL-interpreter statements. Interpolated strings (Scala `s"...$var"`, Python `f"...{var}"`) and dynamically constructed SQL that is not a static string literal are not statically extractable and are outside the gate's coverage; this limitation SHALL be documented.

All rejections SHALL return `INVALID_INPUT` without sending the paragraph body to Zeppelin.

#### Scenario: Allow a SQL write to an approved database
- **WHEN** a SQL interpreter paragraph contains `INSERT INTO tmp_dc_ep.my_table` and `sql_write_allowed_databases` includes `tmp_dc_ep`
- **THEN** the paragraph is accepted and sent to Zeppelin

#### Scenario: Reject a SQL write to a non-approved database
- **WHEN** a SQL interpreter paragraph contains `INSERT INTO other_db.my_table` and `sql_write_allowed_databases` is `["tmp_dc_ep"]`
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Reject a forbidden SQL operation on an approved database
- **WHEN** a SQL interpreter paragraph contains `DROP TABLE tmp_dc_ep.my_table` and `sql_forbidden_keywords` includes `DROP` and `sql_write_allowed_databases` includes `tmp_dc_ep`
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Reject TRUNCATE regardless of target database
- **WHEN** a SQL interpreter paragraph contains `TRUNCATE TABLE tmp_dc_ep.my_table` and `sql_forbidden_keywords` includes `TRUNCATE`
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Allow CREATE on an approved database
- **WHEN** a SQL interpreter paragraph contains `CREATE TABLE tmp_dc_ep.my_table (id int)` and `sql_forbidden_keywords` is `["DROP", "TRUNCATE"]` and `sql_write_allowed_databases` includes `tmp_dc_ep`
- **THEN** the paragraph is accepted and sent to Zeppelin

#### Scenario: Allow ALTER on an approved database
- **WHEN** a SQL interpreter paragraph contains `ALTER TABLE tmp_dc_ep.my_table ADD COLUMNS (x int)` and `sql_forbidden_keywords` is `["DROP", "TRUNCATE"]` and `sql_write_allowed_databases` includes `tmp_dc_ep`
- **THEN** the paragraph is accepted and sent to Zeppelin

#### Scenario: Allow a SQL read against any database
- **WHEN** a SQL interpreter paragraph contains `SELECT * FROM any_db.my_table`
- **THEN** the paragraph is accepted regardless of `sql_write_allowed_databases`

#### Scenario: Reject a non-allowlisted sh command
- **WHEN** an `sh` interpreter paragraph body starts with `rm` and `sh_allowed_commands` is `["echo", "cat"]`
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Allow an allowlisted sh command
- **WHEN** an `sh` interpreter paragraph body starts with `echo` and `sh_allowed_commands` is `["echo", "cat"]`
- **THEN** the paragraph is accepted and sent to Zeppelin

#### Scenario: Default deny all sh commands
- **WHEN** `sh_allowed_commands` is empty or omitted and an `sh` interpreter paragraph is submitted
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Reject an embedded SQL write to a non-approved database via spark interpreter
- **WHEN** a `spark` interpreter paragraph contains `spark.sql("INSERT OVERWRITE TABLE dwd_dc_ep.my_table SELECT * FROM tmp_dc_ep.src")` and `sql_write_allowed_databases` is `["tmp_dc_ep"]`
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Reject an embedded forbidden keyword via spark interpreter
- **WHEN** a `spark` interpreter paragraph contains `spark.sql("DROP TABLE dwd_dc_ep.my_table")` and `sql_forbidden_keywords` includes `DROP`
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Allow an embedded SQL read via spark interpreter
- **WHEN** a `spark` interpreter paragraph contains `spark.sql("SELECT * FROM tmp_dc_ep.my_table")`
- **THEN** the paragraph is accepted and sent to Zeppelin

#### Scenario: Allow an embedded SQL write to an approved database via spark interpreter
- **WHEN** a `spark` interpreter paragraph contains `spark.sql("INSERT INTO tmp_dc_ep.my_table VALUES (1)")` and `sql_write_allowed_databases` includes `tmp_dc_ep`
- **THEN** the paragraph is accepted and sent to Zeppelin

#### Scenario: Allow spark code without sql calls
- **WHEN** a `spark` interpreter paragraph contains `val df = spark.read.parquet("/path")` with no `sql(` call
- **THEN** the paragraph is accepted and sent to Zeppelin

#### Scenario: Extract embedded SQL from triple-quoted strings
- **WHEN** a `spark` interpreter paragraph contains `spark.sql("""INSERT OVERWRITE TABLE dwd_dc_ep.my_table SELECT 1""")` using triple-quoted strings and `sql_write_allowed_databases` is `["tmp_dc_ep"]`
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Allow multiple embedded SQL statements when all are safe
- **WHEN** a `spark` interpreter paragraph contains `spark.sql("SELECT 1")` followed by `spark.sql("SELECT * FROM tmp_dc_ep.t")` 
- **THEN** the paragraph is accepted and sent to Zeppelin

### Requirement: Explain write-safety rejections
When the write-safety hook rejects a paragraph, the `add_paragraph` tool SHALL return an `INVALID_INPUT` error whose `explanation` concisely names the fired rule and the safe identifier that caused the rejection. The explanation SHALL identify whether the rejection came from the interpreter allowlist, the SQL forbidden-keyword blacklist, the SQL write-target database allowlist, the embedded-SQL scan, or the sh command allowlist, and SHALL name the relevant safe identifier (interpreter name, SQL keyword, target database, or sh command). The explanation MUST NOT contain credentials, the paragraph body, or unbounded upstream content.

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

#### Scenario: Explain an embedded-SQL write-target rejection
- **WHEN** a `spark` interpreter paragraph contains `spark.sql("INSERT OVERWRITE TABLE dwd_dc_ep.my_table SELECT 1")` and `sql_write_allowed_databases` is `["tmp_dc_ep"]`
- **THEN** the tool error explanation names the write-target rule and the database `dwd_dc_ep`
