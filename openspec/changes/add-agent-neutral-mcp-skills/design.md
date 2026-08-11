## Context

Three Trae-local skills currently describe Hive metadata lookup, Zeppelin notebook execution, and NL2SQL orchestration. Their domain rules are reusable, but their invocation examples depend on Trae's `run_mcp` wrapper, fixed server aliases, and a `/trae/` notebook namespace. This repository now implements the corresponding Hive and Zeppelin MCP tools and should distribute one canonical skill set that any Agent Skills-compatible MCP client can consume.

The canonical source will follow the Agent Skills `SKILL.md` structure. Platform installers will only copy files into project-local discovery directories; they will not maintain divergent content. The skill text will follow the MCP tools abstraction rather than a client's tool-call syntax.

Primary references:

- Agent Skills specification: https://agentskills.io/specification
- MCP tools specification: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- Repository tool contracts: `src/mcp_stdio/plugins/hive/tools.py` and `src/mcp_stdio/plugins/zeppelin/tools.py`

## Goals / Non-Goals

**Goals:**

- Preserve the useful safety and workflow rules from the three source skills.
- Remove Codex-, Trae-, and wrapper-specific vocabulary from canonical skill content.
- Align named tools with the MCP server contracts in this repository.
- Install identical skill files into project-local Codex and Trae directories.
- Make installation deterministic, idempotent with explicit overwrite, and testable without touching a real user project.

**Non-Goals:**

- Configure MCP server instances for clients other than Codex, or launch a listening MCP transport.
- Change MCP tools, schemas, safety policy, or backend behavior.
- Install skills globally in a user's home directory.
- Implement a generic installer for clients other than Codex and Trae.

## Decisions

### Keep one canonical skill tree

Store the canonical packages at `skills/hive`, `skills/zeppelin`, and `skills/nl2sql`. Each package contains a self-contained `SKILL.md`; no client-specific metadata is required.

Alternative considered: maintain `.codex/skills` and `.trae/skills` copies in Git. This was rejected because duplicated content can drift and makes validation ambiguous.

### Describe MCP capabilities, not client invocation syntax

Skills will instruct the agent to discover a configured MCP server exposing the required tool names and then invoke those tools through the client's normal MCP interface. Examples will show tool name plus JSON arguments, without `run_mcp`, generated namespace prefixes, or fixed server aliases.

Alternative considered: use placeholders such as `<client_tool_call>`. This still embeds an artificial calling syntax and is less readable than capability-oriented examples.

### Use an agent-neutral notebook namespace

Agent-created notebooks default to `/agents/`. A user or project instruction may provide another root, which takes precedence. Existing notebooks are listed and reused before a new one is created. This preserves namespace hygiene without retaining `/trae/` coupling.

Alternative considered: remove the namespace rule. This was rejected because uncontrolled root-level notebook creation was a concrete safety and maintainability concern in the source skill.

### Refresh source-derived guidance without importing client or deployment coupling

The latest supplied source skills add useful operational rules, but also contain Trae-only invocation syntax, a fixed `/trae/` namespace, deployment-specific interpreter names, and a write fallback that bypasses the MCP runtime. Canonical skills retain only rules that remain valid for every compatible MCP client and the repository's configured safety boundaries:

- A Zeppelin paragraph still running after 300 seconds pauses for the user's decision to continue waiting or cancel. It never changes interpreter or resubmits automatically; any retry uses only a user-approved, configured interpreter.
- For user-requested ETL or write-operation design, NL2SQL discovers source and target schemas, makes type conversions explicit, and preserves event-time semantics rather than silently substituting ETL execution time. The skill still does not automatically execute writes or bypass the configured Zeppelin allowlist.

Alternative considered: copy every newer source rule verbatim. This was rejected because server aliases, `run_mcp`, `/trae/`, fixed interpreters, and direct beeline/Hive CLI fallbacks either make the skills client-specific or violate the repository safety model.

### Install into project-local client directories

Both installers derive canonical skills from their own repository location and accept the same command interface.

| Field | Required | Default | Meaning |
| --- | --- | --- | --- |
| `--project-root PATH` | no | current working directory | Project receiving the skills |
| `--force` | no | false | Allow overwriting the three managed skill packages |
| `--with-mcp` | Codex only | false | Install the current checkout as an editable uv tool and manage project-local Hive and Zeppelin MCP entries |
| `--help` | no | n/a | Print usage and exit |

Codex destination is `<project>/.codex/skills`; Trae destination is `<project>/.trae/skills`. Missing destination parents are created. Existing managed skill directories cause a non-zero exit unless `--force` is present. Installers never delete unrelated skills.

Example starts:

```sh
./scripts/install-skills-codex.sh --project-root /path/to/project
./scripts/install-skills-trae.sh --project-root /path/to/project
```

No plugin YAML/JSON configuration format is introduced by this change. The server's existing environment-only configuration model remains unchanged; only the Codex host registration is managed.

### Install the local MCP server for Codex without checkout paths in config

When the Codex installer receives `--with-mcp`, it performs this ordered flow:

1. Resolve the repository containing the installer and validate the target Codex config before changing skills, tools, or config.
2. Require `uv`, obtain the uv tool executable directory with `uv tool dir --bin`, and require that exact directory to be present in `PATH`.
3. Run `uv tool install --editable <resolved-repository> --reinstall`. The editable tool metadata may contain the repository path, but the persistent Codex config does not.
4. Require `mcp-stdio` to resolve from `PATH`.
5. Atomically create or replace one marked block in `<project>/.codex/config.toml`, preserving all unrelated content.
6. Report missing required runtime variable names as warnings without printing values or failing installation.

The generated configuration is:

```toml
# BEGIN mcp-stdio managed
[mcp_servers.hive]
command = "mcp-stdio"
args = ["--plugin", "hive"]
env_vars = [
  "HIVE_HOST",
  "HIVE_PORT",
  "HIVE_DATABASE",
  "HIVE_CACHE_TTL_SECONDS",
  "HIVE_USERNAME",
  "HIVE_PASSWORD",
]

[mcp_servers.zeppelin]
command = "mcp-stdio"
args = ["--plugin", "zeppelin"]
env_vars = [
  "ZEPPELIN_BASE_URL",
  "ZEPPELIN_ALLOWED_INTERPRETERS",
  "ZEPPELIN_USERNAME",
  "ZEPPELIN_PASSWORD",
]
# END mcp-stdio managed
```

`env_vars` names variables that Codex forwards from its launch environment. The config never stores a credential value, absolute Python executable, checkout path, virtual-environment path, or `PYTHONPATH`. Required runtime variables are `HIVE_HOST`, `HIVE_USERNAME`, `HIVE_PASSWORD`, and `ZEPPELIN_BASE_URL`; Zeppelin credentials remain an optional pair. Other supported settings continue to use the server's existing environment model.

The Simplified Chinese README may show `[mcp_servers.<name>.env]` only as a syntax example with redacted placeholders. It explicitly states that literal values are persisted as plaintext and that `env_vars` remains the recommended form for real credentials.

The marked block is replaced on repeated runs, so updates remain idempotent. An unmarked `[mcp_servers.hive]` or `[mcp_servers.zeppelin]` table, malformed marker pair, or duplicate managed block is a conflict and causes a non-zero exit before mutation, including when `--force` is supplied. `--force` controls only skill-directory collisions. The Trae installer rejects `--with-mcp` with a clear non-zero error.

Alternative considered: persist the checkout's `.venv/bin/python` plus `PYTHONPATH`. This was rejected because moving the checkout or recreating its environment would invalidate Codex configuration. A uv editable tool provides a stable `mcp-stdio` command while importing code from the current checkout on each process start.

### Preserve exact tool contracts

The skills reference these existing tool inputs. Result handling is described by behavior rather than duplicating every server result schema.

| Tool | Inputs |
| --- | --- |
| `list_databases` | none |
| `list_tables` | `database` |
| `get_table_schema` | `database`, `table`, optional `include_ddl` |
| `list_notebooks` | none |
| `create_notebook` | `name` |
| `add_paragraph` | `notebook_id`, `title`, `body` |
| `run_paragraph` | `notebook_id`, `paragraph_id` |
| `get_paragraph_status` | `notebook_id`, `paragraph_id` |
| `get_paragraph_result` | `notebook_id`, `paragraph_id` |
| `cancel_paragraph` | `notebook_id`, `paragraph_id` |
| `restart_interpreter` | `setting_id` |

Representative results retain the server's JSON field names:

```json
{"database":"dwd","table":"events","columns":[],"partition_columns":[],"ddl":null,"cached":false}
```

```json
{"notebook_id":"2ABC","paragraph_id":"p-1","status":"FINISHED"}
```

## Risks / Trade-offs

- [Different MCP clients render tool names differently] -> Refer to stable MCP tool names and require capability discovery instead of rendered namespace syntax.
- [A target project already has customized skills with the same names] -> Fail on collisions unless the operator explicitly passes `--force`.
- [Canonical skills become stale as server tools evolve] -> Contract tests assert required tool-name coverage against the repository's approved tool set.
- [The `/agents/` default conflicts with a deployment convention] -> State that explicit user or project instructions override the default root.
- [No independent subagent pressure test is available in this session] -> Use source-as-baseline coupling checks, structural validation, scenario review, and isolated installer tests; document the limitation in verification output.

## Migration Plan

1. Add and validate each canonical skill independently.
2. Add installers and verify both against temporary project roots.
3. Consumers run the installer for their client and review any collision before using `--force`.
4. Rollback removes only the installed `hive`, `zeppelin`, and `nl2sql` directories from the target client's project-local skills directory; the installer itself performs no uninstall or broad deletion.

## Open Questions

None. Project-local installation scope was confirmed by the user.
