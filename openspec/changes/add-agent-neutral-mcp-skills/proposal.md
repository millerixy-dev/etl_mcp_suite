## Why

The existing Hive, Zeppelin, and natural-language-to-SQL skills are tied to Trae-specific invocation syntax and naming, so they cannot be distributed with this MCP server for use by different Agent Skills-compatible clients. The project needs one canonical, client-neutral skill set plus repeatable installers for Codex and Trae.

## What Changes

- Add three client-neutral Agent Skills for Hive metadata discovery, Zeppelin notebook execution, and natural-language-to-SQL workflows.
- Replace client-specific tool wrappers and fixed MCP server aliases with capability-based MCP tool discovery and invocation guidance.
- Make the agent-created Zeppelin notebook root configurable instead of embedding a Trae-specific path.
- Add separate Codex and Trae installation scripts that copy the same canonical skills into the platform-specific destination.
- Add an optional Codex-only `--with-mcp` mode that installs the current checkout as an editable uv tool and manages project-local MCP entries without embedding checkout paths or secret values.
- Add automated validation for skill structure, forbidden client coupling, and isolated installation behavior.
- Refresh the canonical skills from the latest supplied Trae-local source skills, retaining only client-neutral guidance that is compatible with the repository's MCP safety boundaries.

## Capabilities

### New Capabilities

- `agent-neutral-mcp-skills`: Canonical Hive, Zeppelin, and NL2SQL Agent Skills and their cross-client installation behavior.

### Modified Capabilities

None.

## Impact

- Adds repository-owned skill packages under `skills/` and installation utilities under `scripts/`.
- Adds tests for skill metadata/content and installer behavior.
- Extends the Codex installer to manage a marked block in `.codex/config.toml`; it does not change MCP tool schemas, runtime dependencies, or backend behavior.
- Updates canonical skill guidance and its content contracts without changing MCP tool schemas, runtime dependencies, or backend behavior.
