import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from stack_generator.builder import BuildManager
from stack_generator.migrate import MigrationLlm
from stack_generator.workspace import RunWorkspace, new_run_id

STATIC_MOCK = "<html><body>STATIC-MOCK</body></html>"


class FakeRunner:
    """Records commands; can fail or block per app dir."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path]] = []
        self.fail_in: set[str] = set()
        self.gate: asyncio.Event | None = None

    async def __call__(self, argv: list[str], cwd: Path) -> str:
        self.calls.append((argv, cwd))
        if self.gate is not None:
            await self.gate.wait()
        if argv[0].endswith("scaffold.sh"):
            app_dir = Path(argv[1])
            (app_dir / "src/app").mkdir(parents=True, exist_ok=True)
            (app_dir / "src/app/layout.tsx").write_text(
                'import { Geist } from "next/font/google";\n'
            )
            (app_dir / "src/app/globals.css").write_text(
                '@import "tailwindcss";\n@theme inline {\n'
                "  --font-sans: var(--font-geist-sans);\n}\n"
            )
            (app_dir / ".gitignore").write_text(".env*\nnode_modules\n")
        for marker in self.fail_in:
            if marker in str(cwd):
                raise RuntimeError(f"compose failed in {marker}")
        return ""

    def compose_calls(self) -> list[tuple[list[str], Path]]:
        return [(argv, cwd) for argv, cwd in self.calls if argv[:2] == ["docker", "compose"]]


def _no_llm_factory(**_: str | None) -> MigrationLlm:
    raise AssertionError("static builds must not need an LLM")


def _make_run(
    runs_dir: Path, *, source_stack: str, codes: list[str], prompt: str = "Coffee shop"
) -> RunWorkspace:
    workspace = RunWorkspace.create(
        new_run_id(),
        source_stack=source_stack,
        input_mode="text",
        prompt_text=prompt,
        runs_dir=runs_dir,
    )
    workspace.commit_version(
        ui_commit_hash="h1",
        parent_ui_commit_hash=None,
        option_codes=codes,
        message=f":art: Version 1 — mock ({source_stack})",
    )
    return workspace


def _subjects(workspace: RunWorkspace) -> list[str]:
    out = subprocess.run(
        ["git", "-c", "safe.directory=*", "log", "--all", "--format=%s"],
        cwd=workspace.path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return out.splitlines()


@pytest.mark.asyncio
async def test_build_static_option_runs_compose(tmp_path: Path) -> None:
    workspace = _make_run(tmp_path, source_stack="html_tailwind", codes=[STATIC_MOCK])
    runner = FakeRunner()
    manager = BuildManager(runner=runner, llm_factory=_no_llm_factory, runs_dir=tmp_path)

    job = manager.start(workspace.run_id, "h1", "pnpm", {})
    assert job.template_id == "static-pnpm-html"
    await manager.wait(workspace.run_id)

    option = job.options[0]
    assert option.state == "running", option.error
    app_id = workspace.run_id.replace("_", "-") + "-op1"
    assert option.url == f"http://{app_id}.localhost:3311/"

    app_dir = workspace.path / "op1" / "app"
    assert (app_dir / "public/index.html").read_text() == STATIC_MOCK
    assert (app_dir / "Dockerfile").exists()
    env = (app_dir / ".env").read_text()
    assert f"APP_ID={app_id}\n" in env
    assert f"APP_HOST={app_id}.localhost\n" in env

    [(argv, cwd)] = runner.compose_calls()
    assert argv == [
        "docker", "compose", "--project-directory", str(app_dir),
        "up", "-d", "--build", "--wait",
    ]
    assert cwd == app_dir
    assert manager.get(workspace.run_id) is job


@pytest.mark.asyncio
async def test_build_nextjs_scaffolds_and_migrates(tmp_path: Path) -> None:
    mock = "<html><body><script type='text/babel'>function App(){}</script></body></html>"
    workspace = _make_run(
        tmp_path, source_stack="react_tailwind", codes=[mock], prompt="Build me a Coffee Shop"
    )
    runner = FakeRunner()
    seen_keys: list[dict[str, str | None]] = []

    def llm_factory(**keys: str | None) -> MigrationLlm:
        seen_keys.append(keys)

        async def llm(system: str, user: str) -> str:
            return json.dumps(
                {"files": {"src/app/page.tsx": "export default function Page() { return null; }"}}
            )

        return llm

    manager = BuildManager(runner=runner, llm_factory=llm_factory, runs_dir=tmp_path)
    job = manager.start(
        workspace.run_id, "h1", "pnpm", {"anthropic_api_key": "sk-a"}
    )
    assert job.template_id == "nextjs-pnpm-react-tailwind"
    await manager.wait(workspace.run_id)
    assert job.options[0].state == "running", job.options[0].error

    app_dir = workspace.path / "op1" / "app"
    scaffold = [argv for argv, _ in runner.calls if argv[0].endswith("scaffold.sh")]
    assert scaffold == [
        [scaffold[0][0], str(app_dir), "coffee-shop", str(scaffold[0][3])]
    ]
    assert "export default function Page" in (app_dir / "src/app/page.tsx").read_text()
    assert (app_dir / "design/mock.html").read_text() == mock
    layout = (app_dir / "src/app/layout.tsx").read_text()
    assert "next/font" not in layout
    assert "geist" not in (app_dir / "src/app/globals.css").read_text()
    assert seen_keys[0]["anthropic_api_key"] == "sk-a"


@pytest.mark.asyncio
async def test_one_option_failure_isolated(tmp_path: Path) -> None:
    workspace = _make_run(
        tmp_path, source_stack="html_css", codes=[STATIC_MOCK, STATIC_MOCK]
    )
    runner = FakeRunner()
    runner.fail_in = {"op2"}
    manager = BuildManager(runner=runner, llm_factory=_no_llm_factory, runs_dir=tmp_path)

    job = manager.start(workspace.run_id, "h1", "pnpm", {})
    await manager.wait(workspace.run_id)

    first, second = job.options
    assert first.state == "running"
    assert first.url is not None
    assert second.state == "failed"
    assert second.error is not None and "compose failed in op2" in second.error
    assert second.url is None


@pytest.mark.asyncio
async def test_migration_failure_isolated(tmp_path: Path) -> None:
    workspace = _make_run(
        tmp_path, source_stack="react_tailwind", codes=["<p>GOOD</p>", "<p>BAD</p>"]
    )

    def llm_factory(**_: str | None) -> MigrationLlm:
        async def llm(system: str, user: str) -> str:
            if "BAD" in user:
                return json.dumps({"files": {"../../etc/passwd.ts": "x"}})
            return json.dumps({"files": {"src/app/page.tsx": "export default 1"}})

        return llm

    manager = BuildManager(runner=FakeRunner(), llm_factory=llm_factory, runs_dir=tmp_path)
    job = manager.start(workspace.run_id, "h1", "pnpm", {})
    await manager.wait(workspace.run_id)

    assert job.options[0].state == "running"
    assert job.options[1].state == "failed"
    assert not (tmp_path.parent / "etc").exists()
    # A failed option's partial app is not committed.
    tree = subprocess.run(
        ["git", "-c", "safe.directory=*", "ls-tree", "-r", "--name-only", "main"],
        cwd=workspace.path, check=True, capture_output=True, text=True,
    ).stdout
    assert "op1/app/src/app/page.tsx" in tree
    assert "op2/app/" not in tree


@pytest.mark.asyncio
async def test_second_start_returns_running_job(tmp_path: Path) -> None:
    workspace = _make_run(tmp_path, source_stack="html_css", codes=[STATIC_MOCK])
    runner = FakeRunner()
    runner.gate = asyncio.Event()
    manager = BuildManager(runner=runner, llm_factory=_no_llm_factory, runs_dir=tmp_path)

    first = manager.start(workspace.run_id, "h1", "pnpm", {})
    await asyncio.sleep(0.2)
    second = manager.start(workspace.run_id, "h1", "pnpm", {})
    assert second is first

    runner.gate.set()
    await manager.wait(workspace.run_id)
    assert len(runner.compose_calls()) == 1
    assert first.options[0].state == "running"

    # Once finished, a new start is a new job.
    third = manager.start(workspace.run_id, "h1", "pnpm", {})
    assert third is not first
    await manager.wait(workspace.run_id)


@pytest.mark.asyncio
async def test_commit_messages_first_then_rebuild(tmp_path: Path) -> None:
    workspace = _make_run(tmp_path, source_stack="html_css", codes=[STATIC_MOCK])
    manager = BuildManager(runner=FakeRunner(), llm_factory=_no_llm_factory, runs_dir=tmp_path)

    manager.start(workspace.run_id, "h1", "pnpm", {})
    await manager.wait(workspace.run_id)
    assert _subjects(workspace)[0] == ":tada: First version"

    manager.start(workspace.run_id, "h1", "pnpm", {})
    await manager.wait(workspace.run_id)
    subjects = _subjects(workspace)
    assert subjects[0] == ":rocket: Build app from version 1"
    assert subjects.count(":tada: First version") == 1


def test_start_rejects_unknown_run_and_version(tmp_path: Path) -> None:
    workspace = _make_run(tmp_path, source_stack="html_css", codes=[STATIC_MOCK])
    manager = BuildManager(runner=FakeRunner(), llm_factory=_no_llm_factory, runs_dir=tmp_path)
    with pytest.raises(LookupError):
        manager.start("run_20261008_101500_ab12cd34", "h1", "pnpm", {})
    with pytest.raises(LookupError):
        manager.start("../../etc", "h1", "pnpm", {})
    with pytest.raises(LookupError):
        manager.start(workspace.run_id, "nope", "pnpm", {})
    with pytest.raises(ValueError):
        manager.start(workspace.run_id, "h1", "bun", {})
