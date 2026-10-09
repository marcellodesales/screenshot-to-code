from pathlib import Path

import pytest

from stack_generator.catalog import StackTemplate, load_catalog, resolve_template


def _by_id(catalog: list[StackTemplate]) -> dict[str, StackTemplate]:
    return {template.id: template for template in catalog}


def test_load_catalog_reads_available_templates() -> None:
    catalog = _by_id(load_catalog())

    static = catalog["static-pnpm-html"]
    nextjs = catalog["nextjs-pnpm-react-tailwind"]

    assert static.status == "available"
    assert nextjs.status == "available"
    assert nextjs.has_scaffold is True
    assert nextjs.mock_path == "design/mock.html"
    assert "src/app/page.tsx" in nextjs.migration_targets
    assert static.has_scaffold is False
    assert static.mock_path == "public/index.html"
    assert static.path.is_dir()
    assert "bootstrap" in static.source_stacks


def test_load_catalog_keeps_entries_without_template_dir(tmp_path: Path) -> None:
    (tmp_path / "catalog.yaml").write_text(
        """
version: 1
stacks:
  - id: vite-pnpm-react-tailwind
    source_stacks: [react_tailwind]
    build_system: pnpm
    phase: 3
    status: planned
""",
        encoding="utf-8",
    )

    [template] = load_catalog(tmp_path)

    assert template.status == "planned"
    assert template.mock_path == ""
    assert template.has_scaffold is False
    assert template.migration_targets == []


def test_resolve_prefers_framework_template() -> None:
    catalog = load_catalog()

    assert (
        resolve_template("react_tailwind", "pnpm", catalog).id
        == "nextjs-pnpm-react-tailwind"
    )
    assert resolve_template("bootstrap", "pnpm", catalog).id == "static-pnpm-html"
    with pytest.raises(ValueError):
        resolve_template("react_tailwind", "bun", catalog)
