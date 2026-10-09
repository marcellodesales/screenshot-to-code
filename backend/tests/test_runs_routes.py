import asyncio
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse

from routes import runs
from routes.runs import SaveVersionRequest, get_qa_file, list_stacks, save_version
from stack_generator.workspace import RunWorkspace, new_run_id


def _workspace(runs_dir: Path) -> RunWorkspace:
    ws = RunWorkspace.create(
        new_run_id(),
        source_stack="react_tailwind",
        input_mode="image",
        prompt_text="Coffee shop",
        runs_dir=runs_dir,
    )
    ws.commit_version(
        ui_commit_hash="h1",
        parent_ui_commit_hash=None,
        option_codes=["<a/>", "<b/>"],
        message=":art: Version 1 — mock (react_tailwind)",
    )
    return ws


def _git(ws: RunWorkspace, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ws.path, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    return tmp_path


class FakeQa:
    """Stands in for run_version_qa (no Chromium in route tests)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[str]]] = []
        self.delay = 0.0
        self.error: Exception | None = None

    async def __call__(self, workspace: RunWorkspace, ui_commit_hash: str) -> dict[str, Any]:
        # Record the codes QA sees: it must run on the saved version.
        self.calls.append(
            (workspace.run_id, ui_commit_hash, workspace.option_codes(ui_commit_hash))
        )
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return {
            "commitHash": ui_commit_hash,
            "options": [{"index": 0, "renderOk": True, "duplicateOf": None}],
        }


@pytest.fixture(autouse=True)
def fake_qa(monkeypatch: pytest.MonkeyPatch) -> FakeQa:
    fake = FakeQa()
    monkeypatch.setattr(runs, "run_version_qa", fake)
    return fake


@pytest.mark.asyncio
async def test_list_stacks() -> None:
    stacks = {stack.id: stack for stack in await list_stacks()}

    assert stacks["static-pnpm-html"].status == "available"
    assert stacks["static-pnpm-html"].build_system == "pnpm"
    assert stacks["nextjs-pnpm-react-tailwind"].source_stacks == ["react_tailwind"]
    assert stacks["nextjs-pnpm-react-tailwind"].phase == 2
    assert set(stacks["static-pnpm-html"].model_dump()) == {
        "id",
        "source_stacks",
        "build_system",
        "phase",
        "status",
    }


@pytest.mark.asyncio
async def test_put_version_creates_code_edit_version(runs_dir: Path) -> None:
    ws = _workspace(runs_dir)
    parent_sha = _git(ws, "rev-parse", "refs/s2c/versions/h1")

    response = await save_version(
        ws.run_id,
        "e1",
        SaveVersionRequest(parentCommitHash="h1", optionIndex=1, code="<edited/>"),
    )

    assert _git(ws, "rev-parse", "refs/s2c/versions/e1") == response.gitSha
    assert _git(ws, "rev-parse", f"{response.gitSha}^") == parent_sha
    assert _git(ws, "log", "-1", "--format=%s", response.gitSha) == (
        ":art: Version 2 — manual edit"
    )
    assert ws.option_codes("e1") == ["<a/>", "<edited/>"]


@pytest.mark.asyncio
async def test_put_version_updates_existing(runs_dir: Path) -> None:
    ws = _workspace(runs_dir)
    first = await save_version(
        ws.run_id,
        "e1",
        SaveVersionRequest(parentCommitHash="h1", optionIndex=0, code="<one/>"),
    )

    second = await save_version(
        ws.run_id,
        "e1",
        SaveVersionRequest(parentCommitHash="h1", optionIndex=0, code="<two/>"),
    )

    assert second.gitSha != first.gitSha
    assert _git(ws, "rev-parse", f"{second.gitSha}^") == first.gitSha
    assert _git(ws, "log", "-1", "--format=%s", second.gitSha) == (
        ":art: Version 2 — manual edit"
    )
    assert ws.option_codes("e1") == ["<two/>", "<b/>"]
    assert ws.version_number("e1") == 2


@pytest.mark.asyncio
async def test_put_version_returns_visual_qa(runs_dir: Path, fake_qa: FakeQa) -> None:
    ws = _workspace(runs_dir)

    response = await save_version(
        ws.run_id,
        "e1",
        SaveVersionRequest(parentCommitHash="h1", optionIndex=1, code="<edited/>"),
    )

    assert fake_qa.calls == [(ws.run_id, "e1", ["<a/>", "<edited/>"])]
    assert response.visualQa == {
        "commitHash": "e1",
        "options": [{"index": 0, "renderOk": True, "duplicateOf": None}],
    }
    assert response.gitSha == _git(ws, "rev-parse", "refs/s2c/versions/e1")


@pytest.mark.asyncio
async def test_put_version_omits_visual_qa_when_qa_fails(
    runs_dir: Path, fake_qa: FakeQa
) -> None:
    ws = _workspace(runs_dir)
    fake_qa.error = RuntimeError("no renderer")

    response = await save_version(
        ws.run_id,
        "e1",
        SaveVersionRequest(parentCommitHash="h1", optionIndex=0, code="<x/>"),
    )

    assert response.visualQa is None
    assert ws.has_version("e1")
    assert "visualQa" not in response.model_dump(exclude_none=True)


@pytest.mark.asyncio
async def test_put_version_omits_visual_qa_on_timeout(
    runs_dir: Path, fake_qa: FakeQa, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace(runs_dir)
    monkeypatch.setattr(runs, "VISUAL_QA_TIMEOUT_SECONDS", 0.05)
    fake_qa.delay = 1.0

    response = await save_version(
        ws.run_id,
        "e1",
        SaveVersionRequest(parentCommitHash="h1", optionIndex=0, code="<x/>"),
    )

    assert response.visualQa is None
    assert response.gitSha


def test_put_version_route_drops_null_visual_qa() -> None:
    route = next(
        r
        for r in runs.router.routes
        if getattr(r, "path", "") == "/api/runs/{run_id}/versions/{commit_hash}"
    )
    assert getattr(route, "response_model_exclude_none", False) is True


@pytest.mark.asyncio
async def test_put_version_unknown_run_404(runs_dir: Path) -> None:
    body = SaveVersionRequest(parentCommitHash="h1", optionIndex=0, code="<a/>")

    for run_id in [new_run_id(), "../../etc"]:
        with pytest.raises(HTTPException) as exc_info:
            await save_version(run_id, "e1", body)
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_put_version_unknown_parent_404(runs_dir: Path) -> None:
    ws = _workspace(runs_dir)

    with pytest.raises(HTTPException) as exc_info:
        await save_version(
            ws.run_id,
            "e1",
            SaveVersionRequest(parentCommitHash="nope", optionIndex=0, code="<a/>"),
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_put_version_too_large_413(runs_dir: Path) -> None:
    ws = _workspace(runs_dir)

    with pytest.raises(HTTPException) as exc_info:
        await save_version(
            ws.run_id,
            "e1",
            SaveVersionRequest(
                parentCommitHash="h1", optionIndex=0, code="x" * (2 * 1024 * 1024 + 1)
            ),
        )
    assert exc_info.value.status_code == 413
    assert not ws.has_version("e1")


@pytest.mark.asyncio
async def test_get_qa_file_serves_qa_pngs(runs_dir: Path) -> None:
    ws = _workspace(runs_dir)
    qa = ws.path / "qa" / "h1"
    qa.mkdir(parents=True)
    (qa / "op1-1280.png").write_bytes(b"\x89PNG-op1")
    (qa / "app-op2-1280.png").write_bytes(b"\x89PNG-app")
    (qa / "qa.json").write_text("{}", encoding="utf-8")

    response = await get_qa_file(ws.run_id, "h1", "op1-1280.png")
    assert isinstance(response, FileResponse)
    assert Path(response.path) == qa / "op1-1280.png"
    assert response.media_type == "image/png"
    app = await get_qa_file(ws.run_id, "h1", "app-op2-1280.png")
    assert Path(app.path) == qa / "app-op2-1280.png"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "run_id, commit_hash, file_name",
    [
        ("BAD", "h1", "op1-1280.png"),
        ("../../etc", "h1", "op1-1280.png"),
        (None, "nope", "op1-1280.png"),
        (None, "..", "op1-1280.png"),
        (None, "h1", "qa.json"),
        (None, "h1", "op1-1280.jpg"),
        (None, "h1", "../op1-1280.png"),
        (None, "h1", "opx-1280.png"),
        (None, "h1", "op2-375.png"),  # well-formed but missing
    ],
)
async def test_get_qa_file_404(
    runs_dir: Path, run_id: str | None, commit_hash: str, file_name: str
) -> None:
    ws = _workspace(runs_dir)
    qa = ws.path / "qa" / "h1"
    qa.mkdir(parents=True)
    (qa / "op1-1280.png").write_bytes(b"\x89PNG")
    (qa / "qa.json").write_text("{}", encoding="utf-8")
    (qa / "op1-1280.jpg").write_bytes(b"jpg")

    with pytest.raises(HTTPException) as exc_info:
        await get_qa_file(run_id or ws.run_id, commit_hash, file_name)
    assert exc_info.value.status_code == 404
