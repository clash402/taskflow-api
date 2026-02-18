# Taskflow API Assumptions

## Scope
- v1 runs with an in-process async runner and SQLite-backed state.
- Execution durability across process restarts is best-effort by resuming `created` and `running` runs on startup.

## Workflow Template Format
- Templates contain:
  - `id`, `name`, `version`, `description`
  - `graph.nodes[]` with `id`, `name`, `description`, `depends_on[]`
  - `graph.edges[]` with `source`, `target`
  - `contracts` keyed by `node_id`
- Runtime mutates node state in `run.dag.nodes[]` using:
  - `status` (`pending|running|completed|failed|skipped|canceled`)
  - `last_output`
  - `last_error`

## Tool Interface Assumption
- v1 executor uses one built-in tool contract: `llm.generate`.
- If `allowed_tools` excludes `llm.generate`, the step fails with structured `tool_not_allowed`.

## Output Contract Assumption
- Node outputs are validated against Pydantic output models from the contract registry.
- Validation errors map to structured `schema_error` and are retried per policy.

## Reflection Behavior Assumption
- Reflection triggers on:
  - step failure
  - periodic boundaries (`reflection_interval_steps`)
  - monitor faults (timeout/budget/max steps)
- Reflection can produce one of:
  - `replanned`
  - `adjusted_parameters`
  - `terminated`
- Diagnostics are persisted as `reflection` events and appended to run diagnostics.

## LLM Provider Assumption
- `LLM_PROVIDER=mock` is default for local/dev tests.
- OpenAI/Anthropic routes are available through optional LangChain provider imports.
- `OPENAI_API_KEY` is required when `LLM_PROVIDER=openai`.
- `ANTHROPIC_API_KEY` is required when `LLM_PROVIDER=anthropic`.
- Provider dependency/key misconfiguration is fail-fast at startup (no silent fallback to mock).

## Cost Ledger Assumption
- Every planner and executor LLM call writes to `cost_ledger` with:
  - `app`
  - `provider`
  - `model`
  - token counts
  - USD estimate
- Run totals are incrementally aggregated from these entries.
