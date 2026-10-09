"""Visual QA against real headless Chromium (the preview_screenshot browser)."""

import io
import json
from pathlib import Path
from typing import Any, AsyncIterator

import pytest
from PIL import Image

from preview_screenshot import registry
from preview_screenshot.playwright_backend import PlaywrightBackend
from stack_generator import visual_qa
from stack_generator.visual_qa import (
    capture,
    is_blank,
    run_version_qa,
    similarity,
)
from stack_generator.workspace import RunWorkspace, new_run_id

GRID_PAGE = """<!DOCTYPE html><html><head><style>
body { margin: 0; font-family: sans-serif; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
        gap: 16px; padding: 16px; }
.cell { height: 220px; background: #2563eb; color: white; padding: 8px; }
</style></head><body><div class="grid">
""" + "".join(f'<div class="cell">Cell {i}</div>' for i in range(24)) + """
</div></body></html>"""

CARD_PAGE = """<!DOCTYPE html><html><head><style>
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: flex; align-items: center;
       justify-content: center; background: #f5f5f4; font-family: sans-serif; }
.card { max-width: 24rem; width: 100%; background: #111827; color: white;
        border-radius: 24px; padding: 32px; height: 520px; }
</style></head><body><div id="root"><div class="card">
<h1>The Artisan Blend</h1><p>$12 / month</p><button>Subscribe</button>
</div></div></body></html>"""

DARK_PAGE = """<!DOCTYPE html><html><body style="margin:0;background:#000">
<div style="height:900px;background:#000"></div>
<div style="position:fixed;top:40px;left:40px;width:200px;height:200px;background:#f00"></div>
</body></html>"""

BLANK_PAGE = "<!DOCTYPE html><html><body style='margin:0;background:#fff'></body></html>"

OVERFLOW_PAGE = """<!DOCTYPE html><html><body style="margin:0">
<div style="width:2000px;height:400px;background:#16a34a"></div></body></html>"""

ERROR_PAGE = """<!DOCTYPE html><html><body style="margin:0">""" + GRID_PAGE.split(
    "<body>"
)[1].split("</body>")[0] + """<script>throw new Error("boom");</script></body></html>"""


@pytest.fixture
async def chromium(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """A fresh shared browser per test (each test has its own event loop)."""
    backend = PlaywrightBackend()
    monkeypatch.setattr(registry, "_backend", backend)
    yield
    await backend.close()


def _png(color: tuple[int, int, int], size: tuple[int, int] = (1280, 900)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


# -- pure image helpers ---------------------------------------------------------


def test_similarity_identical_and_different_images() -> None:
    white = _png((255, 255, 255))
    assert similarity(white, white) == pytest.approx(1.0)
    assert similarity(white, _png((0, 0, 0))) < 0.05


def test_is_blank_threshold() -> None:
    assert is_blank(_png((250, 250, 250)))
    image = Image.new("RGB", (100, 100), (255, 255, 255))
    for x in range(100):
        for y in range(5):  # 5% of the pixels differ -> not blank
            image.putpixel((x, y), (0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    assert not is_blank(buffer.getvalue())
    # Within +-8 of the most common colour still counts as blank.
    noisy = Image.new("RGB", (100, 100), (200, 200, 200))
    for x in range(0, 100, 2):
        noisy.putpixel((x, 0), (206, 194, 200))
    buffer = io.BytesIO()
    noisy.save(buffer, format="PNG")
    assert is_blank(buffer.getvalue())


# -- real Chromium ----------------------------------------------------------------


async def test_capture_identical_pages_are_similar(chromium: None) -> None:
    first = await capture(GRID_PAGE)
    second = await capture(GRID_PAGE)
    assert first.thumbnail is not None and second.thumbnail is not None
    assert similarity(first.thumbnail, second.thumbnail) >= 0.99
    assert [w.width for w in first.widths] == [375, 768, 1280, 1920]
    assert first.render_ok and first.error is None
    # Full-page 1280 thumbnail, at device scale 1.
    assert Image.open(io.BytesIO(first.thumbnail)).width == 1280


async def test_capture_very_different_pages(chromium: None) -> None:
    grid = await capture(GRID_PAGE)
    dark = await capture(DARK_PAGE)
    assert grid.thumbnail is not None and dark.thumbnail is not None
    assert similarity(grid.thumbnail, dark.thumbnail) < 0.8


async def test_blank_page_is_not_render_ok(chromium: None) -> None:
    result = await capture(BLANK_PAGE)
    assert not result.render_ok
    assert result.error is not None


async def test_uncaught_error_is_not_render_ok(chromium: None) -> None:
    result = await capture(ERROR_PAGE)
    assert not result.render_ok
    assert result.error is not None and "boom" in result.error


async def test_centred_card_is_not_responsive(chromium: None) -> None:
    result = await capture(CARD_PAGE)
    responsive = result.responsive()
    assert responsive["pass"] is False
    by_width = {w["width"]: w for w in responsive["widths"]}
    assert by_width[1920]["contentWidthRatio"] < 0.5
    assert not any(w["horizontalOverflow"] for w in responsive["widths"])


async def test_full_width_grid_is_responsive(chromium: None) -> None:
    responsive = (await capture(GRID_PAGE)).responsive()
    assert responsive["pass"] is True
    for entry in responsive["widths"]:
        assert set(entry) == {"width", "contentWidthRatio", "horizontalOverflow"}
        assert entry["horizontalOverflow"] is False
        assert entry["contentWidthRatio"] >= 0.85


async def test_wide_div_overflows_at_375(chromium: None) -> None:
    responsive = (await capture(OVERFLOW_PAGE)).responsive()
    by_width = {w["width"]: w for w in responsive["widths"]}
    assert by_width[375]["horizontalOverflow"] is True
    assert responsive["pass"] is False


# -- version QA -----------------------------------------------------------------


def _workspace(runs_dir: Path, codes: list[str]) -> RunWorkspace:
    workspace = RunWorkspace.create(
        new_run_id(),
        source_stack="html_css",
        input_mode="text",
        prompt_text="Grid",
        runs_dir=runs_dir,
    )
    workspace.commit_version(
        ui_commit_hash="h1",
        parent_ui_commit_hash=None,
        option_codes=codes,
        message=":art: Version 1 — mock (html_css)",
    )
    return workspace


async def test_run_version_qa_writes_pngs_and_json(
    chromium: None, tmp_path: Path
) -> None:
    workspace = _workspace(tmp_path, [GRID_PAGE, GRID_PAGE, CARD_PAGE, BLANK_PAGE])

    data = await run_version_qa(workspace, "h1")

    assert data["commitHash"] == "h1"
    first, duplicate, card, blank = data["options"]
    run_id = workspace.run_id
    assert first == {
        "index": 0,
        "screenshot": f"/api/runs/{run_id}/qa/h1/op1-1280.png",
        "renderOk": True,
        "error": None,
        "duplicateOf": None,
        "similarity": None,
        "responsive": first["responsive"],
    }
    assert first["responsive"]["pass"] is True
    assert duplicate["duplicateOf"] == 0
    assert duplicate["similarity"] >= 0.97
    assert card["duplicateOf"] is None
    assert isinstance(card["similarity"], float) and card["similarity"] < 0.97
    assert card["responsive"]["pass"] is False
    assert blank["renderOk"] is False

    qa_dir = workspace.path / "qa" / "h1"
    for number in range(1, 5):
        for width in (375, 768, 1280, 1920):
            assert (qa_dir / f"op{number}-{width}.png").is_file()
    assert json.loads((qa_dir / "qa.json").read_text(encoding="utf-8")) == data


async def test_run_version_qa_rejects_unknown_version(
    chromium: None, tmp_path: Path
) -> None:
    workspace = _workspace(tmp_path, [GRID_PAGE])
    with pytest.raises(KeyError):
        await run_version_qa(workspace, "nope")
    with pytest.raises(KeyError):
        await run_version_qa(workspace, "../etc")


async def test_run_version_qa_raises_when_renderer_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unavailable() -> Any:
        raise RuntimeError("Executable doesn't exist")

    monkeypatch.setattr(visual_qa, "shared_chromium", unavailable)
    workspace = _workspace(tmp_path, [GRID_PAGE])
    # Every option "failing" would be a false alarm: report nothing instead.
    with pytest.raises(RuntimeError):
        await run_version_qa(workspace, "h1")
    assert not (workspace.path / "qa" / "h1" / "qa.json").exists()
