"""Run workspace HTTP routes: stack catalog and manual-edit versions (spec §2.2)."""

import asyncio
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from stack_generator.catalog import load_catalog
from stack_generator.visual_qa import qa_dir, run_version_qa
from stack_generator.workspace import RunWorkspace

router = APIRouter()

MAX_CODE_BYTES = 2 * 1024 * 1024
QA_FILE_PATTERN = re.compile(r"^(app-)?op\d+-\d+\.png$")
# Same bound as the websocket path: QA must never hold a save up for long.
VISUAL_QA_TIMEOUT_SECONDS = 20.0


class StackInfo(BaseModel):
    id: str
    source_stacks: list[str]
    build_system: str
    phase: int
    status: str


class SaveVersionRequest(BaseModel):
    parentCommitHash: str | None = None
    optionIndex: int = Field(ge=0)
    code: str


class SaveVersionResponse(BaseModel):
    gitSha: str
    # The websocket ``visualQa.data`` shape; omitted when QA failed/timed out.
    visualQa: dict[str, Any] | None = None


@router.get("/api/stacks")
async def list_stacks() -> list[StackInfo]:
    catalog = await asyncio.to_thread(load_catalog)
    return [
        StackInfo(
            id=template.id,
            source_stacks=template.source_stacks,
            build_system=template.build_system,
            phase=template.phase,
            status=template.status,
        )
        for template in catalog
    ]


def _save_version(
    workspace: RunWorkspace, commit_hash: str, body: SaveVersionRequest
) -> str:
    if workspace.has_version(commit_hash):
        number = workspace.version_number(commit_hash)
        return workspace.update_version(
            commit_hash,
            body.optionIndex,
            body.code,
            f":art: Version {number} — manual edit",
        )

    # First save of a code_edit version: the parent's options with the edited
    # one replaced.
    if not body.parentCommitHash or not workspace.has_version(body.parentCommitHash):
        raise HTTPException(status_code=404, detail="Unknown parent version")
    option_codes = workspace.option_codes(body.parentCommitHash)
    while len(option_codes) <= body.optionIndex:
        option_codes.append("")
    option_codes[body.optionIndex] = body.code
    number = len(workspace.metadata.get("versions") or []) + 1
    return workspace.commit_version(
        ui_commit_hash=commit_hash,
        parent_ui_commit_hash=body.parentCommitHash,
        option_codes=option_codes,
        message=f":art: Version {number} — manual edit",
    )


async def _version_qa(workspace: RunWorkspace, commit_hash: str) -> dict[str, Any] | None:
    """Best-effort visual QA of a saved version (bounded; never fatal)."""
    try:
        return await asyncio.wait_for(
            run_version_qa(workspace, commit_hash),
            timeout=VISUAL_QA_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        print(f"[VISUAL_QA] Skipped: took over {VISUAL_QA_TIMEOUT_SECONDS}s")
    except Exception as e:
        print(f"[VISUAL_QA] Skipped: {e}")
    return None


@router.put(
    "/api/runs/{run_id}/versions/{commit_hash}", response_model_exclude_none=True
)
async def save_version(
    run_id: str, commit_hash: str, body: SaveVersionRequest
) -> SaveVersionResponse:
    if len(body.code.encode("utf-8")) > MAX_CODE_BYTES:
        raise HTTPException(status_code=413, detail="Code is larger than 2 MB")

    workspace = await asyncio.to_thread(RunWorkspace.open, run_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Unknown run")

    try:
        git_sha = await asyncio.to_thread(_save_version, workspace, commit_hash, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    visual_qa = await _version_qa(workspace, commit_hash)
    return SaveVersionResponse(gitSha=git_sha, visualQa=visual_qa)


def _qa_file(run_id: str, commit_hash: str, file_name: str) -> Path | None:
    workspace = RunWorkspace.open(run_id)
    # has_version also rejects malformed commit hashes (no path traversal).
    if workspace is None or not workspace.has_version(commit_hash):
        return None
    path = qa_dir(workspace, commit_hash) / file_name
    return path if path.is_file() else None


@router.get("/api/runs/{run_id}/qa/{commit_hash}/{file_name}")
async def get_qa_file(run_id: str, commit_hash: str, file_name: str) -> FileResponse:
    """A visual QA screenshot (``op<N>-<width>.png`` / ``app-op<N>-<width>.png``)."""
    if not QA_FILE_PATTERN.match(file_name):
        raise HTTPException(status_code=404, detail="Not found")
    path = await asyncio.to_thread(_qa_file, run_id, commit_hash, file_name)
    if path is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="image/png")
