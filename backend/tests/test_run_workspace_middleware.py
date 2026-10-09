import asyncio
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from routes import generate_code
from routes.generate_code import (
    ExtractedParams,
    ParameterExtractionStage,
    PipelineContext,
    RunWorkspaceMiddleware,
)

SentMessage = tuple[str, str | None, int, dict[str, Any] | None]


class FakeQa:
    """Stands in for visual QA (real Chromium is covered by test_visual_qa)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.error: Exception | None = None
        self.delay = 0.0

    async def __call__(self, workspace: Any, ui_commit_hash: str) -> dict[str, Any]:
        self.calls.append((workspace.run_id, ui_commit_hash))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return {"commitHash": ui_commit_hash, "options": [{"index": 0}]}


@pytest.fixture(autouse=True)
def fake_qa(monkeypatch: pytest.MonkeyPatch) -> FakeQa:
    fake = FakeQa()
    monkeypatch.setattr(generate_code, "run_version_qa", fake)
    return fake


def _context(
    sent: list[SentMessage],
    *,
    generation_type: Literal["create", "update"] = "create",
    run_id: str | None = None,
    commit_hash: str | None = "h1",
    parent_commit_hash: str | None = None,
    text: str = "Coffee shop landing page",
) -> PipelineContext:
    async def send_message(
        msg_type: str,
        value: str | None,
        variant_index: int,
        data: dict[str, Any] | None = None,
        eventId: str | None = None,
    ) -> None:
        sent.append((msg_type, value, variant_index, data))

    context = PipelineContext(websocket=MagicMock())
    context.ws_comm = cast(
        Any, SimpleNamespace(send_message=send_message, throw_error=AsyncMock())
    )
    context.extracted_params = ExtractedParams(
        stack="react_tailwind",
        input_mode="image",
        should_generate_images=False,
        openai_api_key=None,
        anthropic_api_key="key",
        gemini_api_key=None,
        replicate_api_key=None,
        openai_base_url=None,
        generation_type=generation_type,
        prompt={
            "text": text,
            "images": ["data:image/png;base64,iVBORw0KGgo="],
            "videos": [],
        },
        history=[],
        file_state=None,
        option_codes=[],
        run_id=run_id,
        commit_hash=commit_hash,
        parent_commit_hash=parent_commit_hash,
    )
    return context


async def _run(context: PipelineContext, completions: list[str]) -> bool:
    called = False

    async def next_func() -> None:
        nonlocal called
        called = True
        context.completions = completions

    await RunWorkspaceMiddleware().process(context, next_func)
    return called


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _of_type(sent: list[SentMessage], msg_type: str) -> list[SentMessage]:
    return [message for message in sent if message[0] == msg_type]


@pytest.mark.asyncio
async def test_extracts_run_linking_params() -> None:
    extracted = await ParameterExtractionStage(AsyncMock()).extract_and_validate(
        {
            "generatedCodeConfig": "html_tailwind",
            "inputMode": "text",
            "prompt": {"text": "hello"},
            "runId": "run_20261008_101500_ab12cd34",
            "commitHash": "h2",
            "parentCommitHash": "h1",
        }
    )

    assert extracted.run_id == "run_20261008_101500_ab12cd34"
    assert extracted.commit_hash == "h2"
    assert extracted.parent_commit_hash == "h1"

    old_client = await ParameterExtractionStage(AsyncMock()).extract_and_validate(
        {"generatedCodeConfig": "html_tailwind", "inputMode": "text"}
    )
    assert old_client.run_id is None
    assert old_client.commit_hash is None
    assert old_client.parent_commit_hash is None


@pytest.mark.asyncio
async def test_create_sends_run_info_and_commits_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    sent: list[SentMessage] = []

    assert await _run(_context(sent), ["<a/>", "<b/>"])

    assert sent[0][0] == "runInfo"
    run_id = sent[0][1]
    assert run_id is not None and re.match(r"^run_\d{8}_\d{6}_[0-9a-f]{8}$", run_id)
    run_dir = tmp_path / run_id
    assert (run_dir / "op2/design/mock.html").read_text(encoding="utf-8") == "<b/>"
    assert len(list((run_dir / "uploads/screenshots").iterdir())) == 1

    [committed] = _of_type(sent, "versionCommitted")
    data = committed[3]
    assert data is not None and data["commitHash"] == "h1"
    assert re.match(r"^[0-9a-f]{40}$", data["gitSha"])
    assert _git(run_dir, "log", "-1", "--format=%s", data["gitSha"]) == (
        ":art: Version 1 — mock (react_tailwind)"
    )


@pytest.mark.asyncio
async def test_update_reuses_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    sent: list[SentMessage] = []
    await _run(_context(sent), ["<a/>", "<b/>"])
    run_id = sent[0][1]
    assert run_id is not None
    first_sha = _of_type(sent, "versionCommitted")[0][3]["gitSha"]  # type: ignore[index]

    sent.clear()
    instruction = "Make the header dark " + "x" * 100
    await _run(
        _context(
            sent,
            generation_type="update",
            run_id=run_id,
            commit_hash="h2",
            parent_commit_hash="h1",
            text=instruction,
        ),
        ["<c/>", "<d/>"],
    )

    assert sent[0] == ("runInfo", run_id, 0, None)
    assert [p.name for p in tmp_path.iterdir()] == [run_id]
    new_sha = _of_type(sent, "versionCommitted")[0][3]["gitSha"]  # type: ignore[index]
    run_dir = tmp_path / run_id
    assert _git(run_dir, "rev-parse", f"{new_sha}^") == first_sha
    assert _git(run_dir, "log", "-1", "--format=%s", new_sha) == (
        f":art: Version 2 — {instruction[:72]}"
    )


@pytest.mark.asyncio
async def test_unknown_run_id_starts_new_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    sent: list[SentMessage] = []

    await _run(
        _context(
            sent,
            generation_type="update",
            run_id="../../etc",
            commit_hash="h2",
            parent_commit_hash="h1",
        ),
        ["<c/>"],
    )

    run_id = sent[0][1]
    assert sent[0][0] == "runInfo"
    assert run_id is not None and re.match(r"^run_\d{8}_\d{6}_[0-9a-f]{8}$", run_id)
    assert [p.name for p in tmp_path.iterdir()] == [run_id]
    assert len(_of_type(sent, "versionCommitted")) == 1


@pytest.mark.asyncio
async def test_skips_commit_without_commit_hash_or_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    sent: list[SentMessage] = []

    await _run(_context(sent, commit_hash=None), ["<a/>"])
    await _run(_context(sent), ["", ""])

    assert _of_type(sent, "versionCommitted") == []
    assert len(_of_type(sent, "runInfo")) == 2


@pytest.mark.asyncio
async def test_workspace_failure_does_not_break_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    not_a_dir = tmp_path / "runs"
    not_a_dir.write_text("", encoding="utf-8")
    monkeypatch.setenv("RUNS_DIR", str(not_a_dir))
    sent: list[SentMessage] = []
    context = _context(sent)

    assert await _run(context, ["<a/>"])

    cast(AsyncMock, cast(Any, context.ws_comm).throw_error).assert_not_awaited()
    assert _of_type(sent, "versionCommitted") == []


@pytest.mark.asyncio
async def test_commit_failure_does_not_break_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    sent: list[SentMessage] = []
    context = _context(sent)

    async def next_func() -> None:
        context.completions = ["<a/>"]
        # The run dir disappears mid-generation (e.g. volume wiped).
        run_id = sent[0][1]
        assert run_id is not None
        subprocess.run(["rm", "-rf", str(tmp_path / run_id)], check=True)

    await RunWorkspaceMiddleware().process(context, next_func)

    cast(AsyncMock, cast(Any, context.ws_comm).throw_error).assert_not_awaited()
    assert _of_type(sent, "versionCommitted") == []


@pytest.mark.asyncio
async def test_sends_visual_qa_after_version_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_qa: FakeQa
) -> None:
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    sent: list[SentMessage] = []

    await _run(_context(sent), ["<a/>", "<b/>"])

    types = [message[0] for message in sent]
    assert types.index("visualQa") == types.index("versionCommitted") + 1
    [qa] = _of_type(sent, "visualQa")
    assert qa == ("visualQa", None, 0, {"commitHash": "h1", "options": [{"index": 0}]})
    assert fake_qa.calls == [(sent[0][1], "h1")]


@pytest.mark.asyncio
async def test_visual_qa_failure_or_timeout_sends_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_qa: FakeQa
) -> None:
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    sent: list[SentMessage] = []
    fake_qa.error = RuntimeError("Chromium unavailable")
    context = _context(sent)

    assert await _run(context, ["<a/>"])
    assert len(_of_type(sent, "versionCommitted")) == 1
    assert _of_type(sent, "visualQa") == []

    fake_qa.error = None
    fake_qa.delay = 5
    monkeypatch.setattr(generate_code, "VISUAL_QA_TIMEOUT_SECONDS", 0.05)
    sent.clear()
    assert await _run(_context(sent), ["<a/>"])
    assert len(_of_type(sent, "versionCommitted")) == 1
    assert _of_type(sent, "visualQa") == []
    cast(AsyncMock, cast(Any, context.ws_comm).throw_error).assert_not_awaited()


@pytest.mark.asyncio
async def test_no_visual_qa_without_a_committed_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_qa: FakeQa
) -> None:
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    sent: list[SentMessage] = []

    await _run(_context(sent, commit_hash=None), ["<a/>"])
    await _run(_context(sent), ["", ""])

    assert fake_qa.calls == []
    assert _of_type(sent, "visualQa") == []
