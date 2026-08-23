# Taskflow Operations

## Runtime

Taskflow runs as a Docker container and is configured for Fly.io. Local development uses `./start.sh` on port 8000.

Copy `.env.local.example` to `.env.local` for local configuration.

## Provider Modes

- `LLM_PROVIDER=mock` is the deterministic default.
- `LLM_PROVIDER=openai` requires `OPENAI_API_KEY` and the optional OpenAI dependency group.
- `LLM_PROVIDER=anthropic` requires `ANTHROPIC_API_KEY` and the optional Anthropic dependency group.

An explicitly selected real provider fails at startup when its package or credentials are missing. It does not silently fall back to mock.

Model names and per-1K-token rates are configurable for cheap, default, and expensive routes. Cost values are estimates based on configured rates.

## Run Guardrails

Default run constraints:

- Budget: USD 2.00
- Timeout: 300 seconds
- Maximum steps: 30
- Reflection interval: every 2 completed steps

Run requests may override these values. The monitor evaluates cost, elapsed time, progress, cancellation, terminal node state, and reflection conditions after planning and each step.

## Persistence and Recovery

SQLite stores control-plane state on the local filesystem. The in-memory event broker is not durable, but SSE subscribers first receive database events before live events.

Startup attempts to resume incomplete runs when the same database is still available. Recovery is best effort and does not guarantee exactly-once external effects.

The current Fly configuration does not mount a volume, so its SQLite database is ephemeral across machine replacement. Production restart recovery is not a meaningful guarantee until persistence is mounted or externalized.

Current operational gaps:

- No automated database backups or restore drill
- No persistent production volume
- No persistent external queue
- No distributed worker coordination
- No cross-instance live event broker
- No tool-level idempotency framework
- No authentication or tenant isolation

## Observability

- Requests accept or generate `X-Request-Id`.
- Structured logs identify service activity and unhandled run failures.
- Run events persist planning, step, reflection, retry, cancellation, and completion state.
- Step and run records expose status, attempts, logs, diagnostics, token usage, and estimated cost.
- SSE provides live operational updates with keepalives.

There is no external tracing or metrics backend, SLO dashboard, or alerting integration.

## Deployment Verification

Production deployment runs after successful main-branch CI. CI checks formatting, lint, tests, static security, dependency vulnerabilities, and container vulnerabilities.

After deployment, verify:

1. `GET /health`
2. Workflow template listing
3. A mock-provider run from creation to terminal state
4. SSE event replay and live updates
5. Cancellation and retry behavior
6. Run totals and cost-ledger persistence
7. Restart recovery with a controlled incomplete run in a persistent local or volume-backed environment
