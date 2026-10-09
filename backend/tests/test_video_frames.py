import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai.types.chat import ChatCompletionMessageParam

from llm import Llm
from prompts.pipeline import build_prompt_messages
from prompts.request_parsing import MAX_VIDEO_FRAMES, parse_prompt_content
from routes.generate_code import (
    AgenticGenerationStage,
    ExtractedParams,
    ModelSelectionStage,
    PipelineContext,
    RunWorkspaceMiddleware,
    variant_prompt_messages,
)
from stack_generator.workspace import RunWorkspace

VIDEO_DATA_URL = "data:video/mp4;base64,AAAA"
JPEG_BYTES = b"\xff\xd8\xff\xe0frame"
FRAME = "data:image/jpeg;base64," + base64.b64encode(JPEG_BYTES).decode()


def _frames(count: int) -> list[str]:
    return [f"data:image/jpeg;base64,{index:04d}" for index in range(count)]


# -- request parsing ---------------------------------------------------------


def test_parses_video_frames_next_to_videos() -> None:
    parsed = parse_prompt_content(
        {"text": "", "videos": [VIDEO_DATA_URL], "videoFrames": [FRAME, FRAME, 3]}
    )
    assert parsed["videos"] == [VIDEO_DATA_URL]
    assert parsed.get("video_frames") == [FRAME, FRAME]


def test_missing_video_frames_are_omitted() -> None:
    parsed = parse_prompt_content({"text": "hi", "videos": []})
    assert "video_frames" not in parsed


def test_video_frames_are_capped_keeping_first_and_last() -> None:
    frames = _frames(MAX_VIDEO_FRAMES + 5)
    parsed = parse_prompt_content({"videoFrames": frames})
    kept = parsed.get("video_frames", [])
    assert MAX_VIDEO_FRAMES == 20
    assert len(kept) == MAX_VIDEO_FRAMES
    assert kept[0] == frames[0]
    assert kept[-1] == frames[-1]


# -- model selection ---------------------------------------------------------


async def _select(
    *,
    openai: bool,
    anthropic: bool,
    gemini: bool,
    frames: bool,
    generation_type: str = "create",
) -> List[Llm]:
    selector = ModelSelectionStage(AsyncMock())
    return await selector.select_models(
        generation_type=cast(Any, generation_type),
        input_mode="video",
        openai_api_key="key" if openai else None,
        anthropic_api_key="key" if anthropic else None,
        gemini_api_key="key" if gemini else None,
        has_video_frames=frames,
    )


@pytest.mark.asyncio
async def test_video_with_frames_all_keys_pairs_claude_frames_with_gemini_video() -> None:
    models = await _select(openai=True, anthropic=True, gemini=True, frames=True)
    assert models == [Llm.CLAUDE_FABLE_5_1_HIGH, Llm.GEMINI_3_1_PRO_PREVIEW_HIGH]


@pytest.mark.asyncio
async def test_video_with_frames_anthropic_and_gemini() -> None:
    models = await _select(openai=False, anthropic=True, gemini=True, frames=True)
    assert models == [Llm.CLAUDE_FABLE_5_1_HIGH, Llm.GEMINI_3_1_PRO_PREVIEW_HIGH]


@pytest.mark.asyncio
async def test_video_with_frames_anthropic_only() -> None:
    models = await _select(openai=False, anthropic=True, gemini=False, frames=True)
    assert models == [Llm.CLAUDE_FABLE_5_1_HIGH, Llm.CLAUDE_OPUS_5_5_MEDIUM]


@pytest.mark.asyncio
async def test_video_with_frames_openai_only() -> None:
    models = await _select(openai=True, anthropic=False, gemini=False, frames=True)
    assert models == [Llm.GPT_5_6_SOL_HIGH, Llm.GPT_5_6_SOL_MEDIUM]


@pytest.mark.asyncio
async def test_video_with_frames_openai_and_anthropic() -> None:
    models = await _select(openai=True, anthropic=True, gemini=False, frames=True)
    assert models == [Llm.CLAUDE_FABLE_5_1_HIGH, Llm.GPT_5_6_SOL_HIGH]


@pytest.mark.asyncio
async def test_video_with_frames_openai_and_gemini() -> None:
    models = await _select(openai=True, anthropic=False, gemini=True, frames=True)
    assert models == [Llm.GPT_5_6_SOL_HIGH, Llm.GEMINI_3_1_PRO_PREVIEW_HIGH]


@pytest.mark.asyncio
async def test_video_gemini_only_is_unchanged_with_or_without_frames() -> None:
    expected = [Llm.GEMINI_3_FLASH_PREVIEW_MINIMAL, Llm.GEMINI_3_1_PRO_PREVIEW_HIGH]
    for frames in (True, False):
        models = await _select(openai=False, anthropic=False, gemini=True, frames=frames)
        assert models == expected


@pytest.mark.asyncio
async def test_video_without_frames_keeps_gemini_video_models() -> None:
    models = await _select(openai=True, anthropic=True, gemini=True, frames=False)
    assert models == [
        Llm.GEMINI_3_FLASH_PREVIEW_MINIMAL,
        Llm.GEMINI_3_1_PRO_PREVIEW_HIGH,
    ]


@pytest.mark.asyncio
async def test_video_without_frames_or_gemini_reports_gemini_requirement() -> None:
    throw_error = AsyncMock()
    selector = ModelSelectionStage(throw_error)
    with pytest.raises(Exception, match="No API key"):
        await selector.select_models(
            generation_type="create",
            input_mode="video",
            openai_api_key="key",
            anthropic_api_key="key",
            gemini_api_key=None,
            has_video_frames=False,
        )
    assert "Video mode requires a Gemini API key" in throw_error.await_args_list[0].args[0]


# -- prompts -----------------------------------------------------------------


def _user_parts(messages: list[ChatCompletionMessageParam]) -> list[dict[str, Any]]:
    content = messages[1].get("content")
    assert isinstance(content, list)
    return [cast(dict[str, Any], part) for part in content]


@pytest.mark.asyncio
async def test_frames_prompt_sends_every_frame_as_an_image_in_order() -> None:
    frames = _frames(3)
    messages = await build_prompt_messages(
        stack="html_tailwind",
        input_mode="video",
        generation_type="create",
        prompt={"text": "Use dark mode", "images": [], "videos": [VIDEO_DATA_URL], "video_frames": frames},
        history=[],
        use_video_frames=True,
    )
    parts = _user_parts(messages)
    image_urls = [part["image_url"]["url"] for part in parts if part["type"] == "image_url"]
    assert image_urls == frames
    assert VIDEO_DATA_URL not in image_urls
    text = "\n".join(part["text"] for part in parts if part["type"] == "text")
    assert (
        "These are 3 frames sampled at 1 fps from a screen recording of an app, "
        "in order. Reconstruct the app, including the states and interactions "
        "the frames show."
    ) in text
    assert "Use dark mode" in text
    assert "Selected stack: html_tailwind." in text


@pytest.mark.asyncio
async def test_video_prompt_still_sends_the_video_by_default() -> None:
    messages = await build_prompt_messages(
        stack="html_tailwind",
        input_mode="video",
        generation_type="create",
        prompt={"text": "", "images": [], "videos": [VIDEO_DATA_URL], "video_frames": _frames(2)},
        history=[],
    )
    parts = _user_parts(messages)
    image_urls = [part["image_url"]["url"] for part in parts if part["type"] == "image_url"]
    assert image_urls == [VIDEO_DATA_URL]


def test_variant_prompts_give_frames_to_non_gemini_models() -> None:
    video_prompt: list[ChatCompletionMessageParam] = [{"role": "user", "content": "video"}]
    frames_prompt: list[ChatCompletionMessageParam] = [{"role": "user", "content": "frames"}]

    prompts = variant_prompt_messages(
        [Llm.CLAUDE_FABLE_5_1_HIGH, Llm.GEMINI_3_1_PRO_PREVIEW_HIGH, Llm.GPT_5_6_SOL_HIGH],
        video_prompt,
        frames_prompt,
    )

    assert prompts == [frames_prompt, video_prompt, frames_prompt]
    assert variant_prompt_messages([Llm.CLAUDE_OPUS_5_5_MEDIUM], video_prompt, None) == [
        video_prompt
    ]


@pytest.mark.asyncio
async def test_process_variants_runs_each_model_with_its_own_prompt() -> None:
    stage = AgenticGenerationStage(
        send_message=AsyncMock(),
        openai_api_key=None,
        openai_base_url=None,
        anthropic_api_key="key",
        gemini_api_key="key",
        replicate_api_key=None,
        should_generate_images=False,
        file_state=None,
        asset_base_url="",
        option_codes=None,
    )
    seen: list[tuple[int, Llm, Any]] = []

    async def fake_run_variant(index: int, model: Llm, prompt_messages: Any) -> str:
        seen.append((index, model, prompt_messages))
        return f"<html>{index}</html>"

    stage._run_variant = fake_run_variant  # type: ignore[method-assign]
    video_prompt: list[ChatCompletionMessageParam] = [{"role": "user", "content": "video"}]
    frames_prompt: list[ChatCompletionMessageParam] = [{"role": "user", "content": "frames"}]

    completions = await stage.process_variants(
        variant_models=[Llm.CLAUDE_FABLE_5_1_HIGH, Llm.GEMINI_3_1_PRO_PREVIEW_HIGH],
        prompt_messages=video_prompt,
        frames_prompt_messages=frames_prompt,
    )

    assert completions == {0: "<html>0</html>", 1: "<html>1</html>"}
    assert seen == [
        (0, Llm.CLAUDE_FABLE_5_1_HIGH, frames_prompt),
        (1, Llm.GEMINI_3_1_PRO_PREVIEW_HIGH, video_prompt),
    ]


# -- run workspace -----------------------------------------------------------


def test_save_upload_accepts_a_file_stem(tmp_path: Path) -> None:
    ws = RunWorkspace.create(
        "run_20261008_101500_ab12cd34",
        source_stack="html_tailwind",
        input_mode="video",
        prompt_text="",
        runs_dir=tmp_path,
    )

    path = ws.save_upload("screenshots", FRAME, stem="frame-01")

    assert path == ws.path / "uploads" / "screenshots" / "frame-01.jpg"
    assert path.read_bytes() == JPEG_BYTES
    with pytest.raises(ValueError):
        ws.save_upload("screenshots", FRAME, stem="../escape")


@pytest.mark.asyncio
async def test_run_workspace_saves_video_frames_as_numbered_jpegs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    sent: list[tuple[str, str | None]] = []

    async def send_message(
        msg_type: str,
        value: str | None,
        variant_index: int,
        data: dict[str, Any] | None = None,
        eventId: str | None = None,
    ) -> None:
        sent.append((msg_type, value))

    context = PipelineContext(websocket=MagicMock())
    context.ws_comm = cast(
        Any, SimpleNamespace(send_message=send_message, throw_error=AsyncMock())
    )
    context.extracted_params = ExtractedParams(
        stack="html_tailwind",
        input_mode="video",
        should_generate_images=False,
        openai_api_key=None,
        anthropic_api_key="key",
        gemini_api_key=None,
        replicate_api_key=None,
        openai_base_url=None,
        generation_type="create",
        prompt={
            "text": "",
            "images": [],
            "videos": [VIDEO_DATA_URL],
            "video_frames": [FRAME, FRAME, FRAME],
        },
        history=[],
        file_state=None,
        option_codes=[],
        commit_hash=None,
    )

    async def next_func() -> None:
        context.completions = []

    await RunWorkspaceMiddleware().process(context, next_func)

    run_id = sent[0][1]
    assert run_id is not None
    screenshots = tmp_path / run_id / "uploads" / "screenshots"
    assert sorted(path.name for path in screenshots.iterdir()) == [
        "frame-01.jpg",
        "frame-02.jpg",
        "frame-03.jpg",
    ]
    assert len(list((tmp_path / run_id / "uploads" / "video").iterdir())) == 1
