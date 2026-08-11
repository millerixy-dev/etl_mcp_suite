## ADDED Requirements

### Requirement: Distribute canonical agent-neutral skills
The repository SHALL provide canonical `hive`, `zeppelin`, and `nl2sql` Agent Skills whose `SKILL.md` frontmatter names match their directories. Canonical skill instructions MUST NOT depend on Codex, Trae, `run_mcp`, fixed MCP server aliases, or client-generated tool namespace syntax.

#### Scenario: Inspect canonical skill packages
- **WHEN** a maintainer validates the repository skill tree
- **THEN** all three packages have valid frontmatter and contain no prohibited client-specific coupling

### Requirement: Guide Hive metadata discovery through MCP
The `hive` skill SHALL use `list_databases`, `list_tables`, and `get_table_schema` for Hive metadata discovery, SHALL describe Hive MCP as metadata-only, and SHALL route SQL execution needs to the `zeppelin` skill without suggesting direct JDBC, Thrift, REST, or shell access.

#### Scenario: Resolve a Hive schema request
- **WHEN** an agent needs databases, tables, columns, partitions, or DDL
- **THEN** the skill directs it to the matching Hive MCP metadata tool using only validated identifiers

#### Scenario: Request requires row access
- **WHEN** an agent needs to execute SQL or inspect table data
- **THEN** the skill directs it to the Zeppelin workflow after metadata validation

### Requirement: Guide safe Zeppelin notebook execution through MCP
The `zeppelin` skill SHALL cover notebook discovery and reuse, creation under an explicit project/user root or the `/agents/` default, paragraph creation, asynchronous execution, bounded status polling, result retrieval, cancellation, and interpreter restart. It MUST prohibit direct REST scripts, hard-coded credentials, and safety-policy bypasses.

#### Scenario: Execute a paragraph to completion
- **WHEN** an agent needs to run an allowed Zeppelin paragraph
- **THEN** the skill directs it through list/reuse-or-create, add, run, terminal-state polling, and result retrieval

#### Scenario: Stop an active paragraph
- **WHEN** the user requests cancellation of a running paragraph
- **THEN** the skill directs the agent to `cancel_paragraph` and then confirms the resulting status

### Requirement: Guide metadata-grounded natural-language queries
The `nl2sql` skill SHALL require schema discovery before SQL construction, exact use of discovered identifiers, partition pruning for partitioned tables, Spark SQL validation, bounded result sets, and Zeppelin MCP execution. It MUST stop for user clarification when table, column, partition, or business meaning remains materially ambiguous.

#### Scenario: Translate a natural-language query
- **WHEN** a user asks a business question that requires Hive row data
- **THEN** the skill directs the agent to discover metadata, construct and validate SQL, execute it through Zeppelin, and explain the bounded result

#### Scenario: Required identifier is ambiguous
- **WHEN** multiple discovered tables or columns plausibly match the user's intent
- **THEN** the skill directs the agent to present the candidates and wait for clarification before executing SQL

### Requirement: Install skills into project-local client directories
The repository SHALL provide separate executable installers for Codex and Trae. Each installer SHALL copy the same canonical skill packages into the selected project's client-specific skills directory, default the selected project to the current working directory, support `--project-root` and `--force`, fail safely on unmanaged collisions without `--force`, and leave unrelated skills untouched.

#### Scenario: Install for Codex
- **WHEN** the Codex installer runs against an empty temporary project
- **THEN** identical canonical skill files are installed under `.codex/skills`

#### Scenario: Install for Trae
- **WHEN** the Trae installer runs against an empty temporary project
- **THEN** identical canonical skill files are installed under `.trae/skills`

#### Scenario: Protect an existing skill
- **WHEN** a managed destination already exists and `--force` is absent
- **THEN** the installer exits non-zero without overwriting the existing skill

#### Scenario: Preserve unrelated skills
- **WHEN** installation runs in a project containing other skill directories
- **THEN** those unrelated directories and files remain unchanged

### Requirement: Optionally install and configure the local MCP server for Codex
The Codex installer SHALL accept `--with-mcp`, SHALL install the current repository using `uv tool install --editable` with reinstall semantics, and SHALL configure project-local Hive and Zeppelin MCP servers to invoke `mcp-stdio` by command name. The persistent Codex configuration MUST NOT contain a secret value, absolute Python executable, checkout path, virtual-environment path, or `PYTHONPATH`. The Trae installer MUST reject `--with-mcp`.

#### Scenario: Install Codex skills with the local MCP server
- **WHEN** the Codex installer runs with `--with-mcp`, uv is available, and the uv tool executable directory is on `PATH`
- **THEN** the current checkout is installed as an editable uv tool and `.codex/config.toml` contains Hive and Zeppelin entries that run `mcp-stdio --plugin <name>`

#### Scenario: Follow local source updates
- **WHEN** source files in the installed checkout change after a successful `--with-mcp` installation
- **THEN** a subsequently started `mcp-stdio` process loads the editable checkout without regenerating Codex configuration

#### Scenario: Forward secrets by variable name
- **WHEN** the installer writes the managed MCP entries
- **THEN** it uses `env_vars` to name supported Hive and Zeppelin variables and writes no environment-variable values

#### Scenario: Update the managed block idempotently
- **WHEN** a valid managed MCP block already exists and the Codex installer runs again with `--with-mcp`
- **THEN** exactly one managed block is replaced atomically while unrelated configuration remains unchanged

#### Scenario: Protect user-managed MCP entries
- **WHEN** the target configuration has an unmarked Hive or Zeppelin MCP table, malformed managed markers, or multiple managed blocks
- **THEN** installation exits non-zero before changing skills, the uv tool, or the target configuration

#### Scenario: uv tool command is not launchable
- **WHEN** uv is missing or its reported tool executable directory is absent from `PATH`
- **THEN** installation exits non-zero before mutation and explains how to make the tool command available

#### Scenario: Required runtime variables are not yet exported
- **WHEN** MCP installation succeeds but one or more required variables are absent from the installer environment
- **THEN** the installer reports only the missing variable names as warnings and does not print values or fail the installation

#### Scenario: Request MCP setup for Trae
- **WHEN** the Trae installer receives `--with-mcp`
- **THEN** it exits non-zero with a message that the option is currently Codex-only
