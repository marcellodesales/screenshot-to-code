import pytest
from fastapi import HTTPException

import config
from routes import builds
from routes.builds import StartBuildRequest, get_build, start_build
from stack_generator.builder import BuildJob, OptionStatus


class FakeManager:
    def __init__(self) -> None:
        self.started: list[tuple[str, str, str, dict[str, str | None]]] = []
        self.jobs: dict[str, BuildJob] = {}
        self.error: Exception | None = None
        self.options: list[list[int] | None] = []

    def start(
        self,
        run_id: str,
        ui_commit_hash: str,
        build_system: str,
        api_keys: dict[str, str | None],
        options: list[int] | None = None,
    ) -> BuildJob:
        if self.error is not None:
            raise self.error
        self.started.append((run_id, ui_commit_hash, build_system, api_keys))
        self.options.append(options)
        job = BuildJob(
            run_id=run_id,
            ui_commit_hash=ui_commit_hash,
            build_system=build_system,
            template_id="static-pnpm-html",
            options=[OptionStatus(index=0, state="queued", step_message="Queued", url=None, error=None)],
        )
        self.jobs[run_id] = job
        return job

    def get(self, run_id: str) -> BuildJob | None:
        return self.jobs.get(run_id)


RUN_ID = "run_20261008_101500_ab12cd34"


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> FakeManager:
    fake = FakeManager()
    monkeypatch.setattr(builds, "build_manager", fake)
    return fake


def _body(**extra: object) -> StartBuildRequest:
    return StartBuildRequest.model_validate(
        {"commitHash": "h1", "buildSystem": "pnpm", **extra}
    )


@pytest.mark.asyncio
async def test_build_route_disabled_403(
    manager: FakeManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "STACK_GENERATOR_ENABLED", False)
    with pytest.raises(HTTPException) as exc:
        await start_build(RUN_ID, _body())
    assert exc.value.status_code == 403
    assert exc.value.detail == "Stack generator disabled (set STACK_GENERATOR_ENABLED=true)"
    with pytest.raises(HTTPException) as exc:
        await get_build(RUN_ID)
    assert exc.value.status_code == 403
    assert manager.started == []


@pytest.mark.asyncio
async def test_build_route_starts_job_with_key_fallback(
    manager: FakeManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "STACK_GENERATOR_ENABLED", True)
    monkeypatch.setattr(config, "OPENAI_API_KEY", "env-openai")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)

    result = await start_build(RUN_ID, _body(anthropicApiKey="ui-anthropic"))

    assert result["run_id"] == RUN_ID
    assert result["template_id"] == "static-pnpm-html"
    assert result["options"][0]["step_message"] == "Queued"
    [(run_id, commit_hash, build_system, keys)] = manager.started
    assert (run_id, commit_hash, build_system) == (RUN_ID, "h1", "pnpm")
    assert keys == {
        "openai_api_key": "env-openai",
        "anthropic_api_key": "ui-anthropic",
        "gemini_api_key": None,
    }

    assert (await get_build(RUN_ID))["run_id"] == RUN_ID


@pytest.mark.asyncio
async def test_build_route_errors(
    manager: FakeManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "STACK_GENERATOR_ENABLED", True)

    with pytest.raises(HTTPException) as exc:
        await get_build(RUN_ID)
    assert exc.value.status_code == 404

    manager.error = KeyError("h1")
    with pytest.raises(HTTPException) as exc:
        await start_build(RUN_ID, _body())
    assert exc.value.status_code == 404

    manager.error = ValueError("No available stack template")
    with pytest.raises(HTTPException) as exc:
        await start_build(RUN_ID, _body())
    assert exc.value.status_code == 400


def test_builds_router_is_mounted() -> None:
    from main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/runs/{run_id}/build" in paths


@pytest.mark.asyncio
async def test_build_route_passes_selected_options(
    manager: FakeManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "STACK_GENERATOR_ENABLED", True)

    await start_build(RUN_ID, _body())
    await start_build(RUN_ID, _body(options=[0, 2]))

    assert manager.options == [None, [0, 2]]
    job = await get_build(RUN_ID)
    option = job["options"][0]
    for key in ("screenshot", "parity", "responsive", "render_ok"):
        assert key in option and option[key] is None
