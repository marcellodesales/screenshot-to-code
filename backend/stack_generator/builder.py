"""The "Build app" pipeline (spec §7): version mocks -> stack app -> commit -> compose up.

Per option: scaffold (``scaffold.sh``; static templates are copied), migrate the
mock, write ``.env``; then one ``commit_app`` for every prepared option; then
``docker compose up -d --build --wait`` per option. Options run concurrently
and one option failing never stops the others.

Docker runs against the host daemon through the mounted socket, so nothing
here relies on bind mounts (spec §7.1).
"""

import asyncio
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Literal, Protocol

from stack_generator.catalog import StackTemplate, load_catalog, resolve_template
from stack_generator.migrate import (
    MigrationLlm,
    apply_system_fonts,
    default_migration_llm,
    migrate_mock,
)
from stack_generator.naming import app_id_for, app_slug_from_prompt
from stack_generator.workspace import RunWorkspace

OptionState = Literal[
    "queued", "scaffolding", "migrating", "committing", "starting", "running", "failed"
]
CommandRunner = Callable[[list[str], Path], Awaitable[str]]

GATEWAY_PORT = 3311
COMMAND_TIMEOUT_SECONDS = 15 * 60
_ERROR_LIMIT = 2000
_FIRST_BUILD_MESSAGE = ":tada: First version"
# Each build commit is pinned as refs/s2c/builds/<k> (k = 1, 2, ...).
_BUILD_REF_PREFIX = "refs/s2c/builds/"


class MigrationLlmFactory(Protocol):
    def __call__(
        self,
        *,
        openai_api_key: str | None,
        anthropic_api_key: str | None,
        gemini_api_key: str | None,
    ) -> MigrationLlm: ...


@dataclass
class OptionStatus:
    index: int
    state: OptionState
    step_message: str
    url: str | None
    error: str | None


@dataclass
class BuildJob:
    run_id: str
    ui_commit_hash: str
    build_system: str
    template_id: str
    options: list[OptionStatus] = field(default_factory=lambda: [])

    @property
    def finished(self) -> bool:
        return all(option.state in ("running", "failed") for option in self.options)


class CommandError(RuntimeError):
    pass


async def run_command(argv: list[str], cwd: Path) -> str:
    """Default runner: subprocess; raises ``CommandError`` with stderr on failure."""
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=COMMAND_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise CommandError(f"{argv[0]} timed out after {COMMAND_TIMEOUT_SECONDS}s")
    if process.returncode != 0:
        detail = (stderr or stdout).decode("utf-8", "replace").strip()
        raise CommandError(
            f"{Path(argv[0]).name} exited with {process.returncode}: {detail[-_ERROR_LIMIT:]}"
        )
    return stdout.decode("utf-8", "replace")


def _error_text(exc: BaseException) -> str:
    text = str(exc) or type(exc).__name__
    return text[-_ERROR_LIMIT:]


def _app_title(slug: str) -> str:
    return slug.replace("-", " ").strip().title() or "App"


def _write_files(app_dir: Path, files: dict[str, str]) -> None:
    root = app_dir.resolve()
    for relative, content in files.items():
        target = (app_dir / relative).resolve()
        # Defense in depth: migrate_mock already validated the paths.
        if not target.is_relative_to(root):
            raise ValueError(f"Refusing to write outside the app: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _copy_static_template(template: StackTemplate, app_dir: Path) -> None:
    shutil.copytree(
        template.path,
        app_dir,
        ignore=shutil.ignore_patterns("tests", "template.yaml", ".env"),
    )


def _git(workspace: RunWorkspace, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "safe.directory=*", *args],
        cwd=workspace.path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _build_refs(workspace: RunWorkspace) -> list[str]:
    return _git(
        workspace, "for-each-ref", "--format=%(refname)", _BUILD_REF_PREFIX
    ).split()


def _pin_build(workspace: RunWorkspace, sha: str) -> None:
    """Keep every build reachable (``main`` moves on with later versions)."""
    _git(
        workspace,
        "update-ref",
        f"{_BUILD_REF_PREFIX}{len(_build_refs(workspace)) + 1}",
        sha,
    )


@dataclass
class _JobContext:
    workspace: RunWorkspace
    template: StackTemplate
    checkout_dir: Path
    slug: str
    api_keys: dict[str, str | None]


class BuildManager:
    def __init__(
        self,
        runner: CommandRunner = run_command,
        llm_factory: MigrationLlmFactory = default_migration_llm,
        *,
        runs_dir: Path | None = None,
        templates_dir: Path | None = None,
    ) -> None:
        self._runner = runner
        self._llm_factory = llm_factory
        self._runs_dir = runs_dir
        self._templates_dir = templates_dir
        self._jobs: dict[str, BuildJob] = {}
        self._tasks: dict[str, "asyncio.Task[None]"] = {}

    def get(self, run_id: str) -> BuildJob | None:
        return self._jobs.get(run_id)

    def start(
        self,
        run_id: str,
        ui_commit_hash: str,
        build_system: str,
        api_keys: dict[str, str | None],
    ) -> BuildJob:
        """Start a build; while one is in progress for the run, return it.

        Raises ``LookupError`` for an unknown run/version and ``ValueError``
        when no template fits the source stack + build system. No ``await``
        happens between the in-progress check and registering the job, so two
        concurrent requests can never start two builds of one run.
        """
        existing = self._jobs.get(run_id)
        if existing is not None and not existing.finished:
            return existing

        workspace = RunWorkspace.open(run_id, self._runs_dir)
        if workspace is None:
            raise LookupError(f"Unknown run: {run_id}")
        if not workspace.has_version(ui_commit_hash):
            raise LookupError(f"Unknown version: {ui_commit_hash}")
        metadata = workspace.metadata
        template = resolve_template(
            str(metadata.get("source_stack", "")),
            build_system,
            load_catalog(self._templates_dir),
        )
        option_count = len(workspace.option_codes(ui_commit_hash))
        job = BuildJob(
            run_id=run_id,
            ui_commit_hash=ui_commit_hash,
            build_system=build_system,
            template_id=template.id,
            options=[
                OptionStatus(index=i, state="queued", step_message="Queued", url=None, error=None)
                for i in range(option_count)
            ],
        )
        slug = app_slug_from_prompt(str(metadata.get("prompt") or ""), run_id)
        self._jobs[run_id] = job
        self._tasks[run_id] = asyncio.create_task(
            self._run_guarded(job, workspace, template, slug, dict(api_keys))
        )
        return job

    async def wait(self, run_id: str) -> None:
        task = self._tasks.get(run_id)
        if task is not None:
            await task

    # -- pipeline ------------------------------------------------------------

    async def _run_guarded(
        self,
        job: BuildJob,
        workspace: RunWorkspace,
        template: StackTemplate,
        slug: str,
        api_keys: dict[str, str | None],
    ) -> None:
        try:
            await self._run(job, workspace, template, slug, api_keys)
        except Exception as exc:
            # A bug must not leave the job "in progress" forever (that would
            # block every later build of the run).
            for option in job.options:
                if option.state not in ("running", "failed"):
                    self._fail(option, exc)

    async def _run(
        self,
        job: BuildJob,
        workspace: RunWorkspace,
        template: StackTemplate,
        slug: str,
        api_keys: dict[str, str | None],
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="s2c-build-") as tmp:
            checkout_dir = Path(tmp)
            try:
                await asyncio.to_thread(
                    workspace.checkout_version, job.ui_commit_hash, checkout_dir
                )
            except Exception as exc:
                self._fail_all(job, f"Checking out version failed: {_error_text(exc)}")
                return
            context = _JobContext(workspace, template, checkout_dir, slug, api_keys)
            prepared = await asyncio.gather(
                *(self._prepare(job, option, context) for option in job.options)
            )

        ready = [
            (option, app_dir)
            for option, app_dir in zip(job.options, prepared)
            if app_dir is not None
        ]
        if not ready:
            return
        if not await self._commit(job, workspace, [option for option, _ in ready]):
            return
        await asyncio.gather(*(self._start(job, option, app_dir) for option, app_dir in ready))

    async def _prepare(
        self, job: BuildJob, option: OptionStatus, context: _JobContext
    ) -> Path | None:
        number = option.index + 1
        app_dir = context.workspace.path / f"op{number}" / "app"
        try:
            template = context.template
            self._set(option, "scaffolding", f"Scaffolding {template.id}")
            if app_dir.exists():
                await asyncio.to_thread(shutil.rmtree, app_dir)
            if template.has_scaffold:
                await self._runner(
                    [
                        str(template.path / "scaffold.sh"),
                        str(app_dir),
                        context.slug,
                        str(context.checkout_dir / f"op{number}"),
                    ],
                    context.workspace.path,
                )
            else:
                await asyncio.to_thread(_copy_static_template, template, app_dir)

            self._set(option, "migrating", "Migrating the mock into the stack")
            mock_html = (
                context.checkout_dir / f"op{number}" / "design" / "mock.html"
            ).read_text(encoding="utf-8")
            title = _app_title(context.slug)
            llm = self._llm_for(template, context.api_keys)
            files = await migrate_mock(
                mock_html=mock_html, template=template, app_title=title, llm=llm
            )
            _write_files(app_dir, files)
            if template.has_scaffold:
                apply_system_fonts(app_dir, title)

            app_id = app_id_for(job.run_id, option.index)
            (app_dir / ".env").write_text(
                f"APP_ID={app_id}\nAPP_HOST={app_id}.localhost\n", encoding="utf-8"
            )
            return app_dir
        except Exception as exc:
            self._fail(option, exc)
            # Never commit a half-built app.
            await asyncio.to_thread(shutil.rmtree, app_dir, True)
            return None

    def _llm_for(
        self, template: StackTemplate, api_keys: dict[str, str | None]
    ) -> MigrationLlm:
        if not template.has_scaffold:

            async def unused(_system: str, _user: str) -> str:
                raise RuntimeError("Static templates do not migrate with an LLM")

            return unused
        return self._llm_factory(
            openai_api_key=api_keys.get("openai_api_key"),
            anthropic_api_key=api_keys.get("anthropic_api_key"),
            gemini_api_key=api_keys.get("gemini_api_key"),
        )

    async def _commit(
        self, job: BuildJob, workspace: RunWorkspace, options: list[OptionStatus]
    ) -> bool:
        for option in options:
            self._set(option, "committing", "Committing the app")
        try:
            if await asyncio.to_thread(_build_refs, workspace):
                number = workspace.version_number(job.ui_commit_hash)
                message = f":rocket: Build app from version {number}"
            else:
                message = _FIRST_BUILD_MESSAGE
            sha = await asyncio.to_thread(
                workspace.commit_app, job.ui_commit_hash, message
            )
            await asyncio.to_thread(_pin_build, workspace, sha)
        except Exception as exc:
            for option in options:
                self._fail(option, exc, prefix="Commit failed: ")
            return False
        return True

    async def _start(self, job: BuildJob, option: OptionStatus, app_dir: Path) -> None:
        self._set(option, "starting", "docker compose up --build")
        try:
            await self._runner(
                [
                    "docker", "compose", "--project-directory", str(app_dir),
                    "up", "-d", "--build", "--wait",
                ],
                app_dir,
            )
        except Exception as exc:
            self._fail(option, exc)
            return
        app_id = app_id_for(job.run_id, option.index)
        option.url = f"http://{app_id}.localhost:{GATEWAY_PORT}/"
        self._set(option, "running", "Running")

    # -- state helpers -------------------------------------------------------

    @staticmethod
    def _set(option: OptionStatus, state: OptionState, message: str) -> None:
        option.state = state
        option.step_message = message

    @staticmethod
    def _fail(option: OptionStatus, exc: BaseException, prefix: str = "") -> None:
        option.error = prefix + _error_text(exc)
        option.step_message = f"Failed while {option.state}"
        option.state = "failed"

    @staticmethod
    def _fail_all(job: BuildJob, message: str) -> None:
        for option in job.options:
            option.error = message
            option.step_message = "Failed"
            option.state = "failed"
