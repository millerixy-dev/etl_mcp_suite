# Verification — add-spark-event-log-download

Date: 2026-10-12. Schema: spec-driven. Branch: codex/spark-job-failure-diagnosis.
OpenSpec tasks.md is the implementation progress authority.

## Scope and review

Delivered one Spark plugin/tool: fetch_spark_event_log(application_id, attempt_id=None, refresh=False).
Validated, redacted JSONL and one manifest are published in private per-download directories;
default exact-source/scope reuse and explicit refresh are supported. No CAS, TTL, GC, tail repair
or new runtime dependency was added.

Implementation followed task-scoped RED/GREEN tests. Independent read-only review covered
d2d80c1e7794336fad58376beba34e46da806dee through edf0eac0dd53d19787d91a1282752177cd8ebfbc,
then reviewed the corrective working-tree diff after 961c3d3. Three Important findings were
reproduced in failing tests and fixed separately:

- Literal attempt string "null" was changed by SDK preprocessing: registered FuncMetadata now
  preserves raw validated values while retaining output conversion. Regressions distinguish
  string "null", string "1" and JSON null.
- Prebuilt default SSLContext inherited environment CA settings: default trust now uses
  HTTPX verify=True with trust_env=False; explicit CA configuration still uses verified
  SSLContext. A no-network real context-factory test checks SSL_CERT_FILE/DIR isolation.
- Unknown multi-value Cookie text leaked its second value: full Cookie/Set-Cookie header values
  are redacted before generic assignment handling, with a persistent JSONL regression.

Independent re-review: all three findings resolved, no remaining Critical/Important/Minor
findings in the corrective diff. Reviewer fresh focused suite: 155 passed.

## Final fresh commands and outcomes

| Command | Result |
| --- | --- |
| `uv sync --locked` | exit 0; 57 packages resolved, 51 checked |
| `PYTHONPATH=src uv run --locked pytest` | exit 0; 1580 passed, 6 skipped, 6 deselected (13.40 s) |
| `uv run --locked ruff check .` | exit 0; all checks passed |
| `uv run --locked pyright` | exit 0; 0 errors, 0 warnings |
| `uv build` | exit 0; sdist and wheel built |
| `PYTHONPATH=src uv run --locked mcp-stdio --help` | exit 0; four plugins including spark listed |
| `PYTHONPATH=src uv run --locked pytest -m integration tests/integration/test_spark_server.py -rs` | exit 0; 1 skipped, deployment opt-in/settings absent |
| `openspec validate add-spark-event-log-download --strict` | exit 0; valid |
| `openspec validate --changes --strict` | exit 0; 14 passed, 0 failed |
| `openspec validate --specs --strict` | exit 0; 2 passed, 0 failed |
| `git diff --check` | exit 0 |

Full pytest's skipped entries belong to the existing environment-gated DolphinScheduler suite;
six integration-marker cases are deselected by the default test setting. The explicit Spark
live command was also executed and skipped. No real authenticated HTTP download is claimed.
Prior manual browser download is design evidence, not proof of this automatic client.

OpenSpec emitted existing informational notes about unrelated change archive targets and an
existing long main-spec requirement; none was a validation failure.

## Console EOF and wheel smoke

The following exact command was executed successfully. It launches the real console entry
point, supplies a fresh temporary private root and unreachable source, sends EOF immediately,
checks protocol-only stdout and no staging, then checks the built wheel's Spark modules.
No upstream request is issued.

```sh
PYTHONPATH=src uv run --locked python - <<'PY'
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

root = Path.cwd()
with TemporaryDirectory(prefix='spark-console-smoke-') as temporary:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('SPARK_', 'MCP_STDIO__SETTINGS__'))}
    env.update(PYTHONPATH=str(root / 'src'), SPARK_HISTORY_SERVER_URL='https://127.0.0.1:1',
               SPARK_CACHE_DIR=str(Path(temporary) / 'l3'))
    child = subprocess.run([str(root / '.venv/bin/mcp-stdio'), '--plugin', 'spark'],
                           input='', capture_output=True, text=True, env=env, timeout=15)
    assert child.returncode == 0, 'Spark console EOF smoke failed'
    assert child.stdout == '', 'non-protocol stdout'
    assert (Path(temporary) / 'l3' / '.lock').is_file()
    assert not list((Path(temporary) / 'l3').glob('.part-*'))
    print('Spark console EOF smoke: PASS (private temporary root, no upstream call)')
wheel = next((root / 'dist').glob('*.whl'))
with zipfile.ZipFile(wheel) as archive:
    names = set(archive.namelist())
    required = {'mcp_stdio/plugins/spark/' + name + '.py' for name in
                ('config', 'models', 'gateway', 'service', 'http_client', 'files', 'cache', 'tools', 'plugin')}
    assert required <= names
    print('Built wheel contains all Spark runtime modules: PASS')
PY
```

## Host environment note

The execution host repeatedly marked virtual-environment .pth files with the macOS hidden
flag. Python verbose startup showed it skipping the editable .pth, producing import failures.
`chflags nohidden .venv/lib/python3.12/site-packages/*.pth` confirmed the cause, but the tool
environment reapplied flags. Final development checks therefore explicitly use PYTHONPATH=src,
also inherited by test subprocesses. This is a host test workaround, not a product-code change
or production deployment instruction; README continues to require installed wheel releases.

## Remaining deployment validation

Supply a trusted CA where needed, inject the existing Cookie safely into SPARK_GATEWAY_COOKIE,
and explicitly enable the documented live test for the actual gateway. Automatic login,
insecure TLS and browser credential extraction are unsupported. Existing manually downloaded
ZIP files are not imported. Persistent directories are user-managed and retained until cleanup.
