from typing import Any

import pytest

from agent.providers.anthropic.provider import (
    AnthropicProviderSession,
    ADAPTIVE_THINKING_MODELS,
    _get_anthropic_api_model_name,
    _get_anthropic_effort,
)
from llm import Llm


def test_claude_opus_5_effort_variants_map_to_same_api_model() -> None:
    expected_efforts = {
        Llm.CLAUDE_OPUS_5_LOW: "low",
        Llm.CLAUDE_OPUS_5_MEDIUM: "medium",
        Llm.CLAUDE_OPUS_5_HIGH: "high",
        Llm.CLAUDE_OPUS_5_XHIGH: "xhigh",
        Llm.CLAUDE_OPUS_5_MAX: "max",
    }

    for model, effort in expected_efforts.items():
        assert _get_anthropic_api_model_name(model) == "claude-opus-5"
        assert _get_anthropic_effort(model) == effort
        assert model.value in ADAPTIVE_THINKING_MODELS


def test_claude_opus_4_8_effort_variants_map_to_same_api_model() -> None:
    expected_efforts = {
        Llm.CLAUDE_OPUS_4_8_LOW: "low",
        Llm.CLAUDE_OPUS_4_8_MEDIUM: "medium",
        Llm.CLAUDE_OPUS_4_8_HIGH: "high",
        Llm.CLAUDE_OPUS_4_8_XHIGH: "xhigh",
        Llm.CLAUDE_OPUS_4_8_MAX: "max",
    }

    for model, effort in expected_efforts.items():
        assert _get_anthropic_api_model_name(model) == "claude-opus-4-8"
        assert _get_anthropic_effort(model) == effort


def test_claude_fable_5_effort_variants_map_to_same_api_model() -> None:
    expected_efforts = {
        Llm.CLAUDE_FABLE_5_LOW: "low",
        Llm.CLAUDE_FABLE_5_MEDIUM: "medium",
        Llm.CLAUDE_FABLE_5_HIGH: "high",
        Llm.CLAUDE_FABLE_5_XHIGH: "xhigh",
        Llm.CLAUDE_FABLE_5_MAX: "max",
    }

    for model, effort in expected_efforts.items():
        assert _get_anthropic_api_model_name(model) == "claude-fable-5"
        assert _get_anthropic_effort(model) == effort
        assert model.value in ADAPTIVE_THINKING_MODELS


class _StopStream(Exception):
    pass


class _FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        raise _StopStream()


class _FakeAnthropicClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


async def _noop_event_sink(_: Any) -> None:
    return None


def _anthropic_tool() -> dict[str, Any]:
    return {
        "name": "edit_file",
        "description": "Apply an edit.",
        "input_schema": {"type": "object", "properties": {}},
    }


async def _captured_anthropic_request(tools: list[dict[str, Any]]) -> dict[str, Any]:
    client = _FakeAnthropicClient()
    session = AnthropicProviderSession(
        client=client,  # type: ignore[arg-type]
        model=Llm.CLAUDE_SONNET_4_6,
        prompt_messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "Return JSON."},
        ],
        tools=tools,
    )
    with pytest.raises(_StopStream):
        await session.stream_turn(_noop_event_sink)
    return client.messages.calls[0]


@pytest.mark.asyncio
async def test_anthropic_session_omits_tools_when_list_is_empty() -> None:
    request = await _captured_anthropic_request([])
    assert "tools" not in request


@pytest.mark.asyncio
async def test_anthropic_session_sends_tools_when_present() -> None:
    request = await _captured_anthropic_request([_anthropic_tool()])
    assert request["tools"] == [_anthropic_tool()]
