from __future__ import annotations

import importlib
import os
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from backend.src.core.settings import Settings


class ProviderConfigurationError(RuntimeError):
    pass


class LLMCallResult(BaseModel):
    provider: str
    model: str
    content: str
    prompt_tokens: int
    completion_tokens: int


class LLMProvider(ABC):
    provider_name: str

    @abstractmethod
    async def generate(
        self,
        *,
        prompt: str,
        model: str,
        timeout_s: int,
        metadata: dict[str, Any] | None = None,
    ) -> LLMCallResult:
        raise NotImplementedError


class MockLLMProvider(LLMProvider):
    provider_name = "mock"

    async def generate(
        self,
        *,
        prompt: str,
        model: str,
        timeout_s: int,
        metadata: dict[str, Any] | None = None,
    ) -> LLMCallResult:
        del timeout_s
        metadata = metadata or {}
        node_id = metadata.get("node_id", "unknown")
        summary = f"Processed node={node_id}; prompt_len={len(prompt)}"
        prompt_tokens = max(1, len(prompt.split()))
        completion_tokens = max(1, len(summary.split()))
        return LLMCallResult(
            provider=self.provider_name,
            model=model,
            content=summary,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )


class LangChainProvider(LLMProvider):
    def __init__(
        self, provider_name: str, client_cls: type[Any], api_key: str | None = None
    ) -> None:
        self.provider_name = provider_name
        self._client_cls = client_cls
        self._api_key = api_key

    async def generate(
        self,
        *,
        prompt: str,
        model: str,
        timeout_s: int,
        metadata: dict[str, Any] | None = None,
    ) -> LLMCallResult:
        metadata = metadata or {}
        kwargs: dict[str, Any] = {"model": model, "timeout": timeout_s, "tags": ["taskflow"]}
        if self._api_key:
            if self.provider_name == "openai":
                kwargs["api_key"] = self._api_key
            if self.provider_name == "anthropic":
                kwargs["anthropic_api_key"] = self._api_key
        client = self._client_cls(**kwargs)
        response = await client.ainvoke(prompt, config={"metadata": metadata})

        content = self._normalize_content(getattr(response, "content", ""))
        usage = self._extract_usage(response)

        prompt_tokens = int(
            usage.get("prompt_tokens") or usage.get("input_tokens") or max(1, len(prompt.split()))
        )
        completion_tokens = int(
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or max(1, len(content.split()))
        )

        return LLMCallResult(
            provider=self.provider_name,
            model=model,
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def _extract_usage(self, response: Any) -> dict[str, Any]:
        usage: dict[str, Any] = {}

        usage_metadata = getattr(response, "usage_metadata", None)
        if isinstance(usage_metadata, dict):
            usage.update(usage_metadata)

        response_meta = getattr(response, "response_metadata", {}) or {}
        if "token_usage" in response_meta and isinstance(response_meta["token_usage"], dict):
            usage.update(response_meta["token_usage"])
        if "usage" in response_meta and isinstance(response_meta["usage"], dict):
            usage.update(response_meta["usage"])
        return usage

    def _normalize_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    parts.append(str(part["text"]))
                    continue
                text_attr = getattr(part, "text", None)
                if text_attr:
                    parts.append(str(text_attr))
                    continue
                parts.append(str(part))
            return " ".join(segment for segment in parts if segment).strip()
        return str(content)


def _import_client_class(module_name: str, class_name: str, provider_name: str) -> type[Any]:
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise ProviderConfigurationError(
            f"Missing dependency '{module_name}' for LLM_PROVIDER={provider_name}. "
            f"Install the provider package and retry."
        ) from exc

    client_cls = getattr(module, class_name, None)
    if client_cls is None:
        raise ProviderConfigurationError(
            f"Dependency '{module_name}' does not expose '{class_name}' required for "
            f"LLM_PROVIDER={provider_name}."
        )
    return client_cls


def _require_api_key(env_var: str, provider_name: str) -> str:
    api_key = os.environ.get(env_var)
    if not api_key:
        raise ProviderConfigurationError(
            f"{env_var} must be set when LLM_PROVIDER={provider_name}."
        )
    return api_key


def build_provider(settings: Settings) -> LLMProvider:
    provider = settings.llm_provider.lower().strip()
    if provider == "mock":
        return MockLLMProvider()

    if provider == "openai":
        chat_open_ai = _import_client_class("langchain_openai", "ChatOpenAI", provider)
        api_key = _require_api_key("OPENAI_API_KEY", provider)
        return LangChainProvider(provider_name=provider, client_cls=chat_open_ai, api_key=api_key)

    if provider == "anthropic":
        chat_anthropic = _import_client_class("langchain_anthropic", "ChatAnthropic", provider)
        api_key = _require_api_key("ANTHROPIC_API_KEY", provider)
        return LangChainProvider(provider_name=provider, client_cls=chat_anthropic, api_key=api_key)

    raise ProviderConfigurationError(f"Unsupported LLM provider: {settings.llm_provider}")
