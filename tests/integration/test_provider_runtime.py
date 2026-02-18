from __future__ import annotations

import asyncio
import sys
import types

import pytest

from backend.src.core.llm.provider import (
    LangChainProvider,
    ProviderConfigurationError,
    build_provider,
)
from backend.src.core.settings import Settings


def test_openai_provider_runtime_path(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        content = "openai completion"
        response_metadata = {"token_usage": {"prompt_tokens": 12, "completion_tokens": 5}}

    class FakeChatOpenAI:
        last_instance = None

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.last_prompt = ""
            self.last_config = {}
            FakeChatOpenAI.last_instance = self

        async def ainvoke(self, prompt: str, config: dict | None = None):
            self.last_prompt = prompt
            self.last_config = config or {}
            return FakeResponse()

    monkeypatch.setitem(
        sys.modules, "langchain_openai", types.SimpleNamespace(ChatOpenAI=FakeChatOpenAI)
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")

    settings = Settings(LLM_PROVIDER="openai")
    provider = build_provider(settings)
    assert isinstance(provider, LangChainProvider)

    result = asyncio.run(
        provider.generate(
            prompt="plan this task",
            model="gpt-4o-mini",
            timeout_s=20,
            metadata={"run_id": "run-123", "phase": "planner"},
        )
    )

    assert result.provider == "openai"
    assert result.model == "gpt-4o-mini"
    assert result.content == "openai completion"
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 5

    assert FakeChatOpenAI.last_instance is not None
    assert FakeChatOpenAI.last_instance.kwargs["api_key"] == "sk-openai-test"
    assert FakeChatOpenAI.last_instance.kwargs["timeout"] == 20
    assert FakeChatOpenAI.last_instance.last_prompt == "plan this task"
    assert FakeChatOpenAI.last_instance.last_config["metadata"]["run_id"] == "run-123"


def test_anthropic_provider_runtime_path_with_usage_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        content = [{"type": "text", "text": "anthropic"}, {"type": "text", "text": "output"}]
        response_metadata = {}
        usage_metadata = {"input_tokens": 14, "output_tokens": 6}

    class FakeChatAnthropic:
        last_instance = None

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.last_prompt = ""
            self.last_config = {}
            FakeChatAnthropic.last_instance = self

        async def ainvoke(self, prompt: str, config: dict | None = None):
            self.last_prompt = prompt
            self.last_config = config or {}
            return FakeResponse()

    monkeypatch.setitem(
        sys.modules,
        "langchain_anthropic",
        types.SimpleNamespace(ChatAnthropic=FakeChatAnthropic),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic-test")

    settings = Settings(LLM_PROVIDER="anthropic")
    provider = build_provider(settings)
    assert isinstance(provider, LangChainProvider)

    result = asyncio.run(
        provider.generate(
            prompt="reflect on this workflow",
            model="claude-3-5-sonnet",
            timeout_s=15,
            metadata={"run_id": "run-xyz", "phase": "reflection"},
        )
    )

    assert result.provider == "anthropic"
    assert result.content == "anthropic output"
    assert result.prompt_tokens == 14
    assert result.completion_tokens == 6

    assert FakeChatAnthropic.last_instance is not None
    assert FakeChatAnthropic.last_instance.kwargs["anthropic_api_key"] == "sk-anthropic-test"
    assert FakeChatAnthropic.last_instance.last_config["metadata"]["phase"] == "reflection"


def test_provider_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "langchain_openai", types.SimpleNamespace(ChatOpenAI=object))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    settings = Settings(LLM_PROVIDER="openai")
    with pytest.raises(ProviderConfigurationError, match="OPENAI_API_KEY"):
        build_provider(settings)


def test_provider_requires_installed_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic-test")

    real_import_module = __import__("importlib").import_module

    def fake_import_module(name: str, package=None):
        if name == "langchain_anthropic":
            raise ModuleNotFoundError("No module named 'langchain_anthropic'")
        return real_import_module(name, package)

    monkeypatch.setattr("backend.src.core.llm.provider.importlib.import_module", fake_import_module)

    settings = Settings(LLM_PROVIDER="anthropic")
    with pytest.raises(ProviderConfigurationError, match="langchain_anthropic"):
        build_provider(settings)
