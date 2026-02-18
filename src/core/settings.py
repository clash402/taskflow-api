from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "taskflow-api"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    database_url: str = Field(default="sqlite:///./data/taskflow.db", alias="DATABASE_URL")

    llm_provider: str = Field(default="mock", alias="LLM_PROVIDER")
    llm_cheap_model: str = Field(default="mock-cheap", alias="LLM_CHEAP_MODEL")
    llm_default_model: str = Field(default="mock-default", alias="LLM_DEFAULT_MODEL")
    llm_expensive_model: str = Field(default="mock-expensive", alias="LLM_EXPENSIVE_MODEL")

    llm_cheap_prompt_per_1k: float = Field(default=0.0001, alias="LLM_CHEAP_PROMPT_PER_1K")
    llm_cheap_completion_per_1k: float = Field(default=0.0002, alias="LLM_CHEAP_COMPLETION_PER_1K")
    llm_default_prompt_per_1k: float = Field(default=0.0005, alias="LLM_DEFAULT_PROMPT_PER_1K")
    llm_default_completion_per_1k: float = Field(
        default=0.001, alias="LLM_DEFAULT_COMPLETION_PER_1K"
    )
    llm_expensive_prompt_per_1k: float = Field(default=0.002, alias="LLM_EXPENSIVE_PROMPT_PER_1K")
    llm_expensive_completion_per_1k: float = Field(
        default=0.004, alias="LLM_EXPENSIVE_COMPLETION_PER_1K"
    )

    default_run_budget_usd: float = 2.0
    default_run_timeout_s: int = 300
    default_run_max_steps: int = 30
    default_reflection_interval_steps: int = 2

    request_id_header: str = "X-Request-Id"
    cost_ledger_app: str = "taskflow-api"

    @property
    def sqlite_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("Only sqlite:/// URLs are supported")
        raw_path = self.database_url[len(prefix) :]
        return Path(raw_path).expanduser().resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
