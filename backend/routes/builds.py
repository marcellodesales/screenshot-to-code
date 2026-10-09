"""Build app routes (spec §7): start a build of a run version, poll its progress."""

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

import config
from stack_generator.builder import BuildJob, BuildManager

router = APIRouter()

DISABLED_DETAIL = "Stack generator disabled (set STACK_GENERATOR_ENABLED=true)"

# One manager per process: it owns the in-memory job table.
build_manager = BuildManager()


class StartBuildRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    commit_hash: str = Field(alias="commitHash", min_length=1)
    build_system: str = Field(alias="buildSystem", min_length=1)
    openai_api_key: str | None = Field(default=None, alias="openAiApiKey")
    anthropic_api_key: str | None = Field(default=None, alias="anthropicApiKey")
    gemini_api_key: str | None = Field(default=None, alias="geminiApiKey")
    # 0-based option indices; absent = every option QA didn't mark a duplicate.
    options: list[int] | None = None


def _require_enabled() -> None:
    if not config.STACK_GENERATOR_ENABLED:
        raise HTTPException(status_code=403, detail=DISABLED_DETAIL)


def _job_json(job: BuildJob) -> dict[str, Any]:
    return asdict(job)


@router.post("/api/runs/{run_id}/build")
async def start_build(run_id: str, body: StartBuildRequest) -> dict[str, Any]:
    _require_enabled()
    api_keys: dict[str, str | None] = {
        "openai_api_key": body.openai_api_key or config.OPENAI_API_KEY,
        "anthropic_api_key": body.anthropic_api_key or config.ANTHROPIC_API_KEY,
        "gemini_api_key": body.gemini_api_key or config.GEMINI_API_KEY,
    }
    try:
        job = build_manager.start(
            run_id, body.commit_hash, body.build_system, api_keys, options=body.options
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'\""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _job_json(job)


@router.get("/api/runs/{run_id}/build")
async def get_build(run_id: str) -> dict[str, Any]:
    _require_enabled()
    job = build_manager.get(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No build for this run")
    return _job_json(job)
