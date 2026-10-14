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
