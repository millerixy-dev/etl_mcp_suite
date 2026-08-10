## Context

The shared stdio runtime, configuration loader, error and logging boundary, explicit registry, Hive vertical slice, and Zeppelin vertical slice are implemented. The `build-plugin-mcp-stdio` parent change already specifies the DolphinScheduler V1 capability surface (a single status tool, a deployment-configured status path, environment-backed authentication, response normalization, and HTTP client cleanup) and carries empty stubs plus a `NotImplementedError` runtime builder in `src/mcp_stdio/plugins/dolphinscheduler/`. The registry already imports the `dolphinscheduler` definition. Those stubs have no implementation and no tests, blocking the parent change's section 5 from closing. The parent design intentionally deferred the exact DolphinScheduler REST API facts; this slice captures the DolphinScheduler 3.1.7 monitor API and implements the plugin following the same vertical-slice shape as Hive and Zeppelin.

DolphinScheduler 3.1.7 is observational in V1: the plugin exposes server status only and performs no workflow, task, project, schedule, definition, or instance operations.

## Goals / Non-Goals

**Goals:**

- Ship a working, contract-tested DolphinScheduler plugin with the exact one-tool MCP surface `get_server_status` and no input arguments.
- Capture the DolphinScheduler 3.1.7 monitor REST API facts (context path, authentication, endpoints, response envelope, server model) as implementation source of truth.
- Normalize the 3.1.7 `Result` envelope and server list into safe, bounded detail fields without exposing headers, cookies, credentials, the DolphinScheduler `msg` field, or unbounded upstream bodies.
- Authenticate each request with a `token` HTTP header sourced from an environment-backed secret; map HTTP 401 to `AUTHENTICATION_FAILED` and other transport/business failures to safe categories.
- Reuse the shared core (`load_config` with `env_prefix="DOLPHINSCHEDULER"`, error categories, logging, stdio lifecycle) and the existing `httpx` dependency without modifying the core or adding a new third-party dependency.

**Non-Goals:**

- Workflow, task, project, schedule, definition, or instance operations.
- DolphinScheduler `POST /dolphinscheduler/login` session-cookie authentication, LDAP, or token refresh.
- Querying `/monitor/databases` or `/monitor/workers` as separate tools; only the single configured status path is queried.
- Pagination, long-polling, or automatic retries with side effects.
- HTTP/SSE MCP transport or opening an MCP listening port.

## Decisions

### 1. Vertical slice shape (mirrors Hive and Zeppelin)

```text
dolphinscheduler/
  config.py      - DolphinSchedulerSettings (StrictConfigModel), DolphinSchedulerSecrets (SecretConfigModel)
  gateway.py     - DolphinSchedulerGateway port (Protocol) + DolphinSchedulerGatewayError
  http_client.py - async httpx adapter implementing the gateway; one lazy client per process
  service.py     - DolphinSchedulerStatusService (application service, SDK-independent) + ServerStatusResult
  tools.py       - DolphinSchedulerToolAdapter (FastMCP inbound adapter)
  plugin.py      - composition root: load_config -> adapter -> service -> tools -> runtime
```

The application service depends on the gateway Protocol and the immutable `ServerStatusResult` only. The HTTP adapter depends on `httpx`. The tool adapter depends on FastMCP and the service. This preserves the Clean Architecture dependency direction already enforced by architecture tests. No `models.py` is needed because the plugin has no caller inputs and a single small result model; the result model lives in `service.py` (the parent design's layout is respected, and a split is deferred until size warrants it).

### 2. Configuration

The plugin uses the shared loader (`load_config` with `env_prefix="DOLPHINSCHEDULER"` and `expected_plugin="dolphinscheduler"`). Configuration comes from a versioned YAML/JSON file passed with `--config`, OR from environment variables only (no `--config`). When both are present, environment variables take precedence over file values. All validation runs locally with no network access.

#### Settings (non-sensitive)

| Field | Type | Default | Range | Required |
|---|---|---|---|---|
| `base_url` | string | - | absolute `http`/`https`, no userinfo/query/fragment; trailing slash stripped | yes |
| `status_path` | string | `/monitor/masters` | must start with `/`; no `?` or `#` | no |
| `request_timeout_seconds` | number | `30` | `> 0` and `<= 300` | no |
| `max_response_bytes` | int | `1048576` (1 MiB) | `1` to `8388608` (8 MiB) | no |
| `max_detail_items` | int | `100` | `1` to `1000` | no |

`base_url` includes the DolphinScheduler context path `/dolphinscheduler` (default API port 12345). `status_path` is queried relative to `base_url`, so the full status URL is `base_url + status_path`, for example `http://ds-host:12345/dolphinscheduler/monitor/masters`.

#### Secrets (environment-backed only)

| Field | Default | Meaning |
|---|---|---|
| `token` | `None` | In a file this is an **environment variable name** (not a value); the runtime resolves it at startup. Empty/omitted means unauthenticated. |

When `token` is resolved, the adapter sends it as a DolphinScheduler `token` HTTP header on every status request. The token value never appears in tool schemas, results, errors, stdout, or logs.

#### File example (`docs/examples/dolphinscheduler.yaml`)

```yaml
version: 1
plugin: dolphinscheduler
settings:
  base_url: http://ds-host:12345/dolphinscheduler
  status_path: /monitor/masters        # optional, defaults to /monitor/masters
  request_timeout_seconds: 30          # optional
  max_response_bytes: 1048576          # optional
  max_detail_items: 100                # optional
secrets:
  token: DOLPHINSCHEDULER_TOKEN        # env var NAME holding the actual token
```

Start with the file and export the referenced variable:

```bash
export DOLPHINSCHEDULER_TOKEN=<your-dolphinscheduler-api-token>
mcp-stdio --plugin dolphinscheduler --config /path/to/dolphinscheduler.yaml
```

#### Environment-variable-only example (no `--config`)

Omit `--config` and set `DOLPHINSCHEDULER_<FIELD>` variables. Settings use the field value directly; the secret variable holds the **actual token value**.

| Field | Variable | Required |
|---|---|---|
| `settings.base_url` | `DOLPHINSCHEDULER_BASE_URL` | yes |
| `settings.status_path` | `DOLPHINSCHEDULER_STATUS_PATH` | no |
| `settings.request_timeout_seconds` | `DOLPHINSCHEDULER_REQUEST_TIMEOUT_SECONDS` | no |
| `settings.max_response_bytes` | `DOLPHINSCHEDULER_MAX_RESPONSE_BYTES` | no |
| `settings.max_detail_items` | `DOLPHINSCHEDULER_MAX_DETAIL_ITEMS` | no |
| `secrets.token` | `DOLPHINSCHEDULER_TOKEN` | no (omit for unauthenticated) |

```bash
export DOLPHINSCHEDULER_BASE_URL=http://ds-host:12345/dolphinscheduler
export DOLPHINSCHEDULER_TOKEN=<your-dolphinscheduler-api-token>
mcp-stdio --plugin dolphinscheduler
```

Unknown fields, type coercion, unsafe URLs/paths, and out-of-range limits are rejected with `CONFIG_ERROR` at startup without echoing any secret value.

### 3. DolphinScheduler 3.1.7 authentication

DolphinScheduler 3.1.7 authenticates API requests through `LoginHandlerInterceptor.preHandle`, which reads the `token` HTTP header (`request.getHeader("token")`) and resolves the user via `userMapper.queryUserByToken(token, date)`. A missing, invalid, or expired token causes the interceptor to set HTTP 401 (`response.setStatus(HttpStatus.SC_UNAUTHORIZED)`) and abort the request with no response body. A disabled user is likewise rejected with HTTP 401.

The V1 adapter uses token-header authentication exclusively. It does not perform session-cookie login, does not store cookies, and does not refresh tokens. If the configured `token` is absent, requests are sent without the `token` header and the deployment's 401 response is surfaced as `AUTHENTICATION_FAILED` at call time (startup still succeeds, consistent with the lazy-connection runtime requirement).

### 4. Status endpoint and response envelope

DolphinScheduler 3.1.7 exposes monitor endpoints under the `/dolphinscheduler` context path (default API port 12345), all requiring authentication:

| Operation | Method | Path | `Result.data` shape |
|---|---|---|---|
| List master servers | GET | `/dolphinscheduler/monitor/masters` | array of `Server` |
| List worker servers | GET | `/dolphinscheduler/monitor/workers` | array of `WorkerServerModel` |
| Query database state | GET | `/dolphinscheduler/monitor/databases` | array of `MonitorRecord` |

Every monitor endpoint returns the `Result<T>` envelope:

```json
{
  "code": 0,
  "msg": "success",
  "data": []
}
```

`Status.SUCCESS` is code `0`. The default `status_path` is `/monitor/masters`, which lists registered master servers from the registry (Zookeeper). A non-empty master list indicates an operational scheduler; an empty list indicates no master is registered (the API server is reachable but the cluster cannot schedule).

`Server` model (master):

```json
{ "id": 1, "host": "192.168.1.1", "port": 5678, "zkDirectory": "/dolphinscheduler/nodes/master/...",
  "resInfo": "...", "createTime": "...", "lastHeartbeatTime": "..." }
```

`WorkerServerModel` (worker):

```json
{ "id": 1, "host": "192.168.1.2", "port": 1234, "zkDirectories": ["..."],
  "resInfo": "...", "createTime": "...", "lastHeartbeatTime": "..." }
```

`resInfo` is a free-form resource string (CPU and memory usage) carrying no credentials; it is passed through bounded and truncated, not parsed. Relevant `Status` enum codes: `SUCCESS(0)`, `USER_LOGIN_FAILURE(10043)`, `LIST_MASTERS_ERROR(10045)`, `USER_DISABLED(10148)`, `USER_NO_OPERATION_PERM(30001)`.

### 5. Status normalization

The `get_server_status` tool performs an authenticated HTTP GET to `base_url + status_path`, reads at most `max_response_bytes`, and normalizes:

- HTTP 2xx with `code == 0` and `data` a list:
  - `available = true`
  - `status = "HEALTHY"` when the list is non-empty, `"UNHEALTHY"` when empty
  - `server_count` = number of summaries returned (bounded by `max_detail_items`)
  - `servers` = first `max_detail_items` entries, each reduced to safe fields `host`, `port`, `res_info` (bounded), `last_heartbeat_time`; unknown fields are dropped
- HTTP 2xx with `code != 0` -> `UPSTREAM_ERROR` with a concise safe message (the `msg` is bounded and never includes credentials)
- HTTP 2xx whose body is not a valid `Result` envelope or whose `data` is not a list -> `UNEXPECTED_RESPONSE`

`available` reflects whether the DolphinScheduler API responded successfully (code 0); `status` reflects the health of the monitored component. The DolphinScheduler `msg` field is not returned in the success result.

### 6. Error mapping

| Condition | Category |
|---|---|
| Connection refused / DNS failure / network unreachable | `CONNECTION_FAILED` |
| Request exceeds `request_timeout_seconds` | `TIMEOUT` |
| HTTP 401 | `AUTHENTICATION_FAILED` |
| HTTP 403 | `PERMISSION_DENIED` |
| HTTP 5xx | `UPSTREAM_ERROR` |
| HTTP 2xx with non-zero `Result.code` | `UPSTREAM_ERROR` |
| Unparseable body or non-list `data` | `UNEXPECTED_RESPONSE` |
| Other uncaught exception | generic safe error + stderr correlation ID |

No raw HTTP client exception representation, response headers, cookies, credentials, or unbounded body reaches the MCP client.

### 7. HTTP adapter and lifecycle

One lazily constructed async `httpx.AsyncClient` per process, closed in `runtime.close()`. Responses are bounded by `max_response_bytes` during read. Timeouts use `request_timeout_seconds`. The `token` header is added only when a token is configured. The client is constructed lazily on the first tool call (no network access during startup validation), mirroring the Zeppelin adapter's lazy-construction and cleanup shape.

### 8. Tool surface

Exactly one tool `get_server_status` with no input arguments. The contract test asserts the single-tool set and the absence of any workflow/task/project/schedule/instance/definition tool. The tool result shape is:

```json
{
  "available": true,
  "status": "HEALTHY",
  "server_count": 1,
  "servers": [
    { "host": "192.168.1.1", "port": 5678,
      "res_info": "...",
      "last_heartbeat_time": "..." }
  ]
}
```

## Risks / Trade-offs

- **[DolphinScheduler returns HTTP 401 with no body on auth failure]** -> The adapter maps HTTP 401 to `AUTHENTICATION_FAILED` and does not attempt to parse a missing body; no retry is performed.
- **[DolphinScheduler business errors use HTTP 200 with a non-zero `Result.code`]** -> The adapter inspects `Result.code` after a 2xx response and maps non-zero codes to `UPSTREAM_ERROR` rather than treating 200 as unconditional success.
- **[The configurable status path could point at an endpoint with a different `data` shape]** -> The normalizer requires `data` to be a list and otherwise returns `UNEXPECTED_RESPONSE`; the default `/monitor/masters` and the sibling `/monitor/workers` both return lists of server-like objects, while `/monitor/databases` returns a different shape and would fail closed.
- **[A single configurable path checks only masters or workers, not both]** -> Accepted for V1 observational scope; the deployer chooses the path. Querying multiple endpoints or adding worker-specific detail is a future change.
- **[`resInfo` is a free-form string of unbounded length]** -> It is bounded and truncated at read/normalize time with no parsing, so it cannot overflow the response.
