# Web API Client Pattern (Copy/Paste Reference)

- `client.ts` owns:
  - base URL
  - request id header
  - envelope parsing
  - error normalization

- `endpoints.ts` owns:
  - per-endpoint calls
  - Zod validation of `data`

- `types.ts` owns:
  - Zod schemas + inferred types
