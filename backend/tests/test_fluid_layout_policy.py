from typing import Literal, get_args

import pytest

from custom_types import InputMode
from prompts.pipeline import build_prompt_messages
from prompts.policies import FLUID_LAYOUT_POLICY
from prompts.prompt_types import Stack, UserTurnInput
from stack_generator.prompts import MIGRATION_SYSTEM_PROMPT

PNG_DATA_URL = "data:image/png;base64,iVBORw0KGgo="
VIDEO_DATA_URL = "data:video/mp4;base64,AAAA"


def test_policy_text_matches_the_contract() -> None:
    assert FLUID_LAYOUT_POLICY.startswith("Fluid, full-canvas layout:")
    assert "`w-full min-h-screen`" in FLUID_LAYOUT_POLICY
    assert "never wrap the page in a fixed or max-width container" in (
        FLUID_LAYOUT_POLICY
    )
    assert "no horizontal scrolling" in FLUID_LAYOUT_POLICY
    assert "`max-w-prose`" in FLUID_LAYOUT_POLICY


def _prompt_for(input_mode: InputMode) -> UserTurnInput:
    return {
        "text": "A pricing page",
        "images": [PNG_DATA_URL] if input_mode == "image" else [],
        "videos": [VIDEO_DATA_URL] if input_mode == "video" else [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("stack", get_args(Stack))
@pytest.mark.parametrize("input_mode", ["image", "text", "video"])
async def test_create_system_prompt_has_fluid_layout_policy_for_every_stack(
    stack: Stack, input_mode: InputMode
) -> None:
    messages = await build_prompt_messages(
        stack=stack,
        input_mode=input_mode,
        generation_type="create",
        prompt=_prompt_for(input_mode),
        history=[],
    )
    system_message = messages[0]
    assert system_message["role"] == "system"
    assert FLUID_LAYOUT_POLICY in str(system_message.get("content"))


@pytest.mark.asyncio
@pytest.mark.parametrize("stack", get_args(Stack))
async def test_update_system_prompt_has_fluid_layout_policy_for_every_stack(
    stack: Stack,
) -> None:
    generation_type: Literal["update"] = "update"
    messages = await build_prompt_messages(
        stack=stack,
        input_mode="text",
        generation_type=generation_type,
        prompt={"text": "Make it blue", "images": [], "videos": []},
        history=[],
        file_state={"path": "index.html", "content": "<html></html>"},
    )
    assert FLUID_LAYOUT_POLICY in str(messages[0].get("content"))


def test_migration_system_prompt_has_fluid_layout_policy() -> None:
    assert FLUID_LAYOUT_POLICY in MIGRATION_SYSTEM_PROMPT
