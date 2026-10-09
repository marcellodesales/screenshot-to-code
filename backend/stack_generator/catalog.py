"""Target stack catalog (``internal/stack/catalog.yaml`` + per-template metadata)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

import config


@dataclass(frozen=True)
class StackTemplate:
    id: str
    source_stacks: list[str]
    build_system: str
    phase: int
    status: str
    path: Path
    mock_path: str
    has_scaffold: bool
    migration_targets: list[str]


def _read_yaml(path: Path) -> dict[str, Any]:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return cast(dict[str, Any], data) if isinstance(data, dict) else {}


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in cast(list[Any], value)]


def load_catalog(templates_dir: Path | None = None) -> list[StackTemplate]:
    """Catalog entries merged with each ``<id>/template.yaml`` (catalog wins).

    Entries without a template dir (planned stacks) keep their catalog status
    and get an empty ``mock_path``.
    """
    root = templates_dir if templates_dir is not None else Path(
        config.STACK_TEMPLATES_DIR
    )
    catalog = _read_yaml(root / "catalog.yaml")
    stacks: list[StackTemplate] = []
    entries: list[Any] = catalog.get("stacks") or []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        entry = cast(dict[str, Any], raw_entry)
        if not entry.get("id"):
            continue
        stack_id = str(entry["id"])
        template_dir = root / stack_id
        meta_path = template_dir / "template.yaml"
        meta = _read_yaml(meta_path) if meta_path.is_file() else {}
        merged: dict[str, Any] = {**meta, **entry}
        stacks.append(
            StackTemplate(
                id=stack_id,
                source_stacks=_str_list(merged.get("source_stacks")),
                build_system=str(merged.get("build_system", "")),
                phase=int(merged.get("phase", 0)),
                status=str(merged.get("status", "planned")),
                path=template_dir,
                mock_path=str(meta.get("mock_path", "")),
                has_scaffold=(template_dir / "scaffold.sh").is_file(),
                migration_targets=_str_list(meta.get("migration_targets")),
            )
        )
    return stacks


def resolve_template(
    source_stack: str, build_system: str, catalog: list[StackTemplate]
) -> StackTemplate:
    """Pick the target template for a mock: framework first, else static."""
    candidates = [
        template
        for template in catalog
        if template.status == "available"
        and template.build_system == build_system
        and source_stack in template.source_stacks
    ]
    for template in candidates:
        if not template.id.startswith("static-"):
            return template
    static_id = f"static-{build_system}-html"
    for template in candidates:
        if template.id == static_id:
            return template
    raise ValueError(
        f"No available stack template for source stack {source_stack!r} "
        f"with build system {build_system!r}"
    )
