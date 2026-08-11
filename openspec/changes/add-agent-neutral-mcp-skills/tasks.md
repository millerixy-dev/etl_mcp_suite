## 1. Validation Foundation

- [x] 1.1 Add tests that reject client-specific coupling and validate canonical skill structure and required MCP tool coverage; confirm the supplied source skills fail the neutral-content checks.

## 2. Canonical Skills

- [x] 2.1 Create and validate the agent-neutral `zeppelin` skill with notebook lifecycle, polling, cancellation, restart, namespace, and safety guidance.
- [x] 2.2 Create and validate the agent-neutral `hive` skill with metadata-only routing and Zeppelin fallback guidance.
- [x] 2.3 Create and validate the agent-neutral `nl2sql` skill with metadata grounding, ambiguity gates, partition pruning, SQL validation, bounded execution, and result explanation.
- [x] 2.4 Refresh the canonical Hive, Zeppelin, and NL2SQL skills from the latest supplied source skills, retaining compatible safety guidance and rejecting client/deployment coupling.

## 3. Project-Local Installation

- [x] 3.1 Add tested Codex and Trae project-local installers with `--project-root`, `--force`, collision protection, and unrelated-skill preservation.
- [x] 3.2 Document canonical skill locations and concise installer usage in the project README.
- [x] 3.3 Add a tested Codex-only `--with-mcp` path using an editable uv tool, command-name MCP entries, safe managed-block updates, and environment-name forwarding.
- [x] 3.4 Document editable MCP installation, project-local Codex configuration, required launch environment variables, and the current Trae limitation.
- [x] 3.5 Document the validated uv version and macOS installation paths, and describe Zeppelin and DolphinScheduler as available built-in plugins.
- [x] 3.6 Add a complete Simplified Chinese README and bidirectional language links.

## 4. Final Verification

- [ ] 4.1 Run the skill validator, affected automated tests, shell syntax checks, full non-integration suite, lint, type checks, package build, console smoke test, and strict OpenSpec validations.

  Blocked: repository-wide Pyright reports 25 pre-existing errors in unchanged Zeppelin test files.
  Changed-scope Pyright passes with zero errors; 581 non-integration tests pass, one skips, and two
  are deselected. Skill validation, shell checks, Ruff, build, the `PYTHONPATH=src` console smoke,
  and strict OpenSpec validation pass. Direct `.venv` console smoke remains affected by the
  pre-existing missing source-path registration in this local environment.
