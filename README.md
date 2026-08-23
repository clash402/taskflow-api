# Taskflow

Taskflow is the control and orchestration layer of Ghost Platform. It turns a task into an explicit workflow graph, executes eligible steps under contracts and budgets, monitors progress, and reflects at controlled boundaries.

The goal is constrained, inspectable autonomy: useful agentic behavior without hiding execution state or allowing model output to bypass system policy.

## Current Capabilities

- Create and version workflow templates with nodes, dependencies, edges, and contracts
- Plan a run from a template or a generated graph
- Execute eligible DAG nodes with dependency checks
- Validate tool permission and structured output contracts
- Retry failed steps according to policy
- Enforce run budgets, timeouts, and maximum step counts
- Reflect after failures, periodic boundaries, and monitor faults
- Cancel or retry runs
- Stream persisted and live run events over SSE
- Persist runs, steps, events, diagnostics, templates, and cost records in SQLite
- Route between mock, OpenAI, and Anthropic providers
- Resume incomplete runs on startup on a best-effort basis

## Current Scope

Taskflow is a portfolio-scale control plane, not a distributed workflow service.

- Execution uses in-process asyncio tasks.
- SQLite is the only supported persistence backend.
- The executor currently exposes one built-in tool contract: `llm.generate`.
- Graph execution is controlled and inspectable, but there are no distributed workers, external queue, human approval workflow, authentication, or tenant isolation.
- Restart recovery resumes incomplete state but does not provide exactly-once execution.

See [docs/architecture.md](docs/architecture.md) for orchestration boundaries and failure semantics.

## Run Lifecycle

```text
Create run
  -> plan DAG
  -> monitor
  -> execute next eligible step
  -> monitor
  -> reflect when policy requires
  -> finish with explicit status
```

Models may propose plans and generate step output. Deterministic services own contract validation, dependency eligibility, retries, budgets, timeouts, persistence, and terminal status.

## Quick Start

Requires Python 3.11 or later.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
cp .env.local.example .env.local
./start.sh
```

The API runs at `http://localhost:8000`, with interactive OpenAPI documentation at `/docs`. The default mock provider supports deterministic local development.

## API Surface

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Service health |
| `GET /workflows` | List workflow templates |
| `GET /workflows/{template_id}` | Retrieve a workflow template |
| `POST /workflows` | Create or update a workflow template |
| `GET /runs` | List runs |
| `POST /runs` | Create and start a run |
| `GET /runs/{run_id}` | Retrieve a run, graph, steps, cost, and diagnostics |
| `POST /runs/{run_id}/cancel` | Request cancellation |
| `POST /runs/{run_id}/retry` | Retry a run or step |
| `GET /runs/{run_id}/events` | Stream run events with SSE |

JSON endpoints return their declared Pydantic response directly. They are not wrapped in a shared Ghost envelope. Correlation uses `X-Request-Id`.

## Quality Checks

```bash
black --check .
ruff check .
pytest
```

Tests cover contracts, provider routing, retry policy, run lifecycle, and the API surface.

## Deployment and Operations

The API is containerized and configured for Fly.io. The current Fly configuration does not mount persistent storage or configure cross-origin browser access. Deployed SQLite state is therefore ephemeral across machine replacement, and a separately hosted browser client needs a same-origin proxy or CORS integration.

Provider configuration, persistence, recovery behavior, guardrails, and operational gaps are documented in [docs/operations.md](docs/operations.md).

The web client lives in [taskflow-web](https://github.com/clash402/taskflow-web).
