# Current delivery — 2026-10-14

The public `fetch_spark_executor_log` tool is now implemented and registered alongside the five existing Spark tools. Tasks2.1–3.3 are verified below. The earlier section records task1.1's separate real stdout milestone; it does not establish a live production NodeManager/redirect test of the new tool.

# Stdout validation — 2026-10-13

Task 1.1 completed the real Driver stdout validation. Public MCP tool implementation remains pending. No production source, dependencies or MCP registration changed in this milestone.

## Scope and reuse

- Application: `application_1783000588461_687089`; attempt `2`; executor `driver`; container `container_e83_1783000588461_687089_02_000001`; stream `stdout`.
- The request used the exact user-provided same-gateway JobHistory joblogs destination with `start=-65536`. No URL guesses, automatic redirects, NodeManager route probes or other executor requests were made.
- Existing `SparkHttpClient._ensure_client()` and `_login()` performed the Knox SSO Basic exchange. Existing `SparkSecrets.redaction_values`, `credential_values()` and `redact_event()` redacted text and provenance. Configured credentials were read only in memory from the same private file previously designated by the user; no copy or environment dump was written.
- Reused the user's previously explicit certificate-verification opt-out only in this one validation process. No persistent TLS/auth/MCP configuration change. Login used the existing History root originalUrl and checked cookie applicability against the actual stdout target; Basic Authorization was asserted absent from GET.
- Fixed limits: one 60-second budget per attempt, HTML up to 8 MiB, output up to 1 MiB, requested tail 64 KiB. Raw HTML/body existed only in bounded process memory; only redacted stdout and a safe manifest were published.

## Observed real response

Final successful request at `2026-10-13T08:22:55.603364Z` (`16:22:55` Asia/Shanghai): login POST 303, applicable Cookie present, stdout GET 200 `text/html`, no redirect.

The HTML response was 8,923 bytes. It contained `Log Type: stdout`, `Log Length: 4404`, one 2-byte template whitespace pre block and one 4,404-byte log-content pre block. The container ID was absent from page heading/link attributes and appeared only in log text. The response URL matched the already authorized and validated container-specific request URL; log text was never used to establish identity.

Requested tail size exceeds the reported complete stream length; extracted raw stdout length exactly equals reported length, 4,404 bytes. This sample therefore contains the full stream, not just a partial tail. It ends with a newline. Synthetic cases independently cover an EOF-final line without newline and preserve it through extraction/redaction. Redaction placeholder expansion increased saved size to 5,754 bytes; saved size is not an upstream byte-offset measure.

## Published private evidence

Local directory (outside Git):

`/Users/liji/.cache/etl-mcp-suite/spark-stdout-validation/application_1783000588461_687089/attempt-2/driver/bcfadccbb1e344888bfacb583a32ea9a/`

- `stdout.log`: UTF-8 redacted text, 5,754 bytes.
- `manifest.json`: request identity, safe source URL, request range, upstream size, output digest/path/time and safe HTTP status metadata. No log正文, credentials, Cookie or raw HTML.
- Output SHA-256: `fc84233bdfaf42a8a71e6d1b0d72d6bc985433f76bf196d12add5d0531d5b13b`.
- Directory mode 0700, both file modes 0600; same-filesystem atomic publication; no staging remnants.

Configured username/password/Basic encoding and all acquired Cookie values were checked absent from the saved stdout and manifest before publication. The first independent checker incorrectly assumed login must return 200; recorded metadata showed the valid existing 303 Cookie exchange. Its assertion was corrected to the actual contract and freshly passed. A separate process reopened both files, recomputed SHA-256 and size, checked identity, status metadata, permissions, staging absence and configured-secret absence; all checks passed. HTTP client/cookies were closed/cleared by the existing lifecycle. No raw media or log text is committed.

## Experiments and checks

| Check / command | Actual result |
| --- | --- |
| Empty extraction stub against synthetic stdout/EOF assertion | expected RED: stdout extraction missing |
| Synthetic stdout/login/entity/EOF/redaction checks | PASS |
| Initial real HTML extraction | authentication/GET succeeded, extraction rejected due to overstrict single-pre and page-title identity assumptions; no files published |
| Structural diagnostic repeat | confirmed whitespace pre + one stdout body and no explicit page identity metadata; only shapes/lengths were output |
| Regression cases for template blocks and request-bound identity | expected RED before adjustment; GREEN afterward; wrong-source URLs and IDs solely in log text rejected |
| Final actual stdout acquisition using existing auth/redaction | PASS: POST 303, GET 200, recognized stdout, private atomic evidence, secret checks |
| Independent saved-file validation in a new process | PASS: sizes, hash, identity, modes, staging absence and configured-secret absence |
| `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_knox_auth.py tests/unit/plugins/spark/test_files.py` | 54 passed in fresh run |
| `openspec validate add-spark-executor-log-fetch --strict` | valid |

The experiment program was private and temporary; no generic parser, new tool or credential loader was added to production. Verification establishes the provided Driver JobHistory stdout path and observed HTML; NodeManager-to-JobHistory redirect flow, other executors and stderr remain unverified. Later tasks remain unchecked.

Fresh final scope checks: `openspec validate --changes --strict` passed 16 changes; `openspec validate --specs --strict` passed 2 specs; `git diff --check` passed. Existing unrelated archive-order and long-requirement informational notices remain; no new validation failure.


## Apply verification — 2026-10-14

Implementation reuses SparkHttpClient's existing Knox exchange, SparkSecrets/credential_values/redact_event, the existing eventlog directory owner, and VerifiedEventLogReader. No new dependency, root setting, storage framework, credential loader or retention/cache subsystem was added. Two optional deployment settings enable gateway access; old configurations remain valid. Services depend only on domain contracts/ports. Six-tool stdio contracts and architecture tests verify composition and isolation.

### TDD and review evidence

- Task2.1: missing input/result/service/config tests observed RED (16 failures), then strict contracts/config/service + safe operation passed132 scoped tests.
- Task2.2: missing URL/HTML/auth adapter tests observed RED. Verified last registration, Driver selection, missing stream without refresh, URL identity/query/allowlist, redirects, authentication, recognized HTML, limits and EOF behavior using synthetic events/HTML and MockTransport. Existing eventlog refusal of redirects remains covered.
- Task2.3: absent fetch/publication and missing MCP/schema/architecture wiring observed RED. Private permissions, symlink descendants, atomic hash/manifest publication, independent repeated evidence, failure cleanup, one deadline, queued-call timeout, shutdown cancellation and shared lock reuse now pass.
- Read-only task and whole-change reviews found Cookie rotation losing an earlier secret; malformed-URL/unsupported-3xx mapping; pre-redaction trimming losing folded/quoted credential context; staging-open cleanup; and redacted-size source-range inference. Each was reproduced by a failing regression test before its fix and re-reviewed. The final policy rejects source text exceeding requested tail_bytes before publication, redacts the full acquired context, and trims only the fixed saved-output bound. OpenSpec was updated before implementing the clarified boundary policy.
- Final task review approved; whole-change review found no additional feature/security issue. Its minor Chinese tool-overview omission was corrected and checked. Review used no real credentials/network.
- Task3.1: new example-file checks first failed due to missing files; equivalent YAML/JSON/env settings now pass. README (both languages) and both architecture views were synchronized, including unsupported stream-metadata shapes and operational limits.
- Task3.2: missing opt-in runner tests first failed (14 failures); complete prerequisites now gate process creation. Both Cookie and Basic modes use existing configuration. Live test runs the shipped stdio process via the MCP SDK and independently verifies saved evidence without printing log text.

### Fresh final checks

| Exact command / check | Result |
| --- | --- |
| `uv sync --locked` | PASS: resolved57 packages, checked51; no dependency change |
| `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark tests/contract/test_spark_stdio.py tests/contract/test_architecture.py tests/unit/test_registry.py` | 599 passed |
| `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_config.py tests/unit/test_package.py` | 39 passed |
| `PYTHONPATH=src uv run --locked pytest -q tests/integration/test_opt_in.py` | 41 passed,1 deselected |
| `PYTHONPATH=src uv run --locked pytest -q` | 2078 passed,6 skipped,7 deselected in32.30s |
| `uv run --locked ruff check .` | All checks passed |
| `uv run --locked pyright` | 0 errors,0 warnings,0 informations |
| `uv build` | wheel and sdist built successfully |
| `PYTHONPATH=src uv run --locked mcp-stdio --help` | exit0; documented plugin/config/debug options |
| Spark EOF smoke described below | PASS |
| `openspec validate add-spark-executor-log-fetch --strict` | valid |
| `openspec validate --changes --strict` | 18 passed,0 failed |
| `openspec validate --specs --strict` | 3 passed,0 failed |
| `git diff --check` | PASS |
| `PYTHONPATH=src uv run --locked pytest -q -m integration tests/integration/test_spark_executor_logs.py` | 1 skipped: explicit deployment opt-in/settings absent |

EOF smoke ran `uv run --locked mcp-stdio --plugin spark` with stdin=/dev/null, an isolated temporary private cache, unreachable `https://127.0.0.1:1/gateway/test/sparkhistory`, enabled placeholder log route and synthetic allowlist. It exited0, emitted no stdout, and a subsequent runtime reopened the same cache successfully. Startup-network rejection is additionally covered by the runtime unit test. Real subprocess contracts exercise eventlog resolution -> NodeManager307 -> JobHistory200 -> fresh private log/manifest, repeat without another eventlog download, and protocol-only stdout.

### Live status and limits

Task1.1's user-designated Driver JobHistory stdout remains a real successful validation with its independently checked private files/hash recorded above. The newly shipped tool's production NodeManager route/redirect and other executors/streams have **not** been live-validated; the new explicit integration suite was **skipped**, not reported passed. The parser accepts only recognized UTF-8 metadata-bound stream content; standard local NodeManager pages without stream metadata fail safely. No deployment route was guessed or probed. Fixed credential redaction is not general business-data anonymization. Existing unrelated archive-order/long-requirement informational notices remain, with no strict-validation failures.
