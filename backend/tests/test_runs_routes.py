import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from routes.runs import SaveVersionRequest, list_stacks, save_version
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
