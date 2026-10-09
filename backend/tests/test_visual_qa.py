"""Visual QA against real headless Chromium (the preview_screenshot browser)."""

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

import pytest
from PIL import Image

from preview_screenshot import registry
from preview_screenshot.playwright_backend import PlaywrightBackend
from stack_generator import visual_qa
from stack_generator.visual_qa import (
    app_qa,
    capture,
    capture_url,
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


def _pricing_card(
    *,
    align: str = "center",
    width: str = "24rem",
    font: str = "sans-serif",
    button_shadow: str = "#d1fae5",
) -> str:
    """A React-ish pricing card on an off-white page (like the real mocks)."""
    return f"""<!DOCTYPE html><html><head><style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-height: 100vh; display: flex; justify-content: center;
       align-items: {align}; background: #fdfcfb; font-family: {font}; }}
.card {{ max-width: {width}; width: 100%; background: #fff; border-radius: 24px;
        overflow: hidden; border: 1px solid #f5f5f4;
        box-shadow: 0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1); }}
.hero {{ height: 192px; background: #3d2b1f; color: #fff; display: flex;
        align-items: center; justify-content: center; font-size: 30px; font-weight: 700; }}
.body {{ padding: 32px; color: #1c1917; }}
.price {{ font-size: 36px; font-weight: 700; margin-bottom: 32px; }}
li {{ margin-bottom: 16px; color: #57534e; }}
button {{ width: 100%; padding: 16px; border: 0; border-radius: 16px; color: #fff;
         font-weight: 700; background: #059669; margin-top: 24px;
         box-shadow: 0 10px 15px -3px {button_shadow}, 0 4px 6px -4px {button_shadow}; }}
</style></head><body><div id="root"><div class="card">
<div class="hero">The Artisan Blend</div><div class="body">
<div class="price">$12 <small>/ month</small></div>
<ul><li>Premium Single-Origin Beans</li><li>Fresh Roast-to-Door Delivery</li>
<li>Exclusive Brewing Guides</li></ul><button>Subscribe Now</button>
<p style="font-size:12px;color:#a8a29e;text-align:center">Cancel or pause anytime.</p>
</div></div></div></body></html>"""


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


def _card_png(top: int, left: int, width: int, height: int) -> bytes:
    image = Image.new("RGB", (1280, 900), (255, 255, 255))
    for x in range(left, left + width):
        for y in range(top, top + height):
            image.putpixel((x, y), (17, 24, 39))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_similarity_is_foreground_aware_on_white_pages() -> None:
    centred = _card_png(top=200, left=480, width=320, height=500)
    assert similarity(centred, centred) == pytest.approx(1.0)
    moved = _card_png(top=0, left=520, width=240, height=500)
    assert similarity(centred, moved) < 0.80
    blank = _png((255, 255, 255))
    assert similarity(blank, centred) < 0.2


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


async def test_similarity_shadow_shade_is_still_a_duplicate(chromium: None) -> None:
    # shadow-emerald-100 vs shadow-emerald-200 on the button: same design.
    light = await capture(_pricing_card(button_shadow="#d1fae5"), widths=(1280,))
    darker = await capture(_pricing_card(button_shadow="#a7f3d0"), widths=(1280,))
    assert light.thumbnail is not None and darker.thumbnail is not None
    assert similarity(light.thumbnail, darker.thumbnail) >= 0.97


async def test_similarity_moved_narrower_card_on_white_page_is_low(
    chromium: None,
) -> None:
    # Mostly-white pages: the background must not dominate the score.
    mock = await capture(_pricing_card(), widths=(1280,))
    app = await capture(
        _pricing_card(align="flex-start", width="20rem", font="serif"),
        widths=(1280,),
    )
    assert mock.thumbnail is not None and app.thumbnail is not None
    assert similarity(mock.thumbnail, app.thumbnail) < 0.80


async def test_similarity_blank_vs_card_is_low(chromium: None) -> None:
    blank = await capture(BLANK_PAGE, widths=(1280,))
    card = await capture(_pricing_card(), widths=(1280,))
    assert blank.thumbnail is not None and card.thumbnail is not None
    assert similarity(blank.thumbnail, card.thumbnail) < 0.2
    assert similarity(card.thumbnail, blank.thumbnail) < 0.2


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


# -- built apps through the gateway ----------------------------------------------


class _HostRecordingHandler(BaseHTTPRequestHandler):
    hosts: list[str] = []
    body = GRID_PAGE.encode("utf-8")

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        type(self).hosts.append(self.headers.get("Host", ""))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def gateway() -> Iterator[str]:
    _HostRecordingHandler.hosts = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HostRecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


async def test_capture_url_sends_app_host_through_gateway(
    chromium: None, gateway: str
) -> None:
    result = await capture_url(gateway, "run-x-op1.localhost")
    assert result.render_ok, result.error
    assert _HostRecordingHandler.hosts
    assert set(_HostRecordingHandler.hosts) == {"run-x-op1.localhost"}


async def test_app_qa_compares_app_with_mock(
    chromium: None, gateway: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GATEWAY_INTERNAL_URL", gateway)
    workspace = _workspace(tmp_path, [GRID_PAGE, CARD_PAGE])
    await run_version_qa(workspace, "h1")

    same = await app_qa(workspace, "h1", 0, "run-x-op1.localhost")
    assert same["screenshot"] == f"/api/runs/{workspace.run_id}/qa/h1/app-op1-1280.png"
    assert (workspace.path / "qa/h1/app-op1-1280.png").is_file()
    assert same["render_ok"] is True
    assert same["parity"] >= 0.99
    assert same["responsive"]["pass"] is True

    # The app serves the grid; option 2's mock is the card. No prior version QA
    # for it is needed: the mock is rendered on demand.
    (workspace.path / "qa/h1/op2-1280.png").unlink()
    different = await app_qa(workspace, "h1", 1, "run-x-op2.localhost")
    assert different["parity"] < 0.8


def test_default_gateway_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GATEWAY_INTERNAL_URL", raising=False)
    assert visual_qa.gateway_internal_url() == "http://host.docker.internal:3311"
