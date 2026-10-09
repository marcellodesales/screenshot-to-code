"""Visual QA of generated options: render checks, duplicates, responsiveness.

Every option of a UI version is rendered in the headless Chromium the
``screenshot_preview`` tool already uses (``preview_screenshot``) at a few
viewport widths. From those renders we derive:

- ``renderOk``   — no uncaught page errors and the 1280 screenshot isn't blank;
- ``duplicateOf`` — the lowest earlier option that looks the same;
- ``responsive``  — no horizontal scrolling at any width and the content uses
  the canvas (``contentWidthRatio``) at desktop widths.

Results live (gitignored) under ``<run>/qa/<ui-commit-hash>/``: one PNG per
option and width plus ``qa.json`` (the ``visualQa`` websocket payload).
"""

import asyncio
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, cast

from PIL import Image, ImageChops, ImageStat
from playwright.async_api import (
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from babel_cdn import normalize_babel_cdn
from preview_screenshot.registry import shared_chromium
from stack_generator.workspace import RunWorkspace

QA_WIDTHS: tuple[int, ...] = (375, 768, 1280, 1920)
QA_HEIGHT = 900
THUMBNAIL_WIDTH = 1280
# contentWidthRatio must reach this at every "desktop" width.
DESKTOP_WIDTHS: tuple[int, ...] = (1280, 1920)
MIN_CONTENT_WIDTH_RATIO = 0.85
DUPLICATE_SIMILARITY = 0.97
PARITY_WARNING = 0.80
# Blank = at least this share of pixels within +-tolerance of the commonest colour.
BLANK_PIXEL_SHARE = 0.98
BLANK_TOLERANCE = 8
SIMILARITY_THUMBNAIL_WIDTH = 256

PAGE_LOAD_TIMEOUT_MS = 15000
RENDER_SETTLE_MS = 250
RESIZE_SETTLE_MS = 150
QA_DIR_NAME = "qa"
QA_JSON = "qa.json"

# Measures one viewport: horizontal overflow, and the horizontal extent of
# what is actually painted (text, media/controls, elements with their own
# background/border/shadow). A solid-colour box spanning the whole viewport is
# the page canvas (like <body>), not content, so it doesn't count.
_MEASURE_JS = """
() => {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const overflow = document.documentElement.scrollWidth > vw + 1;
  let left = Infinity;
  let right = -Infinity;
  const add = (r) => {
    if (r.width <= 0 || r.height <= 0) return;
    const l = Math.max(0, r.left);
    const rr = Math.min(vw, r.right);
    if (rr <= l) return;
    left = Math.min(left, l);
    right = Math.max(right, rr);
  };
  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "LINK", "META", "HEAD"]);
  const MEDIA = new Set(["IMG", "SVG", "VIDEO", "CANVAS", "IFRAME", "INPUT", "TEXTAREA",
                         "SELECT", "BUTTON", "PICTURE", "OBJECT", "EMBED"]);
  const transparent = (c) => !c || c === "transparent" || /rgba\\(.*,\\s*0\\)$/.test(c);
  const hidden = (cs) => cs.visibility === "hidden" || cs.display === "none" ||
                         parseFloat(cs.opacity) === 0;
  const body = document.body;
  if (!body) return { overflow, ratio: 0 };
  for (const el of body.querySelectorAll("*")) {
    const tag = el.tagName.toUpperCase();
    if (SKIP.has(tag)) continue;
    const cs = getComputedStyle(el);
    if (hidden(cs)) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    if (MEDIA.has(tag)) { add(r); continue; }
    const hasImage = cs.backgroundImage && cs.backgroundImage !== "none";
    const hasColor = !transparent(cs.backgroundColor);
    const hasBorder = ["Top", "Right", "Bottom", "Left"].some(
      (s) => parseFloat(cs["border" + s + "Width"]) > 0 && !transparent(cs["border" + s + "Color"]));
    const hasShadow = cs.boxShadow && cs.boxShadow !== "none";
    if (!(hasImage || hasColor || hasBorder || hasShadow)) continue;
    const canvas = !hasImage && r.width >= vw - 1 && r.height >= vh - 1;
    if (!canvas) add(r);
  }
  const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!node.textContent || !node.textContent.trim()) continue;
    const parent = node.parentElement;
    if (!parent || SKIP.has(parent.tagName.toUpperCase())) continue;
    if (hidden(getComputedStyle(parent))) continue;
    range.selectNodeContents(node);
    for (const r of range.getClientRects()) add(r);
  }
  const ratio = right > left ? (right - left) / vw : 0;
  return { overflow, ratio };
}
"""


# Loads the page under test into a fresh context/page.
Loader = Callable[[BrowserContext, Page], Awaitable[None]]


@dataclass
class WidthResult:
    width: int
    content_width_ratio: float
    horizontal_overflow: bool
    screenshot: bytes


@dataclass
class CaptureResult:
    """One page rendered at several widths (1280 is a full-page screenshot)."""

    widths: list[WidthResult] = field(default_factory=lambda: [])
    errors: list[str] = field(default_factory=lambda: [])

    def screenshot(self, width: int) -> bytes | None:
        for entry in self.widths:
            if entry.width == width:
                return entry.screenshot
        return None

    @property
    def thumbnail(self) -> bytes | None:
        return self.screenshot(THUMBNAIL_WIDTH)

    @property
    def blank(self) -> bool:
        thumbnail = self.thumbnail
        return thumbnail is None or is_blank(thumbnail)

    @property
    def render_ok(self) -> bool:
        return not self.errors and not self.blank

    @property
    def error(self) -> str | None:
        if self.errors:
            return self.errors[0]
        if self.thumbnail is None:
            return "No screenshot was captured"
        if self.blank:
            return "Blank render"
        return None

    def responsive(self) -> dict[str, Any]:
        widths: list[dict[str, Any]] = [
            {
                "width": entry.width,
                "contentWidthRatio": round(entry.content_width_ratio, 4),
                "horizontalOverflow": entry.horizontal_overflow,
            }
            for entry in self.widths
        ]
        passed = bool(self.widths) and all(
            not entry.horizontal_overflow for entry in self.widths
        ) and all(
            entry.content_width_ratio >= MIN_CONTENT_WIDTH_RATIO
            for entry in self.widths
            if entry.width in DESKTOP_WIDTHS
        )
        return {"pass": passed, "widths": widths}


# -- image helpers ----------------------------------------------------------------


def _open(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png))


def _grey_thumbnail(png: bytes) -> Image.Image:
    image = _open(png).convert("L")
    width, height = image.size
    thumb_height = max(1, round(height * SIMILARITY_THUMBNAIL_WIDTH / max(1, width)))
    return image.resize(
        (SIMILARITY_THUMBNAIL_WIDTH, thumb_height), Image.Resampling.BILINEAR
    )


def _commonest_grey(image: Image.Image) -> int:
    histogram = image.histogram()
    return max(range(256), key=lambda value: histogram[value])


def _padded(image: Image.Image, height: int) -> Image.Image:
    if image.height == height:
        return image
    # Pad with the page's own background so a slightly taller page isn't
    # penalised as if the extra strip were different content.
    canvas = Image.new("L", (image.width, height), _commonest_grey(image))
    canvas.paste(image, (0, 0))
    return canvas


def similarity(a: bytes, b: bytes) -> float:
    """Perceptual similarity of two screenshots in [0, 1] (1 = identical).

    1 - normalised mean absolute difference of 256-px-wide greyscale
    thumbnails; the shorter one is padded with its background colour.
    """
    first, second = _grey_thumbnail(a), _grey_thumbnail(b)
    height = max(first.height, second.height)
    difference = ImageChops.difference(_padded(first, height), _padded(second, height))
    mean = ImageStat.Stat(difference).mean[0]
    return max(0.0, min(1.0, 1.0 - mean / 255.0))


def is_blank(png: bytes) -> bool:
    """True when >= 98% of pixels are within +-8 of the most common colour."""
    image = _open(png).convert("RGB")
    if image.width > 512:
        # Nearest-neighbour keeps exact colours; plenty of samples for a share.
        height = max(1, round(image.height * 512 / image.width))
        image = image.resize((512, height), Image.Resampling.NEAREST)
    total = image.width * image.height
    colors = image.getcolors(maxcolors=total) or []
    if not colors:
        return True
    _, dominant = max(colors, key=lambda item: item[0])
    difference = ImageChops.difference(image, Image.new("RGB", image.size, dominant))
    red, green, blue = difference.split()
    channel_max = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    within = sum(channel_max.histogram()[: BLANK_TOLERANCE + 1])
    return within >= BLANK_PIXEL_SHARE * total


# -- rendering --------------------------------------------------------------------


async def _measure_widths(page: Page, widths: tuple[int, ...]) -> list[WidthResult]:
    results: list[WidthResult] = []
    for width in widths:
        await page.set_viewport_size({"width": width, "height": QA_HEIGHT})
        await page.wait_for_timeout(RESIZE_SETTLE_MS)
        metrics: dict[str, Any] = await page.evaluate(_MEASURE_JS)
        screenshot = await page.screenshot(
            full_page=width == THUMBNAIL_WIDTH, type="png"
        )
        results.append(
            WidthResult(
                width=width,
                content_width_ratio=float(metrics.get("ratio") or 0.0),
                horizontal_overflow=bool(metrics.get("overflow")),
                screenshot=screenshot,
            )
        )
    return results


async def _settle(page: Page) -> None:
    try:
        await page.evaluate("document.fonts.ready")
    except Exception:
        pass
    await page.wait_for_timeout(RENDER_SETTLE_MS)


async def _render(
    widths: tuple[int, ...],
    load: Loader,
) -> CaptureResult:
    # A missing/broken renderer raises: that is "no QA", not a failed render.
    browser = await shared_chromium()
    context = await browser.new_context(
        viewport={"width": THUMBNAIL_WIDTH, "height": QA_HEIGHT},
        device_scale_factor=1,
    )
    result = CaptureResult()
    try:
        page = await context.new_page()
        page.on("pageerror", lambda error: result.errors.append(str(error)))
        await load(context, page)
        await _settle(page)
        result.widths = await _measure_widths(page, widths)
    except Exception as exc:
        result.errors.append(f"Render failed: {exc}")
    finally:
        await context.close()
    return result


class _HtmlLoader:
    def __init__(self, html: str) -> None:
        self._html = html

    async def __call__(self, context: BrowserContext, page: Page) -> None:
        try:
            await page.set_content(
                normalize_babel_cdn(self._html),
                wait_until="networkidle",
                timeout=PAGE_LOAD_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError:
            pass  # Render whatever loaded (e.g. pages that keep polling).


async def capture(html: str, widths: tuple[int, ...] = QA_WIDTHS) -> CaptureResult:
    """Render ``html`` at each width (height 900; full page at 1280)."""
    return await _render(widths, _HtmlLoader(html))


# -- version QA -------------------------------------------------------------------


def qa_dir(workspace: RunWorkspace, ui_commit_hash: str) -> Path:
    return workspace.path / QA_DIR_NAME / ui_commit_hash


def qa_url(run_id: str, ui_commit_hash: str, file_name: str) -> str:
    return f"/api/runs/{run_id}/qa/{ui_commit_hash}/{file_name}"


def read_qa(workspace: RunWorkspace, ui_commit_hash: str) -> dict[str, Any] | None:
    """The stored ``qa.json`` of a version, or ``None`` if absent/unreadable."""
    if not workspace.has_version(ui_commit_hash):
        return None
    try:
        data: Any = json.loads(
            (qa_dir(workspace, ui_commit_hash) / QA_JSON).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    return cast(dict[str, Any], data) if isinstance(data, dict) else None


def _write_pngs(
    directory: Path, prefix: str, number: int, result: CaptureResult
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for entry in result.widths:
        (directory / f"{prefix}op{number}-{entry.width}.png").write_bytes(
            entry.screenshot
        )


def _duplicate(
    index: int, results: list[CaptureResult]
) -> tuple[int | None, float | None]:
    """(lowest earlier option with similarity >= 0.97, best similarity so far)."""
    thumbnail = results[index].thumbnail
    if thumbnail is None or index == 0:
        return None, None
    best: float | None = None
    for earlier in range(index):
        other = results[earlier].thumbnail
        if other is None:
            continue
        score = similarity(other, thumbnail)
        if score >= DUPLICATE_SIMILARITY:
            return earlier, round(score, 4)
        best = score if best is None else max(best, score)
    return None, None if best is None else round(best, 4)


def _require_version(workspace: RunWorkspace, ui_commit_hash: str) -> None:
    if not workspace.has_version(ui_commit_hash):
        raise KeyError(ui_commit_hash)


async def run_version_qa(workspace: RunWorkspace, ui_commit_hash: str) -> dict[str, Any]:
    """QA every option of a version; write PNGs + ``qa.json``; return the payload."""
    _require_version(workspace, ui_commit_hash)
    codes = await asyncio.to_thread(workspace.option_codes, ui_commit_hash)
    results = list(await asyncio.gather(*(capture(code) for code in codes)))
    directory = qa_dir(workspace, ui_commit_hash)

    options: list[dict[str, Any]] = []
    for index, result in enumerate(results):
        number = index + 1
        await asyncio.to_thread(_write_pngs, directory, "", number, result)
        duplicate_of, score = _duplicate(index, results)
        options.append(
            {
                "index": index,
                "screenshot": (
                    qa_url(workspace.run_id, ui_commit_hash, f"op{number}-{THUMBNAIL_WIDTH}.png")
                    if result.thumbnail is not None
                    else None
                ),
                "renderOk": result.render_ok,
                "error": result.error,
                "duplicateOf": duplicate_of,
                "similarity": score,
                "responsive": result.responsive(),
            }
        )
    data: dict[str, Any] = {"commitHash": ui_commit_hash, "options": options}
    await asyncio.to_thread(_write_json, directory / QA_JSON, data)
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
