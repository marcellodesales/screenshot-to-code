"""Run workspace HTTP routes: stack catalog and manual-edit versions (spec §2.2)."""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from stack_generator.catalog import load_catalog
from stack_generator.workspace import RunWorkspace

router = APIRouter()

MAX_CODE_BYTES = 2 * 1024 * 1024


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


@router.put("/api/runs/{run_id}/versions/{commit_hash}")
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
    return SaveVersionResponse(gitSha=git_sha)
