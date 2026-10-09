import re
import subprocess
from pathlib import Path

import pytest
import yaml

from stack_generator.workspace import RunWorkspace, new_run_id, run_dir_for


def _git(ws: RunWorkspace, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ws.path, check=True, capture_output=True, text=True
    ).stdout.strip()


def _create(tmp_path: Path) -> RunWorkspace:
    return RunWorkspace.create(
        new_run_id(),
        source_stack="react_tailwind",
        input_mode="image",
        prompt_text="Coffee shop landing page",
        runs_dir=tmp_path,
    )


def test_new_run_id_format() -> None:
    assert re.match(r"^run_\d{8}_\d{6}_[0-9a-f]{8}$", new_run_id())


def test_create_initialises_repo_and_stack_yaml(tmp_path: Path) -> None:
    ws = _create(tmp_path)

    assert ws.path.parent == tmp_path
    assert (ws.path / ".git").is_dir()
    meta = yaml.safe_load((ws.path / "stack.yaml").read_text(encoding="utf-8"))
    assert meta["run_id"] == ws.run_id
    assert meta["source_stack"] == "react_tailwind"
    assert meta["input_mode"] == "image"
    assert meta["prompt"] == "Coffee shop landing page"
    assert "uploads/" in (ws.path / ".gitignore").read_text(encoding="utf-8")
    assert _git(ws, "symbolic-ref", "HEAD") == "refs/heads/main"

    reopened = RunWorkspace.open(ws.run_id, runs_dir=tmp_path)
    assert reopened is not None and reopened.path == ws.path
    assert RunWorkspace.open(new_run_id(), runs_dir=tmp_path) is None


def test_commit_version_writes_mocks_and_message(tmp_path: Path) -> None:
    ws = _create(tmp_path)
    message = ":art: Version 1 — mock (react_tailwind)"

    sha = ws.commit_version(
        ui_commit_hash="h1",
        parent_ui_commit_hash=None,
        option_codes=["<a/>", "<b/>"],
        message=message,
    )

    assert re.match(r"^[0-9a-f]{40}$", sha)
    assert (ws.path / "op1/design/mock.html").read_text(encoding="utf-8") == "<a/>"
    assert (ws.path / "op2/design/mock.html").read_text(encoding="utf-8") == "<b/>"
    assert _git(ws, "log", "-1", "--format=%s", sha) == message
    assert _git(ws, "log", "-1", "--format=%an <%ae>", sha) == (
        "screenshot-to-code <noreply@screenshot-to-code.local>"
    )
    assert _git(ws, "rev-parse", "refs/s2c/versions/h1") == sha
    assert _git(ws, "rev-parse", "main") == sha
    tracked = _git(ws, "ls-tree", "-r", "--name-only", sha).splitlines()
    assert set(tracked) == {
        ".gitignore",
        "stack.yaml",
        "op1/design/mock.html",
        "op2/design/mock.html",
    }
    assert ws.has_version("h1")
    assert not ws.has_version("nope")
    assert ws.version_number("h1") == 1
    assert ws.option_codes("h1") == ["<a/>", "<b/>"]
    versions = yaml.safe_load((ws.path / "stack.yaml").read_text(encoding="utf-8"))[
        "versions"
    ]
    assert versions == [
        {"n": 1, "ui_commit_hash": "h1", "parent": None, "message": message}
    ]
    # The committed stack.yaml is the working copy: no SHA written back.
    assert _git(ws, "show", f"{sha}:stack.yaml") == (
        (ws.path / "stack.yaml").read_text(encoding="utf-8").strip()
    )


def test_commit_version_drops_extra_options(tmp_path: Path) -> None:
    ws = _create(tmp_path)
    ws.commit_version(
        ui_commit_hash="h1",
        parent_ui_commit_hash=None,
        option_codes=["<a/>", "<b/>"],
        message="v1",
    )

    sha = ws.commit_version(
        ui_commit_hash="h2",
        parent_ui_commit_hash="h1",
        option_codes=["<c/>"],
        message="v2",
    )

    assert ws.option_codes("h2") == ["<c/>"]
    assert ws.option_codes("h1") == ["<a/>", "<b/>"]
    assert "op2/design/mock.html" not in _git(ws, "ls-tree", "-r", "--name-only", sha)
    assert not (ws.path / "op2/design").exists()


def test_fork_parent_is_parent_ref(tmp_path: Path) -> None:
    ws = _create(tmp_path)
    h1 = ws.commit_version(
        ui_commit_hash="h1", parent_ui_commit_hash=None, option_codes=["1"], message="v1"
    )
    ws.commit_version(
        ui_commit_hash="h2", parent_ui_commit_hash="h1", option_codes=["2"], message="v2"
    )
    h3 = ws.commit_version(
        ui_commit_hash="h3", parent_ui_commit_hash="h1", option_codes=["3"], message="v3"
    )

    assert _git(ws, "rev-parse", f"{h3}^") == h1
    assert _git(ws, "rev-parse", "main") == h3
    assert ws.version_number("h3") == 3


def test_update_version_manual_edit(tmp_path: Path) -> None:
    ws = _create(tmp_path)
    old = ws.commit_version(
        ui_commit_hash="h1",
        parent_ui_commit_hash=None,
        option_codes=["<a/>", "<b/>"],
        message="v1",
    )

    new = ws.update_version("h1", 1, "<edited/>", ":art: Version 1 — manual edit")

    assert new != old
    assert _git(ws, "rev-parse", f"{new}^") == old
    assert _git(ws, "rev-parse", "refs/s2c/versions/h1") == new
    assert _git(ws, "rev-parse", "main") == new
    assert ws.option_codes("h1") == ["<a/>", "<edited/>"]


def test_uploads_not_tracked(tmp_path: Path) -> None:
    ws = _create(tmp_path)
    ws.commit_version(
        ui_commit_hash="h1", parent_ui_commit_hash=None, option_codes=["1"], message="v1"
    )
    ws.update_version("h1", 0, "edited", "v1 manual edit")

    path = ws.save_upload("video", "data:video/mp4;base64,AAAA")

    assert path.parent == ws.path / "uploads" / "video"
    assert path.read_bytes() == b"\x00\x00\x00"
    # Nothing drifts from the committed tree: not uploads, not stack.yaml.
    assert _git(ws, "status", "--porcelain") == ""
    assert _git(ws, "check-ignore", str(path.relative_to(ws.path)))


def test_checkout_version_and_commit_app(tmp_path: Path) -> None:
    ws = _create(tmp_path)
    v1 = ws.commit_version(
        ui_commit_hash="h1", parent_ui_commit_hash=None, option_codes=["<a/>"], message="v1"
    )
    dest = tmp_path / "checkout"
    dest.mkdir()

    ws.checkout_version("h1", dest)
    assert (dest / "op1/design/mock.html").read_text(encoding="utf-8") == "<a/>"

    app_dir = ws.path / "op1" / "app"
    app_dir.mkdir()
    (app_dir / "package.json").write_text("{}", encoding="utf-8")
    sha = ws.commit_app("h1", ":tada: First version")

    assert _git(ws, "rev-parse", f"{sha}^") == v1
    assert _git(ws, "rev-parse", "main") == sha
    assert _git(ws, "rev-parse", "refs/s2c/versions/h1") == v1
    assert "op1/app/package.json" in _git(ws, "ls-tree", "-r", "--name-only", sha)


def test_run_dir_for_rejects_traversal(tmp_path: Path) -> None:
    assert run_dir_for("../../etc", tmp_path) is None
    assert run_dir_for("run_x", tmp_path) is None
    assert run_dir_for("run_20261008_101500_ab12cd34/../x", tmp_path) is None
    assert (
        run_dir_for("run_20261008_101500_ab12cd34", tmp_path)
        == tmp_path / "run_20261008_101500_ab12cd34"
    )


def test_invalid_ui_commit_hash_rejected(tmp_path: Path) -> None:
    ws = _create(tmp_path)

    assert not ws.has_version("../main")
    with pytest.raises(ValueError):
        ws.commit_version(
            ui_commit_hash="../x",
            parent_ui_commit_hash=None,
            option_codes=["1"],
            message="v1",
        )


def test_qa_dir_is_gitignored(tmp_path: Path) -> None:
    ws = _create(tmp_path)
    ignored = (ws.path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "uploads/" in ignored and "qa/" in ignored

    # Runs created before qa/ existed get it on their next version.
    (ws.path / ".gitignore").write_text("uploads/\n", encoding="utf-8")
    sha = ws.commit_version(
        ui_commit_hash="h1",
        parent_ui_commit_hash=None,
        option_codes=["<a/>"],
        message="v1",
    )
    assert "qa/" in (ws.path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "qa/" in _git(ws, "show", f"{sha}:.gitignore").splitlines()
    (ws.path / "qa" / "h1").mkdir(parents=True)
    (ws.path / "qa" / "h1" / "op1-1280.png").write_bytes(b"png")
    assert _git(ws, "status", "--porcelain") == ""
