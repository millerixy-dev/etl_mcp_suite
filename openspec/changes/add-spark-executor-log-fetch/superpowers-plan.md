# Stdout validation micro-plan

> Use superpowers:executing-plans for this tightly coupled validation task. OpenSpec tasks.md remains the only milestone checklist.

**Goal:** Complete task 1.1 against the user-authorized Driver stdout URL, reusing existing Spark authentication and redaction.

**Architecture:** No production changes. A private temporary validation program calls SparkHttpClient._ensure_client/_login and files.redact_event/credential_values, collects a bounded HTML response in memory, extracts stdout and atomically publishes private redacted evidence.

**Tech stack:** Existing locked uv environment, httpx, Pydantic and Python HTMLParser/hashlib/pathlib.

## Global constraints

Python >=3.10, uv exclusively, no secrets/raw HTML/raw log text in outputs or committed files; credentials only in process memory; authorization and TLS settings reuse the prior user-authorized same-gateway validation. Fixed 8MiB response and 1MiB output, one 60s deadline. No URL guessing or automatic redirects. Requested tail is 65536 bytes. The known destination is application_1783000588461_687089, attempt 2, Driver stdout.

## Task 1.1 — Real stdout evidence

Files: read existing spark/config.py, http_client.py, files.py and tests/unit/plugins/spark/test_knox_auth.py; update only this change's planning artifacts and verification.md. Create the experiment program in a private temporary directory and remove it after verification; output evidence under the user's private local cache, never the Git checkout.

Consumes: SparkSettings/SparkSecrets; SparkHttpClient._login(client, download_url, deadline); redact_event({"Event":"DiagnosticText","text":body}, credential_values(secret_values)). Produces: stdout.log and manifest.json, safe structural summary only.

1. Run `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_knox_auth.py tests/unit/plugins/spark/test_files.py`; existing authentication/redaction contracts must pass.
2. Before adding extraction logic, run the temporary program's synthetic checks against an empty extraction stub: a matching stdout pre block must yield `last line without newline`; assert the expected failure. No network in this step.
3. Implement HTMLParser extraction in the experiment only. Require validated request URL identity, Log Type stdout and one associated body pre; reject login form, ignore template-only pre, and never use IDs inside log text as identity evidence. Run the same checks, verify UTF-8/entities and EOF-final-line preservation, then use existing redact_event to remove synthetic password and known secret. No bespoke streaming redactor.
4. Read only the already user-designated credential file in memory. Parse URL/USER_NAME/PASSWORD without executing its contents. Require its origin to match the user's stdout destination. Instantiate the existing settings/secrets and use exactly the existing Knox SSO POST; do not reveal credential values, query auth codes or cookies. Use existing authorized verify_tls=false only for this one live validation; no persistent configuration change.
5. GET the exact user-provided JobHistory stdout URL with start=-65536 and Accept-Encoding identity. Never follow Location automatically; report safe failure if status or recognized log body is missing. Preserve raw HTML in bounded memory only, redact extracted text with configured and acquired cookie values.
6. Publish UTF-8 stdout.log plus one manifest in a 0700/0600 private cache directory. Record container, request range, source metadata, output size/hash and downloaded_at, with credentials redacted from provenance. Independently reopen output and verify hash, permissions and known-secret absence. Run fresh existing tests plus strict OpenSpec checks. Only then gate task 1.1; later public-tool tasks stay pending.

Verification commands: the pytest command above; `openspec validate add-spark-executor-log-fetch --strict`; `openspec validate --changes --strict`; `openspec validate --specs --strict`; `git diff --check`. Record safe actual results in verification.md. The temporary experiment is not a public MCP tool and is not committed as production code.
