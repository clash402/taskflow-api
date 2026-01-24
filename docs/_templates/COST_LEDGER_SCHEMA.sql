-- Shared cost_ledger schema (SQLite)

CREATE TABLE IF NOT EXISTS cost_ledger (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  request_id TEXT NOT NULL,
  app TEXT NOT NULL,
  feature TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_tokens INTEGER NOT NULL,
  completion_tokens INTEGER NOT NULL,
  total_tokens INTEGER NOT NULL,
  usd REAL NOT NULL,
  meta_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_cost_ledger_request_id ON cost_ledger(request_id);
CREATE INDEX IF NOT EXISTS idx_cost_ledger_app_feature ON cost_ledger(app, feature);
