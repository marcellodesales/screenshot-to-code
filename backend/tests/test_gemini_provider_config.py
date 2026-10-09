from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import types

from agent.providers.gemini import (
    GeminiProviderSession,
    _get_gemini_api_model_name,
    _get_thinking_level_for_model,
)
from llm import GEMINI_MODELS, Llm


def test_gemini_3_6_flash_thinking_variants_map_to_same_api_model() -> None:
    expected_levels = {
        Llm.GEMINI_3_6_FLASH_MINIMAL: "minimal",
        Llm.GEMINI_3_6_FLASH_LOW: "low",
        Llm.GEMINI_3_6_FLASH_MEDIUM: "medium",
        Llm.GEMINI_3_6_FLASH_HIGH: "high",
    }

    for model, thinking_level in expected_levels.items():
        assert model in GEMINI_MODELS
        assert _get_gemini_api_model_name(model) == "gemini-3.6-flash"
        assert _get_thinking_level_for_model(model) == thinking_level


def test_gemini_3_8_flash_thinking_variants_map_to_same_api_model() -> None:
    expected_levels = {
        Llm.GEMINI_3_8_FLASH_MINIMAL: "minimal",
        Llm.GEMINI_3_8_FLASH_LOW: "low",
        Llm.GEMINI_3_8_FLASH_MEDIUM: "medium",
        Llm.GEMINI_3_8_FLASH_HIGH: "high",
    }

    for model, thinking_level in expected_levels.items():
        assert model in GEMINI_MODELS
        assert _get_gemini_api_model_name(model) == "gemini-3.8-flash"
        assert _get_thinking_level_for_model(model) == thinking_level


class _StopStream(Exception):
    pass


class _FakeModels:
    def __init__(self) -> None:
        self.configs: list[types.GenerateContentConfig] = []

    async def generate_content_stream(self, **kwargs: Any) -> Any:
        self.configs.append(kwargs["config"])
        raise _StopStream()


class _FakeGeminiClient:
    def __init__(self) -> None:
        self.aio = SimpleNamespace(models=_FakeModels())


async def _noop_event_sink(_: Any) -> None:
    return None


async def _captured_gemini_config(
    tools: list[types.Tool],
) -> types.GenerateContentConfig:
    client = _FakeGeminiClient()
    session = GeminiProviderSession(
        client=client,  # type: ignore[arg-type]
        model=Llm.GEMINI_3_5_FLASH_MEDIUM,
        prompt_messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "Return JSON."},
        ],
        tools=tools,
    )
    with pytest.raises(_StopStream):
        await session.stream_turn(_noop_event_sink)
    return client.aio.models.configs[0]


@pytest.mark.asyncio
async def test_gemini_session_omits_tools_when_list_is_empty() -> None:
    config = await _captured_gemini_config([])
    assert config.tools is None


@pytest.mark.asyncio
async def test_gemini_session_sends_tools_when_present() -> None:
    tool = types.Tool(
        function_declarations=[
            types.FunctionDeclaration(name="edit_file", description="Apply an edit.")
        ]
    )
    config = await _captured_gemini_config([tool])
    assert config.tools == [tool]
