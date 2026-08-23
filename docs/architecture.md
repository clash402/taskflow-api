# Taskflow Architecture

## Responsibility

Taskflow owns planning, orchestration state, contract enforcement, execution policy, monitoring, reflection, and run lifecycle. Domain-specific work belongs in tools or services invoked by the control plane.

Taskflow does not currently provide distributed workers, a general tool marketplace, or exactly-once workflow execution.

## System Context

```text
Web or API client
  -> FastAPI
      -> workflow and run routers
      -> Taskflow orchestrator
          -> planner
          -> executor
          -> monitor
          -> reflection
      -> event broker
      -> model provider
      -> SQLite repository
```

## Workflow Model

A workflow template contains:

- Identity, name, description, and version
- Nodes with dependencies
- Edges for visualization and validation
- Per-node input, output, tool, and retry contracts

A run owns a mutable DAG derived from a template or planner output. Node state records pending, running, completed, failed, skipped, or canceled status plus the last output or error.

The executor currently runs one eligible node at a time. Dependencies must be complete before a node becomes eligible.

## Orchestration Graph

The runtime uses a controlled state graph:

```text
plan -> monitor -> execute_step -> monitor
                    |                |
                    +--- reflect <---+
                              |
                           monitor -> finish
```

Reflection is triggered by policy, not unrestricted agent improvisation:

- Step failure
- Periodic completed-step boundaries
- Timeout, budget, or maximum-step monitor faults

Reflection may replan, adjust parameters, or terminate. The monitor remains authoritative over whether execution continues.

## Deterministic and Probabilistic Boundaries

Models may:

- Propose or expand a workflow plan
- Generate output for the current `llm.generate` tool

Deterministic services own:

- Template and graph validation
- Dependency eligibility
- Allowed-tool checks
- Input and output contract validation
- Retry policy
- Budget, timeout, cancellation, and maximum-step enforcement
- Persistence and terminal status
- Event construction and replay

Provider output cannot bypass a contract or execution constraint.

## Persistence and Events

SQLite stores workflow templates, runs, step attempts, events, diagnostics, and cost-ledger entries. An in-memory broker distributes live events, while persisted events support initial SSE replay.

On startup, the orchestrator attempts to resume created and running runs. This is best-effort recovery: an external tool side effect may have completed before a crash even if its step state was not committed.

## Failure Behavior

| Failure | Behavior |
| --- | --- |
| Invalid graph or contract | Reject planning or execution |
| Tool not allowed | Fail the step with structured error |
| Output schema mismatch | Retry according to policy, then fail |
| Provider unavailable | Fail fast for explicitly configured real providers |
| Step failure | Persist error and trigger controlled reflection |
| Budget, timeout, or max steps | Monitor requests termination |
| Cancellation | Mark remaining work canceled at a safe boundary |
| Process restart | Resume incomplete runs on a best-effort basis |

## Scaling Boundaries

- In-process runner and event broker
- One SQLite database
- One built-in LLM tool
- Sequential eligible-step execution
- No distributed lease, queue, worker heartbeat, or idempotency key for external effects
- No authentication, authorization, approvals, or tenant quotas

Move to external queues, distributed workers, and stronger persistence only when concurrency, duration, or recovery requirements justify the operational cost.
