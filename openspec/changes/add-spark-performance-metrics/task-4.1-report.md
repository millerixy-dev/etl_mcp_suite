# Task 4.1 verification evidence

OpenSpec tasks.md remains the controller-owned acceptance checklist. Final integrated verification and whole-change review are pending task 3.2 completion; the independent local read-only sample check below is already executed.

## Local real-snapshot check

Executed `UV_NO_EDITABLE=1 uv run --locked --no-sync python` against two existing private cached manifests. Existing SparkEventLogAdapter supplied exclusive directory ownership with empty SparkSecrets and an HTTP MockTransport that rejects any request; the shared SparkInspectionAdapter supplied Stage metrics, selected-Stage distribution and query ref rereading. No authentication configuration or credentials were read and no upstream request occurred.

| Application / attempt | JSONL bytes | Stage attempts | Selected Stage / attempt | Stage duration ms | TaskEnd / Success | Duration P50 / P95 ms | Stage seconds | Distribution seconds |
| --- | ---: | ---: | --- | ---: | --- | --- | ---: | ---: |
| application_1783000588461_681757 / 1 | 4008504 | 7 | 0 / 0 | 84171 | 200 / 200 | 640 / 5565 | 0.076 | 0.065 |
| application_1783000588461_687089 / 2 | 6205392 | 2 | 0 / 0 | 89351 | 1500 / 1500 | 2186 / 3714 | 0.116 | 0.101 |

Independent raw JSONL traversal checked SHA-256, selected-group TaskEnd and Success counts, timestamp-derived duration samples and nearest-rank P50/P95 against returned values. Top TaskEnd refs were reread through query using the same digest and matched direct task ID/ref. Evidence bytes and mtime remained unchanged. Ownership was closed after each run; HTTP requests: zero.

Process peak was 45.44 MiB on macOS, including interpreter/imports and the independent verification pass; it is not incremental parser memory. These are approximately 4 MB and 6 MB successful snapshots, not a 100 MB benchmark, live-backend/authentication test, deployed-host test or proof of a production root cause. Only safe counts/times were recorded; real event bodies were not added to the repository.

## Final integrated results

The controller will record fresh suite, lint, type, build, smoke, strict validation and whole-change review results here before gating task 4.1.

## Configuration example correction

The existing file-mode loader requires an explicit secrets mapping even for credential-free reads. A local `load_config(..., environ={})` check of the proposed settings-only JSON rejected it with `CONFIG_ERROR: secrets must be an object`; adding `secrets: {}` was accepted. The active design's field table and YAML example were corrected to document this existing requirement. No configuration behavior, credential, network request or production code changed.
