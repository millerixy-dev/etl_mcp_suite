# Design

## Context

The Hive vertical slice established the plugin architecture pattern: each plugin owns its config model, domain models, application service, gateway port, external adapter, and MCP tool adapter, all behind the shared core's configuration loading and runtime lifecycle. The Zeppelin plugin has spec deltas and RED tests in the parent change but empty stubs. This slice implements Zeppelin following the same vertical-slice shape.

The Zeppelin REST API is execution-capable: callers create notebooks, add paragraphs, run them, and fetch results. Unlike Hive (metadata-only), Zeppelin executes caller-supplied paragraph content, so interpreter trust and input bounding are first-class safety concerns.

## Goals

- Ship a working, contract-tested Zeppelin plugin with the exact five-tool MCP surface.
- Default-deny interpreter execution: no paragraph body reaches Zeppelin unless the interpreter is explicitly allowlisted.
- Bound every input (names, titles, bodies, opaque IDs) and every output (result bytes), truncating rather than overflowing.
- Never expose cookies, headers, credentials, or unbounded upstream bodies.
- Reuse the shared core (config loader with env-prefix support, error categories, logging, stdio lifecycle) without modifying it.

## Decisions

### 1. Vertical slice shape (mirrors Hive)

```
zeppelin/
  config.py      - ZeppelinSettings (StrictConfigModel), ZeppelinSecrets (SecretConfigModel)
  models.py      - typed input validators, status mapping, immutable result models
  gateway.py     - ZeppelinGateway port (Protocol) + ZeppelinGatewayError
  http_client.py - async httpx adapter implementing the gateway; one lazy client per process
  service.py     - ZeppelinNotebookService (application service, SDK-independent)
  tools.py       - ZeppelinToolAdapter (FastMCP inbound adapter)
  plugin.py      - composition root: load_config -> adapter -> service -> tools -> runtime
```

Application service depends on the gateway Protocol and domain models only. The HTTP adapter depends on httpx. Tool adapter depends on FastMCP and the service. This preserves the Clean Architecture dependency direction already enforced by architecture tests.

### 2. Configuration

Inherits the shared loader (`load_config` with `env_prefix="ZEPPELIN"`). Settings are the closed V1 surface: `base_url` (HTTP/HTTPS, no userinfo/query/fragment, trailing slash normalized away), bounded numeric limits with defaults, and `allowed_interpreters` (default empty immutable, case-sensitive, unique, syntax `[A-Za-z][A-Za-z0-9_.-]{0,63}`).

Secrets are optional paired `username`/`password` environment-backed references: both absent (unauthenticated) or both present (session login); a partial pair fails closed. No token/basic-auth/cookie modes in V1.

### 3. Input validation without normalization

Notebook names and paragraph titles preserve original text (including surrounding whitespace) up to configured char limits. Paragraph bodies are bounded by UTF-8 byte length. Opaque IDs are bounded and reject Unicode control characters but preserve slash/traversal/query/fragment syntax as data - the adapter percent-encodes each ID as one path segment with no safe characters, so it cannot target a different REST path. Validation failures use fixed messages and never echo rejected input.

### 4. Tool flow and result normalization

- `create_notebook` -> POST notebook -> return `notebook_id`, `name`.
- `add_paragraph` -> validate interpreter against allowlist BEFORE network -> POST paragraph -> return `notebook_id`, `paragraph_id`, `title`, `interpreter`.
- `run_paragraph` -> POST run -> return acknowledgement/current normalized state without polling to completion.
- `get_paragraph_status` -> GET status -> map to `PENDING|RUNNING|FINISHED|ERROR|CANCELLED|UNKNOWN`.
- `get_paragraph_result` -> GET result -> normalize outputs up to `max_result_bytes`, set `truncated`, include safe failure details for `ERROR` state.

Result models are strict, frozen, JSON-serializable, and contain no raw HTTP artifacts.

### 5. HTTP adapter

One lazily constructed async httpx client per process, closed in `runtime.close()`. Opaque IDs are path-segment-encoded. Responses are bounded by `max_response_bytes` during read. Timeouts use `request_timeout_seconds`. On auth failure return `AUTHENTICATION_FAILED` without retrying execution; on timeout return `TIMEOUT`; on connection failure return `CONNECTION_FAILED`. Backend exceptions are mapped at the adapter boundary; no raw exception representation reaches MCP clients.

### 6. Authentication lifecycle

When credentials are configured, the adapter performs Zeppelin session login lazily on the first authenticated request and reuses the session within the process. If the session expires (Zeppelin rejects it), the current operation returns `AUTHENTICATION_FAILED` without exposing cookies or automatically repeating the request. Unauthenticated config skips login entirely.

### 7. Environment-variable-only startup

Zeppelin declares `env_prefix="ZEPPELIN"`, so `ZEPPELIN_BASE_URL`, `ZEPPELIN_ALLOWED_INTERPRETERS`, `ZEPPELIN_USERNAME`, `ZEPPELIN_PASSWORD`, etc. can start the process without a `--config` file, consistent with the `support-env-var-configuration` change.

## Risks

- Interpreter allowlist is a deployment trust decision; allowing `sh` is high-risk and documented as such. The default empty list forces explicit opt-in.
- Zeppelin REST response shapes vary across versions; the adapter normalizes defensively and returns `UNKNOWN` status for unrecognized states rather than crashing.
- Session/cookie handling must stay inside the adapter and never surface in tool results or logs.

## Zeppelin 0.10.1 REST API (verified)

Captured against a live Zeppelin 0.10.1 server. These are the authoritative upstream endpoints; the adapter MUST use exactly these paths and response shapes.

### Authentication
- `POST /api/login` with form-encoded body `userName=<user>&password=<pass>` (Content-Type `application/x-www-form-urlencoded`).
- Returns `{"status":"OK","body":{"principal":"<user>","ticket":"<uuid>","roles":"[...]"}}`.
- Sets an HttpOnly `JSESSIONID` cookie; all subsequent requests carry it via the httpx client cookie jar. No separate bearer token or header.

### Endpoints and response shapes

| Operation | Method | Path | Request | Response `body` |
|---|---|---|---|---|
| Create notebook | POST | `/api/notebook` | `{"name":"<name>"}` | **string** notebook ID |
| Add paragraph | POST | `/api/notebook/{nbId}/paragraph` | `{"title":"<title>","text":"<body>"}` | **string** paragraph ID |
| Run paragraph | POST | `/api/notebook/job/{nbId}/{pId}` | (empty) | `{"status":"OK"}` - no body field; fire-and-forget, poll separately |
| Get paragraph | GET | `/api/notebook/{nbId}/paragraph/{pId}` | - | object (see below) |
| Get notebook | GET | `/api/notebook/{nbId}` | - | object with `paragraphs[]`, `name`, `id`, `defaultInterpreterGroup` |
| Delete notebook | DELETE | `/api/notebook/{nbId}` | - | `{"status":"OK"}` |
| List notebooks | GET | `/api/notebook` | - | array of `{"id":"<id>","path":"<path>"}` |

### Paragraph object shape
```
{
  "id": "<paragraphId>",
  "title": "<title>",
  "text": "<body>",
  "status": "RUNNING|FINISHED|ERROR|READY|PENDING|ABORT",
  "results": {
    "code": "SUCCESS|ERROR",
    "msg": [ {"type":"TEXT|HTML|...","data":"<string>"} ],
    "exception": "..."   // present on error
  },
  "dateStarted": "...", "dateFinished": "...", "progress": 0.0,
  ...
}
```

### Status normalization mapping (0.10.1)
| Upstream string | Normalized |
|---|---|
| `READY`, `PENDING` | `PENDING` |
| `RUNNING` | `RUNNING` |
| `FINISHED` | `FINISHED` |
| `ERROR` | `ERROR` |
| `ABORT` | `CANCELLED` |
| (anything else) | `UNKNOWN` |

### Interpreter selection
0.10.1 selects the interpreter per-paragraph via a shebang prefix in the paragraph text (e.g. `%sh\necho hi`) or falls back to the notebook's `defaultInterpreterGroup`. The V1 allowlist validates the interpreter name BEFORE the paragraph is sent; the adapter prepends the shebang to the body when the caller-supplied interpreter differs from the notebook default. This is captured as an adapter detail, not a spec-level requirement, since the spec speaks of "interpreter name" validation generically.

### Result normalization
`results.msg[]` entries are flattened into bounded output items preserving `type` and `data` (UTF-8 byte-bounded, truncated at `max_result_bytes` with the `truncated` flag). `results.code == "ERROR"` drives the `ERROR` status with safe failure details from `results.exception` (bounded, no credentials).
