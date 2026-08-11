# Agent-Neutral MCP Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Distribute client-neutral Hive, Zeppelin, and NL2SQL skills with safe project-local Codex and Trae installers.

**Architecture:** Keep one canonical `skills/` tree and treat platform directories as installation targets only. Validate skill structure, MCP contract coverage, portability, and installer behavior with repository tests.

**Tech Stack:** Markdown Agent Skills, POSIX shell, Python 3.10, pytest, PyYAML, OpenSpec.

## Global Constraints

- Canonical skills MUST NOT contain Codex-, Trae-, `run_mcp`-, fixed-server-alias-, or generated-namespace-specific instructions.
- Canonical package names are exactly `hive`, `zeppelin`, and `nl2sql`.
- Installers default to the current project and MUST NOT delete unrelated skills.
- Production Python syntax remains compatible with Python 3.10; project commands use `uv` exclusively.

---

### OpenSpec Task 1.1: Validation Foundation

**Files:**

- Create: `tests/unit/test_agent_skills.py`

**Interfaces:**

- Consumes: the supplied source skill paths and future canonical `skills/<name>/SKILL.md` files.
- Produces: `load_skill(path) -> tuple[dict[str, object], str]` and `agent_coupling(text) -> set[str]` test helpers plus structural/coverage tests reused by later tasks.

- [x] **Step 1: Add frontmatter, portability, and contract-coverage tests**

  Parse the opening YAML document with `yaml.safe_load`, require exactly `name` and `description`, require the name to equal the directory, and require descriptions to start with `Use when`. Scan canonical content case-insensitively for `run_mcp`, `mcp_hive`, `mcp_zeppelin`, `/trae/`, `codex`, `trae`, and generated namespace examples. Assert the repository tool names required by each skill are present.

- [x] **Step 2: Add a source-baseline test**

  Parameterize the three supplied source paths and assert each has at least one client-coupling marker. This records the RED baseline without modifying those external files.

- [x] **Step 3: Run the focused test and confirm RED**

  Run: `uv run pytest tests/unit/test_agent_skills.py -q`

  Expected: source-baseline cases pass, while canonical skill cases fail because `skills/hive/SKILL.md`, `skills/zeppelin/SKILL.md`, and `skills/nl2sql/SKILL.md` do not exist yet.

- [x] **Step 4: Verify the test module itself passes lint and type checking**

  Run: `uv run ruff check tests/unit/test_agent_skills.py && uv run pyright tests/unit/test_agent_skills.py`

  Expected: both commands exit 0; the planned missing canonical files are runtime RED assertions, not static errors.

- [x] **Step 5: Gate OpenSpec task 1.1**

  Record the focused RED evidence and mark task 1.1 complete. Do not create canonical skill content in this task.

### OpenSpec Task 2.1: Canonical Zeppelin Skill

**Files:**

- Create: `skills/zeppelin/SKILL.md`
- Remove generated client metadata: `skills/zeppelin/agents/openai.yaml`
- Test: `tests/unit/test_agent_skills.py`

**Interfaces:**

- Consumes: Zeppelin MCP tools registered by `ZeppelinToolAdapter`.
- Produces: a self-contained `zeppelin` skill covering all eight registered tools and the `/agents/` default namespace.

- [x] **Step 1: Confirm the focused RED**

  Run: `uv run pytest tests/unit/test_agent_skills.py -q -k zeppelin`

  Expected: FAIL with missing `skills/zeppelin/SKILL.md`.

- [x] **Step 2: Initialize the skill package**

  Run the bundled `init_skill.py` with name `zeppelin`, output path `skills`, and interface text derived from the intended skill. Do not add resource directories.

- [x] **Step 3: Replace the template with the minimal canonical skill**

  Write only `name` and `description` frontmatter. The body must define capability discovery, the eight-tool quick reference, list/reuse/create/add/run/poll/result workflow, `PENDING`/`RUNNING` and `FINISHED`/`ERROR`/`CANCELLED` status handling, cancellation, interpreter restart, the configurable root with `/agents/` fallback, and explicit prohibitions on direct REST access, embedded credentials, and safety bypasses.

- [x] **Step 4: Remove generated provider metadata**

  Delete `skills/zeppelin/agents/openai.yaml`; canonical packages contain no client-specific metadata.

- [x] **Step 5: Validate GREEN**

  Run: `uv run pytest tests/unit/test_agent_skills.py -q -k zeppelin`

  Run: `uv run /Users/liji/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/zeppelin`

  Expected: both commands exit 0.

- [x] **Step 6: Gate OpenSpec task 2.1**

  Re-read the Zeppelin source rules and repository tool adapter, then mark task 2.1 complete only if all required lifecycle and safety behaviors are retained.

### OpenSpec Task 2.2: Canonical Hive Skill

**Files:**

- Create: `skills/hive/SKILL.md`
- Remove generated client metadata: `skills/hive/agents/openai.yaml`
- Test: `tests/unit/test_agent_skills.py`

**Interfaces:**

- Consumes: `list_databases`, `list_tables`, and `get_table_schema` from the Hive MCP process.
- Produces: a self-contained `hive` metadata-routing skill that delegates row access and SQL execution to the installed `zeppelin` skill.

- [x] **Step 1: Confirm the focused RED**

  Run: `uv run pytest tests/unit/test_agent_skills.py -q -k hive`

  Expected: canonical Hive case fails because `skills/hive/SKILL.md` is absent; supplied-source baseline remains evidence of client coupling.

- [x] **Step 2: Initialize and replace the Hive skill**

  Use the bundled initializer without resource directories, then replace the template with frontmatter, capability discovery, a three-tool reference, metadata workflow, exact identifier guidance, capability boundaries, Zeppelin fallback, error handling, and anti-patterns.

- [x] **Step 3: Remove generated provider metadata**

  Delete `skills/hive/agents/openai.yaml` so the canonical package remains client-neutral.

- [x] **Step 4: Validate GREEN**

  Run: `uv run pytest tests/unit/test_agent_skills.py -q -k hive`

  Run: `uv run /Users/liji/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/hive`

  Expected: both commands exit 0.

- [x] **Step 5: Gate OpenSpec task 2.2**

  Confirm the skill never claims the Hive MCP surface can read rows or execute caller SQL, then mark task 2.2 complete.

### OpenSpec Task 2.3: Canonical NL2SQL Skill

**Files:**

- Create: `skills/nl2sql/SKILL.md`
- Remove generated client metadata: `skills/nl2sql/agents/openai.yaml`
- Test: `tests/unit/test_agent_skills.py`

**Interfaces:**

- Consumes: the installed `hive` and `zeppelin` skills and their required MCP tools.
- Produces: a self-contained NL2SQL orchestration skill with explicit clarification and validation gates.

- [x] **Step 1: Confirm the focused RED**

  Run: `uv run pytest tests/unit/test_agent_skills.py -q -k nl2sql`

  Expected: FAIL because `skills/nl2sql/SKILL.md` is absent.

- [x] **Step 2: Initialize and replace the NL2SQL skill**

  Use the bundled initializer without resource directories. Replace the template with intent parsing, Hive metadata discovery, ambiguity handling, schema-grounded Spark SQL construction, partition discovery and pruning, a five-round validation gate, bounded Zeppelin execution, result explanation, and safe error recovery.

- [x] **Step 3: Remove generated provider metadata**

  Delete `skills/nl2sql/agents/openai.yaml` so the canonical package remains client-neutral.

- [x] **Step 4: Validate GREEN**

  Run: `uv run pytest tests/unit/test_agent_skills.py -q -k nl2sql`

  Run: `uv run /Users/liji/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/nl2sql`

  Expected: both commands exit 0.

- [x] **Step 5: Gate OpenSpec task 2.3**

  Confirm that every SQL identifier is metadata-grounded, partitioned row queries are pruned, ambiguous matches stop before execution, and no direct backend access is suggested.

### OpenSpec Task 3.1: Project-Local Installers

**Files:**

- Create: `scripts/install-agent-skills.sh`
- Create: `scripts/install-skills-codex.sh`
- Create: `scripts/install-skills-trae.sh`
- Modify: `tests/unit/test_agent_skills.py`

**Interfaces:**

- Consumes: canonical `skills/{hive,zeppelin,nl2sql}` directories.
- Produces: executable wrappers accepting `--project-root PATH`, `--force`, and `--help`; shared core accepts internal client selector `codex|trae`.

- [x] **Step 1: Add failing installer contract tests**

  Parameterize both public scripts. Assert they are executable, default to the subprocess working directory, copy byte-identical canonical files into `.codex/skills` or `.trae/skills`, preserve unrelated skills, fail without partial copies when any managed destination exists, and overwrite managed files only with `--force`.

- [x] **Step 2: Confirm RED**

  Run: `uv run pytest tests/unit/test_agent_skills.py -q -k installer`

  Expected: FAIL because the public installer scripts do not exist.

- [x] **Step 3: Implement the shared installer and wrappers**

  Use POSIX `sh`, `set -eu`, quoted paths, a canonical script-relative source root, a project-root existence check, preflight collision checks for all three managed names, symlink/non-directory rejection, and overlay copy only after preflight. Wrappers resolve their script directory and `exec` the shared core with the fixed client selector.

- [x] **Step 4: Mark scripts executable and validate syntax**

  Run: `chmod +x scripts/install-agent-skills.sh scripts/install-skills-codex.sh scripts/install-skills-trae.sh`

  Run: `sh -n scripts/install-agent-skills.sh scripts/install-skills-codex.sh scripts/install-skills-trae.sh`

  Expected: syntax check exits 0.

- [x] **Step 5: Validate GREEN**

  Run: `uv run pytest tests/unit/test_agent_skills.py -q -k installer`

  Expected: all installer cases pass for both destinations.

- [x] **Step 6: Gate OpenSpec task 3.1**

  Confirm collision failure occurs before any managed copy and unrelated skill content remains unchanged, then mark task 3.1 complete.

### OpenSpec Task 3.2: README Installation Guidance

**Files:**

- Modify: `README.md`
- Modify: `tests/unit/test_agent_skills.py`

**Interfaces:**

- Consumes: the two public installer names and canonical `skills/` tree.
- Produces: discoverable project-local installation commands and collision guidance.

- [x] **Step 1: Add a failing README contract test**

  Assert the README contains `skills/hive`, `skills/zeppelin`, `skills/nl2sql`, both public installer commands, both project-local destination paths, `--project-root`, and `--force` collision guidance.

- [x] **Step 2: Confirm RED**

  Run: `uv run pytest tests/unit/test_agent_skills.py -q -k readme`

  Expected: FAIL because the README does not yet document the skill distribution.

- [x] **Step 3: Add concise README guidance**

  Add an `Agent Skills` section after package installation. Explain canonical source ownership, show the default current-project commands, show optional `--project-root`, and state that existing managed names require explicit `--force` while unrelated skills are preserved.

- [x] **Step 4: Validate GREEN**

  Run: `uv run pytest tests/unit/test_agent_skills.py -q -k readme`

  Run: `git diff --check`

  Expected: both commands exit 0.

- [x] **Step 5: Gate OpenSpec task 3.2**

  Confirm the documented commands match the executable filenames and actual default destinations, then mark task 3.2 complete.

### OpenSpec Task 3.3: Codex Editable MCP Installation

**Files:**

- Modify: `scripts/install-agent-skills.sh`
- Modify: `tests/unit/test_agent_skills.py`

**Interfaces:**

- Consumes: Codex `--with-mcp`, the current repository root, `uv tool`, target `.codex/config.toml`, and named launch-environment variables.
- Produces: an editable `mcp-stdio` uv tool plus one atomic, marked, path-free Codex MCP configuration block.

- [x] **Step 1: Add focused failing tests**

  Use a fake uv executable and temporary project roots. Cover editable reinstall arguments, stable command configuration, environment-name forwarding, absence of secret values and checkout paths, idempotent managed-block replacement, preservation of unrelated config, conflict preflight, uv tool-bin PATH validation, and Trae rejection.

- [x] **Step 2: Confirm RED**

  Run: `uv run pytest tests/unit/test_agent_skills.py -q -k 'with_mcp or mcp_config'`

  Expected: FAIL because the installers do not yet accept `--with-mcp`.

- [x] **Step 3: Implement the smallest safe installer behavior**

  Extend the shared POSIX shell installer with Codex-only argument handling, mutation-free config and uv preflight, editable uv tool installation, command discovery, atomic marker replacement, and missing-variable-name warnings. Keep `--force` scoped to skill collisions.

- [x] **Step 4: Validate GREEN and refactor**

  Run the focused tests, full agent-skill tests, and `sh -n` for all installer scripts. Refactor only while those checks remain green.

- [x] **Step 5: Gate OpenSpec task 3.3**

  Mark task 3.3 complete only after the fake uv log proves editable reinstall targets this repository and generated config contains neither the repository path nor secret values.

### OpenSpec Task 3.4: Codex MCP Documentation

**Files:**

- Modify: `README.md`
- Modify: `tests/unit/test_agent_skills.py`

- [x] **Step 1: Extend the README contract test and confirm RED**

  Require the Codex `--with-mcp` command, `.codex/config.toml`, `uv tool install --editable`, `env_vars`, required variable names, and the Trae limitation.

- [x] **Step 2: Document installation and launch environment**

  Explain that the uv command is stable while the editable install follows local source, and that `.codex/config.toml` stores variable names rather than values. Include copyable export placeholders without credential values.

- [x] **Step 3: Validate GREEN and gate task 3.4**

  Run the focused README test and `git diff --check`, then mark task 3.4 complete.

### OpenSpec Task 4.1: Final Verification

**Files:**

- Verify: `skills/*/SKILL.md`, `scripts/*.sh`, `tests/unit/test_agent_skills.py`, `README.md`
- Update: `openspec/changes/add-agent-neutral-mcp-skills/tasks.md`

**Interfaces:**

- Consumes: all change deliverables and repository verification commands.
- Produces: fresh completion evidence and a fully checked OpenSpec task list.

- [x] **Step 1: Validate each skill and portability constraints**

  Run all three `quick_validate.py` calls, `uv run pytest tests/unit/test_agent_skills.py -q`, a prohibited-token scan, a placeholder scan, and `wc -l skills/*/SKILL.md`.

  Expected: validators and tests exit 0; scans find no canonical coupling or placeholders; every skill remains under 500 lines.

- [x] **Step 2: Validate installer syntax and behavior**

  Run: `sh -n scripts/install-agent-skills.sh scripts/install-skills-codex.sh scripts/install-skills-trae.sh`

  Run both public scripts with `--help` and rerun installer tests.

  Expected: all commands exit 0 and help describes the project-local options.

- [ ] **Step 3: Run repository quality gates**

  Run: `uv run pytest -m 'not integration'`

  Run: `uv run ruff check src tests`

  Run: `uv run pyright`

  Run: `uv build`

  Run: `uv run mcp-stdio --help`

  Expected: test, lint, type, build, and console smoke commands exit 0. Live integration tests remain opt-in and are reported as not run.

- [x] **Step 4: Run strict OpenSpec and diff validation**

  Run: `openspec validate add-agent-neutral-mcp-skills`, `openspec validate --changes`, `openspec validate --specs`, and `git diff --check`.

  Expected: all commands exit 0 with no spec conflicts or whitespace errors.

- [x] **Step 5: Review the complete change**

  Compare the diff against every requirement and scenario in the capability spec. Because subagent dispatch is not authorized in this session, perform a documented self-review and do not claim an independent reviewer result.

- [ ] **Step 6: Gate OpenSpec task 4.1**

  Mark the final task complete only after every fresh command supports completion.

  Blocked on 2026-08-10: repository-wide `uv run pyright` reports 25 pre-existing errors in
  unchanged `tests/unit/plugins/zeppelin/` files. Changed-scope type checking (`src` plus
  `tests/unit/test_agent_skills.py`) passes with zero errors. The full non-integration run reports
  581 passed, one skipped, and two deselected. Lint, build, skill validation, strict OpenSpec
  validation, and the `PYTHONPATH=src` console smoke pass; the direct `.venv` entry point remains
  affected by the pre-existing missing source-path registration in this local environment.
