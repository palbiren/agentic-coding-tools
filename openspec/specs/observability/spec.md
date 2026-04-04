# observability Specification

## Purpose
OpenTelemetry observability for the agent-coordinator: metrics, traces, and Prometheus export for locks, work queue, and policy evaluation.
## Requirements
### Requirement: Telemetry Module and Configuration

The coordinator SHALL provide a `telemetry` module that initializes OpenTelemetry MeterProvider and TracerProvider based on environment configuration, with zero overhead when disabled.

- The telemetry module SHALL expose named meters: `coordinator.locks`, `coordinator.queue`, `coordinator.policy`
- When `OTEL_METRICS_ENABLED` is not `true`, all metric instruments SHALL be no-ops with zero measurable overhead
- OTel dependencies MUST be in an optional extras group (`[observability]`) to avoid bloating the core install
- The `init_telemetry()` function SHALL be called during MCP server and HTTP API startup

#### Scenario: Telemetry enabled with OTLP exporter
- **WHEN** `OTEL_METRICS_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317`
- **THEN** system initializes MeterProvider with OTLP exporter
- **AND** named meters `coordinator.locks`, `coordinator.queue`, `coordinator.policy` are available
- **AND** metric instruments record values to the configured exporter

#### Scenario: Telemetry disabled (default)
- **WHEN** `OTEL_METRICS_ENABLED` is not set or is `false`
- **THEN** system initializes no-op MeterProvider
- **AND** all metric record calls are zero-cost no-ops
- **AND** no network connections are established to any exporter

---

### Requirement: Lock Contention Metrics

`LockService` SHALL emit OpenTelemetry metrics and traces for lock acquisition, contention, and lifecycle tracking.

- `LockService.acquire()` SHALL record a histogram `lock.acquire.duration_ms` with labels `outcome` and `agent_type`
- `LockService.acquire()` SHALL increment `lock.contention.total` when a lock request is denied due to an existing holder
- `LockService.acquire()` and `release()` SHALL maintain an UpDownCounter `lock.active` tracking currently held locks
- `LockService.acquire()` SHALL create a tracing span `lock.acquire` with structured attributes

#### Scenario: Successful lock acquisition records metrics
- **WHEN** agent `claude-code-1` of type `claude_code` acquires lock on `src/api/users.py`
- **THEN** `lock.acquire.duration_ms` histogram records the RPC duration with `outcome=acquired`, `agent_type=claude_code`
- **AND** `lock.active` UpDownCounter increments by 1

#### Scenario: Lock contention recorded
- **WHEN** agent `codex-1` attempts to acquire lock on `src/api/users.py` already held by `claude-code-1`
- **THEN** `lock.contention.total` counter increments with `holder_type=claude_code`, `requester_type=codex`
- **AND** `lock.acquire.duration_ms` histogram records with `outcome=denied`

#### Scenario: Lock release decrements active gauge
- **WHEN** agent releases lock on `src/api/users.py`
- **THEN** `lock.active` UpDownCounter decrements by 1

---

### Requirement: Queue Latency Metrics

`WorkQueueService` SHALL emit OpenTelemetry metrics and traces for task lifecycle latency, submission rates, and guardrail blocks.

- `WorkQueueService.claim()` SHALL record `queue.claim.duration_ms` with labels `task_type` and `outcome`
- `WorkQueueService.claim()` SHALL record `queue.wait_time_ms` (time from task creation to claim) when a task is successfully claimed
- `WorkQueueService.complete()` SHALL record `queue.task.duration_ms` (time from claim to completion) with labels `task_type` and `outcome`
- `WorkQueueService.submit()` SHALL increment `queue.submit.total` with label `task_type`
- `WorkQueueService.claim()` SHALL increment `queue.guardrail_block.total` when a guardrail check blocks task execution

#### Scenario: Task claimed with wait time
- **WHEN** task of type `verify` submitted at T0 is claimed at T1 by agent
- **THEN** `queue.claim.duration_ms` histogram records RPC duration with `task_type=verify`, `outcome=claimed`
- **AND** `queue.wait_time_ms` histogram records `T1 - T0` in milliseconds with `task_type=verify`

#### Scenario: Task completion records duration
- **WHEN** agent completes task claimed at T1, completing at T2 with success
- **THEN** `queue.task.duration_ms` histogram records `T2 - T1` with `task_type=verify`, `outcome=completed`

#### Scenario: Guardrail blocks task execution
- **WHEN** claimed task description matches guardrail pattern `rm_rf`
- **THEN** `queue.guardrail_block.total` counter increments with `pattern=rm_rf`
- **AND** task is auto-released with failure

---

### Requirement: Policy Evaluation Metrics

`PolicyEngine` and `GuardrailsService` SHALL emit OpenTelemetry metrics and traces for evaluation latency, decision outcomes, cache performance, and violation detection.

- `PolicyEngine.check_operation()` SHALL record `policy.evaluate.duration_ms` with labels `engine`, `operation`, and `decision`
- `CedarPolicyEngine._load_policies()` SHALL track `policy.cache.total` with label `result` in {`hit`, `miss`}
- `GuardrailsService.check_operation()` SHALL record `guardrail.check.duration_ms` and increment `guardrail.violation.total` per detected pattern
- Policy evaluation SHALL create tracing spans `policy.evaluate` and `guardrail.check`

#### Scenario: Native policy evaluation recorded
- **WHEN** native policy engine evaluates `acquire_lock` operation for agent with trust level 2
- **THEN** `policy.evaluate.duration_ms` histogram records with `engine=native`, `operation=acquire_lock`, `decision=allow`
- **AND** `policy.decision.total` counter increments with same labels

#### Scenario: Cedar policy cache hit
- **WHEN** CedarPolicyEngine evaluates an operation and cached policies are within TTL
- **THEN** `policy.cache.total` counter increments with `result=hit`
- **AND** no database query is made to load policies

#### Scenario: Guardrail violation detected
- **WHEN** guardrail check detects `force_push` pattern with `severity=block`
- **THEN** `guardrail.violation.total` counter increments with `pattern=force_push`, `severity=block`
- **AND** `guardrail.check.duration_ms` histogram records the check duration

---

### Requirement: Prometheus Metrics Endpoint

When enabled, the HTTP API SHALL expose a `/metrics` endpoint returning Prometheus text format metrics.

- When `PROMETHEUS_ENABLED=true`, the HTTP API SHALL expose a `/metrics` endpoint
- The `/metrics` endpoint SHALL NOT require authentication
- The `/metrics` endpoint MUST NOT expose sensitive data (agent IDs, file paths, task descriptions)

#### Scenario: Prometheus endpoint returns metrics
- **WHEN** `PROMETHEUS_ENABLED=true` and coordinator has processed operations
- **THEN** `GET /metrics` returns HTTP 200 with `Content-Type: text/plain`
- **AND** response contains `lock_acquire_duration_ms`, `queue_claim_duration_ms`, `policy_evaluate_duration_ms` metric families

#### Scenario: Prometheus endpoint disabled by default
- **WHEN** `PROMETHEUS_ENABLED` is not set
- **THEN** `GET /metrics` returns HTTP 404

### Requirement: Langfuse Tracing Module

The coordinator SHALL provide a Langfuse tracing module (`langfuse_tracing.py`) that manages a lazy-initialized Langfuse client, disabled by default.

- The module SHALL initialize the Langfuse client only when `LANGFUSE_ENABLED=true`
- The module SHALL be idempotent — calling `init_langfuse()` multiple times SHALL be a no-op after first initialization
- When `langfuse` package is not installed, initialization SHALL log a warning and fall back to no-op (no crash)
- When initialization fails for any reason, the module SHALL fall back to no-op and log a warning
- The module SHALL provide `create_trace()`, `create_span()`, and `end_span()` helpers that return `None` when disabled
- The module SHALL provide a `trace_operation()` context manager that creates a trace, yields it, records errors on exception, and flushes on exit
- The module SHALL provide `shutdown_langfuse()` that flushes pending events and releases the client
- The Langfuse client SHALL be initialized with `public_key`, `secret_key`, `host`, and `debug` from `LangfuseConfig`
- An empty `public_key` SHALL NOT cause a crash during initialization logging

#### Scenario: Langfuse disabled by default
- **WHEN** `LANGFUSE_ENABLED` is not set or is `false`
- **THEN** `init_langfuse()` sets `_langfuse = None`
- **AND** `get_langfuse()` returns `None`
- **AND** all trace/span helpers return `None` with zero overhead

#### Scenario: Langfuse enabled with valid config
- **WHEN** `LANGFUSE_ENABLED=true` and `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set
- **THEN** `init_langfuse()` creates a Langfuse client
- **AND** `get_langfuse()` returns the client instance
- **AND** `create_trace()` returns a trace object

#### Scenario: Langfuse package not installed
- **WHEN** `LANGFUSE_ENABLED=true` but `langfuse` package is not importable
- **THEN** initialization logs a warning with install instructions
- **AND** `get_langfuse()` returns `None`

#### Scenario: trace_operation records errors
- **WHEN** an exception is raised inside a `trace_operation()` context
- **THEN** the trace is updated with `level=ERROR` and the error message in output
- **AND** the exception is re-raised

### Requirement: Langfuse Configuration

The coordinator SHALL provide a `LangfuseConfig` dataclass with environment-based configuration for Langfuse integration.

- `LANGFUSE_ENABLED` (default: `false`) — master enable/disable toggle
- `LANGFUSE_PUBLIC_KEY` (default: `pk-lf-local-coding-agents`) — project public key
- `LANGFUSE_SECRET_KEY` (default: `sk-lf-local-coding-agents`) — project secret key
- `LANGFUSE_HOST` (default: `http://localhost:3050`) — Langfuse server URL
- `LANGFUSE_TRACE_API_REQUESTS` (default: `true`) — enable/disable HTTP request tracing middleware
- `LANGFUSE_DEBUG` (default: `false`) — enable SDK debug logging

#### Scenario: Default configuration
- **WHEN** no Langfuse environment variables are set
- **THEN** `LangfuseConfig.from_env()` returns `enabled=False`
- **AND** all other fields have sensible defaults for local development

#### Scenario: Trace API requests toggle
- **WHEN** `LANGFUSE_TRACE_API_REQUESTS=false`
- **THEN** the HTTP tracing middleware SHALL NOT be registered on the FastAPI app

### Requirement: HTTP Request Tracing Middleware

The coordinator HTTP API SHALL provide optional Langfuse middleware that traces API requests from cloud agents.

- The middleware SHALL create a Langfuse trace per request with operation name `api:<path>`
- The middleware SHALL resolve agent identity from the `X-API-Key` header via config
- The middleware SHALL skip tracing for health/metrics/docs paths (`/health`, `/metrics`, `/docs`, `/openapi.json`, `/redoc`)
- The middleware SHALL capture HTTP method, path, agent ID, session ID (from `X-Session-Id` header), status code, and duration
- The middleware SHALL finalize traces with `level=ERROR` for 5xx, `WARNING` for 4xx, `DEFAULT` otherwise
- The middleware SHALL finalize traces even when `call_next` raises an exception (recording status 500)
- The middleware SHALL NOT flush Langfuse per-request — it SHALL rely on SDK batching and shutdown flush
- The middleware SHALL only be registered when `get_langfuse() is not None` AND `config.langfuse.trace_api_requests` is `True`
- Agent identity resolution failures SHALL NOT crash the request — fall back to `"cloud-agent"`

#### Scenario: API request traced
- **WHEN** a cloud agent sends `POST /locks/acquire` with `X-API-Key: key1`
- **THEN** middleware creates a trace named `api:locks/acquire` with `user_id` resolved from key1
- **AND** a span is created for `POST /locks/acquire`
- **AND** trace and span are finalized with status code, duration, and level

#### Scenario: Health check not traced
- **WHEN** a request is made to `GET /health`
- **THEN** no Langfuse trace is created
- **AND** the request passes through to the handler directly

#### Scenario: Middleware handles downstream errors
- **WHEN** `call_next` raises an unhandled exception
- **THEN** the trace is finalized with status 500 and `level=ERROR`
- **AND** the exception is re-raised to the ASGI error handler

### Requirement: Claude Code Session Tracing Hook

The coordinator SHALL provide a Claude Code Stop hook (`langfuse_hook.py`) that sends session transcripts to Langfuse incrementally.

- The hook SHALL only run when `LANGFUSE_ENABLED=true` and both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set
- The hook SHALL find the most recently modified transcript file under `~/.claude/projects/`
- The hook SHALL track processing state per session in `~/.claude/state/langfuse_state_<hash>.json`
- The hook SHALL advance the state cursor by **lines consumed** (not messages parsed) to handle blank and invalid JSON lines correctly
- The hook SHALL group messages into conversation turns (user → assistant + tool calls)
- The hook SHALL create a Langfuse trace per turn with user input, assistant output, model info, and tool call spans
- The hook SHALL sanitize all text before sending to Langfuse, redacting:
  - Anthropic/OpenAI API keys (`sk-*`)
  - Langfuse keys (`pk-lf-*`, `sk-lf-*`)
  - Supabase service keys (`sbp_*`)
  - JWT tokens (`eyJ*`)
  - Bearer tokens
  - Generic key=value secret patterns (`password=`, `secret=`, `token=`, `api_key=`, `apikey=`)
- Sanitization patterns SHALL be ordered from most specific to most general to preserve descriptive redaction markers
- The hook SHALL create the Langfuse client with `timeout=5` to limit blocking when the server is unreachable
- The hook SHALL handle client creation failures gracefully (log warning, return 0)
- The hook SHALL advance the cursor even when no complete turns are found (to avoid re-reading orphan messages)

#### Scenario: Incremental transcript processing
- **WHEN** the hook runs and the transcript has 10 new lines since last run, 2 of which are blank
- **THEN** the hook processes 8 valid messages
- **AND** advances the cursor by 10 (lines consumed, not messages parsed)

#### Scenario: Secret sanitization
- **WHEN** a tool output contains `sk-lf-local-coding-agents` and `password=secret123`
- **THEN** the Langfuse trace input/output contains `LF-KEY-REDACTED` and `password=REDACTED`
- **AND** the original secret values do not appear in the Langfuse trace

#### Scenario: Langfuse server unreachable
- **WHEN** `LANGFUSE_ENABLED=true` but the Langfuse server at `LANGFUSE_HOST` is not reachable
- **THEN** the hook logs a warning and returns without sending traces
- **AND** the state cursor is NOT advanced (so messages will be retried on next run)

### Requirement: Self-Hosted Langfuse Stack

The docker-compose file SHALL support a self-hosted Langfuse v3 stack behind a `langfuse` profile.

- The stack SHALL include: Langfuse web, Langfuse worker, ClickHouse, Redis, MinIO
- The stack SHALL reuse the existing Postgres service (creating a separate `langfuse` database via init container)
- The stack SHALL be gated behind the `langfuse` Docker profile — not started by default
- The stack SHALL auto-provision a default project with known API keys for local development
- The Langfuse UI SHALL be accessible at `http://localhost:${LANGFUSE_PORT:-3050}`

#### Scenario: Start Langfuse stack
- **WHEN** operator runs `docker compose --profile langfuse up -d`
- **THEN** Langfuse web, worker, ClickHouse, Redis, and MinIO containers start
- **AND** a `langfuse` database is created in Postgres if it doesn't exist
- **AND** a default project is provisioned with `pk-lf-local-coding-agents` / `sk-lf-local-coding-agents`

#### Scenario: Default profile excludes Langfuse
- **WHEN** operator runs `docker compose up -d` without `--profile langfuse`
- **THEN** no Langfuse-related containers are started

### Requirement: Setup Script

The coordinator SHALL provide a setup script (`setup_langfuse.sh`) for configuring Langfuse integration.

- `--local` mode SHALL start the self-hosted stack and install the Claude Code hook
- `--cloud` mode SHALL configure for Langfuse Cloud (override localhost default to `https://cloud.langfuse.com`)
- `--cloud` mode SHALL require non-default `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`
- `--install-hook` mode SHALL install only the Claude Code hook without starting services
- The setup script SHALL detect when `LANGFUSE_HOST` still has the localhost default in `--cloud` mode and override it

#### Scenario: Cloud mode overrides localhost host
- **WHEN** operator runs `setup_langfuse.sh --cloud` without exporting `LANGFUSE_HOST`
- **THEN** the script sets `LANGFUSE_HOST=https://cloud.langfuse.com`
- **AND** the hook is configured to send traces to Langfuse Cloud

