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
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, cast
from urllib.parse import urlsplit, urlunsplit

from PIL import Image, ImageChops, ImageFilter, ImageStat
from playwright.async_api import (
    BrowserContext,
    Page,
    Request,
    Route,
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
# Foreground masks (for IoU) are compared at half that width so anti-aliasing
# and faint shadow halos don't count as layout changes; the drift search runs
# at a quarter of it (thumbnail heights are padded to a multiple of this).
SIMILARITY_SCALE_STEP = 4
# A band of one page may match the other this far up/down (share of the
# taller page's height): tolerates text wrapping differently, not moved layout.
SIMILARITY_MAX_DRIFT = 0.08
# Weight floor (share of foreground) so bands without content still count.
SIMILARITY_MIN_BAND_WEIGHT = 0.02
# Page heights may differ down to this ratio before the score is penalised.
SIMILARITY_HEIGHT_RATIO = 0.75
# Local tolerance (~20 px at 1280) so text that rewraps or sits a few pixels
# off still overlaps: foreground masks (128 px wide) are matched against the
# other page's mask dilated by this many pixels, greys (256 px wide) are
# box-blurred by SIMILARITY_BLUR_RADIUS before differencing.
SIMILARITY_MASK_TOLERANCE = 2
SIMILARITY_BLUR_RADIUS = 2
# A pixel is foreground when a channel differs from the page background by more.
FOREGROUND_TOLERANCE = 24

PAGE_LOAD_TIMEOUT_MS = 15000
RENDER_SETTLE_MS = 250
RESIZE_SETTLE_MS = 150
QA_DIR_NAME = "qa"
QA_JSON = "qa.json"
DEFAULT_GATEWAY_INTERNAL_URL = "http://host.docker.internal:3311"

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


def _background(image: Image.Image) -> tuple[int, int, int]:
    """The page's dominant colour (exact colours via a nearest-neighbour sample)."""
    sample = image.resize(
        (max(1, image.width // 2), max(1, image.height // 2)),
        Image.Resampling.NEAREST,
    )
    colors = sample.getcolors(maxcolors=sample.width * sample.height) or []
    if not colors:
        return (255, 255, 255)
    _, color = max(colors, key=lambda item: item[0])
    return cast(tuple[int, int, int], color)


def _foreground_mask(image: Image.Image, background: tuple[int, int, int]) -> Image.Image:
    """255 where any channel is > FOREGROUND_TOLERANCE away from the background."""
    difference = ImageChops.difference(image, Image.new("RGB", image.size, background))
    red, green, blue = difference.split()
    channel_max = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    return channel_max.point(lambda value: 255 if value > FOREGROUND_TOLERANCE else 0)


def _mask_count(mask: Image.Image) -> float:
    return float(ImageStat.Stat(mask).sum[0]) / 255.0


def _grey_of(color: tuple[int, int, int]) -> int:
    """The "L" value Pillow converts ``color`` to (ITU-R 601-2 luma)."""
    red, green, blue = color
    return (red * 299 + green * 587 + blue * 114) // 1000


@dataclass
class _Page:
    """A screenshot prepared for :func:`similarity`.

    ``grey`` (box-blurred) and ``mask`` are SIMILARITY_THUMBNAIL_WIDTH wide,
    ``coarse_mask`` (and its dilation) half that and ``search`` a quarter; the
    thumbnail height is padded (with the page background) to a multiple of
    SIMILARITY_SCALE_STEP so a row in one scale maps exactly onto the others.
    """

    grey: Image.Image
    mask: Image.Image
    coarse_mask: Image.Image
    dilated_mask: Image.Image
    search: Image.Image
    background: int
    height: int
    content_height: int


def _page(png: bytes) -> _Page:
    image = _open(png).convert("RGB")
    width = SIMILARITY_THUMBNAIL_WIDTH
    content_height = max(1, round(image.height * width / max(1, image.width)))
    thumbnail = image.resize((width, content_height), Image.Resampling.BILINEAR)
    background = _background(thumbnail)
    step = SIMILARITY_SCALE_STEP
    height = -(-content_height // step) * step
    if height != content_height:
        # Pad with the page's own background (not counted as content).
        canvas = Image.new("RGB", (width, height), background)
        canvas.paste(thumbnail, (0, 0))
        thumbnail = canvas
    coarse = thumbnail.resize((width // 2, height // 2), Image.Resampling.BILINEAR)
    coarse_mask = _foreground_mask(coarse, background)
    grey = thumbnail.convert("L")
    return _Page(
        grey=grey.filter(ImageFilter.BoxBlur(SIMILARITY_BLUR_RADIUS)),
        mask=_foreground_mask(thumbnail, background),
        coarse_mask=coarse_mask,
        dilated_mask=coarse_mask.filter(
            ImageFilter.MaxFilter(2 * SIMILARITY_MASK_TOLERANCE + 1)
        ),
        search=grey.resize((width // step, height // step), Image.Resampling.BILINEAR),
        background=_grey_of(background),
        height=height,
        content_height=content_height,
    )


def _window(image: Image.Image, top: int, height: int, fill: int) -> Image.Image:
    """Rows ``[top, top + height)`` of ``image``; rows outside it are ``fill``."""
    if top >= 0 and top + height <= image.height:
        return image.crop((0, top, image.width, top + height))
    window = Image.new("L", (image.width, height), fill)
    start, end = max(0, top), min(image.height, top + height)
    if end > start:
        window.paste(image.crop((0, start, image.width, end)), (0, start - top))
    return window


def _mean_difference(first: Image.Image, second: Image.Image) -> float:
    return float(ImageStat.Stat(ImageChops.difference(first, second)).mean[0])


def _best_offset(first: _Page, second: _Page, top: int, height: int, reach: int) -> int:
    """Vertical offset (thumbnail px) at which ``second`` best matches a band of ``first``.

    Coarse search at a quarter of the thumbnail width over +-``reach``
    (smallest shift wins ties), then refined by +-half a coarse step.
    """
    step = SIMILARITY_SCALE_STEP
    band = first.search.crop(
        (0, top // step, first.search.width, (top + height) // step)
    )
    coarse_reach = reach // step
    shifts = sorted(range(-coarse_reach, coarse_reach + 1), key=abs)
    best = min(
        shifts,
        key=lambda shift: _mean_difference(
            band,
            _window(second.search, top // step + shift, band.height, second.background),
        ),
    )
    grey_band = first.grey.crop((0, top, first.grey.width, top + height))
    half = step // 2
    return min(
        (best * step, best * step - half, best * step + half),
        key=lambda offset: _mean_difference(
            grey_band, _window(second.grey, top + offset, height, second.background)
        ),
    )


def _band_score(
    first: _Page, second: _Page, top: int, height: int, offset: int
) -> tuple[float, float]:
    """(foreground-aware score, weight) of a band of ``first`` vs ``second`` shifted.

    The overlap term is a tolerant IoU: the share of both pages' foreground
    pixels that have foreground of the other page within
    SIMILARITY_MASK_TOLERANCE pixels.
    """
    box = (0, top // 2, first.coarse_mask.width, (top + height) // 2)
    first_mask, first_dilated = first.coarse_mask.crop(box), first.dilated_mask.crop(box)
    second_top = (top + offset) // 2
    second_mask = _window(second.coarse_mask, second_top, height // 2, 0)
    second_dilated = _window(second.dilated_mask, second_top, height // 2, 0)
    mask_total = _mask_count(first_mask) + _mask_count(second_mask)
    overlap = (
        1.0
        if mask_total == 0
        else (
            _mask_count(ImageChops.darker(first_mask, second_dilated))
            + _mask_count(ImageChops.darker(second_mask, first_dilated))
        )
        / mask_total
    )

    first_grey = first.grey.crop((0, top, first.grey.width, top + height))
    second_grey = _window(second.grey, top + offset, height, second.background)
    difference = ImageChops.difference(first_grey, second_grey)
    page_score = 1.0 - float(ImageStat.Stat(difference).mean[0]) / 255.0
    union = ImageChops.lighter(
        first.mask.crop((0, top, first.mask.width, top + height)),
        _window(second.mask, top + offset, height, 0),
    )
    union_count = _mask_count(union)
    foreground_score = (
        1.0
        if union_count == 0
        else 1.0
        - float(ImageStat.Stat(difference, union).sum[0]) / union_count / 255.0
    )
    content = union_count / float(first.grey.width * height)
    weight = max(content, SIMILARITY_MIN_BAND_WEIGHT) * height
    return min(overlap, foreground_score, page_score), weight


def _directional_similarity(first: _Page, second: _Page) -> float:
    """Content-weighted mean band score of ``first``'s bands found in ``second``."""
    step = SIMILARITY_SCALE_STEP
    band = max(step, round(first.grey.width * QA_HEIGHT / THUMBNAIL_WIDTH / step) * step)
    reach = round(SIMILARITY_MAX_DRIFT * max(first.height, second.height) / step) * step
    total = 0.0
    total_weight = 0.0
    for top in range(0, first.height, band):
        height = min(band, first.height - top)
        offset = _best_offset(first, second, top, height, reach)
        score, weight = _band_score(first, second, top, height, offset)
        total += score * weight
        total_weight += weight
    return total / total_weight if total_weight else 1.0


def similarity(a: bytes, b: bytes) -> float:
    """Foreground-aware, drift-tolerant similarity of two screenshots in [0, 1].

    Each page's dominant colour is its background; pixels further than
    FOREGROUND_TOLERANCE from it are foreground. A plain whole-page
    difference lets a mostly-white background dominate (a moved, resized
    card scored ~0.90), so every comparison is the minimum of:

    - a tolerant IoU of the two foreground masks (128 px wide; foreground
      within SIMILARITY_MASK_TOLERANCE px of the other's counts) — where
      things are;
    - 1 - mean absolute (box-blurred) grey difference over the union of
      foreground pixels (256 px wide) — what they look like;
    - 1 - mean absolute (box-blurred) grey difference over everything —
      catches a different background with matching content.

    Real pages drift: one heading wrapping differently shifts everything
    below it, and a position-by-position comparison of a long page then
    collapses (a near-identical built app scored 0.41 against its mock). So
    the first page is cut into viewport-tall bands (1280x900 scaled); each
    band is compared with the best-matching window of the other page within
    +-SIMILARITY_MAX_DRIFT of the taller page's height (coarse search on a
    64 px wide greyscale, refined at 256 px), and band scores are averaged
    weighted by their foreground content (blank bands count a little). This
    is done in both directions and the lower score kept, so extra content on
    either side counts. A layout change larger than the drift allowance — a
    missing section, a card moved or resized — still scores low. Finally,
    pages whose heights differ by more than 1 - SIMILARITY_HEIGHT_RATIO are
    scaled down by (height ratio / SIMILARITY_HEIGHT_RATIO).

    Two blank pages with the same background score 1.
    """
    first, second = _page(a), _page(b)
    score = min(
        _directional_similarity(first, second),
        _directional_similarity(second, first),
    )
    ratio = min(first.content_height, second.content_height) / max(
        first.content_height, second.content_height
    )
    if ratio < SIMILARITY_HEIGHT_RATIO:
        score *= ratio / SIMILARITY_HEIGHT_RATIO
    return max(0.0, min(1.0, score))


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


class _GatewayLoader:
    """Loads ``http://<host>/`` through the gateway with ``Host: <host>``.

    Chromium refuses to override the Host header, so requests for the app host
    are fetched by Playwright from the gateway with the header set and
    fulfilled back into the page; other origins (CDNs) go out untouched.
    """

    def __init__(self, gateway_url: str, host: str) -> None:
        self._gateway = gateway_url.rstrip("/")
        self._host = host

    async def __call__(self, context: BrowserContext, page: Page) -> None:
        async def proxy(route: Route, request: Request) -> None:
            parts = urlsplit(request.url)
            if parts.hostname != self._host:
                await route.continue_()
                return
            target = self._gateway + urlunsplit(("", "", parts.path or "/", parts.query, ""))
            response = await route.fetch(
                url=target, headers={**request.headers, "host": self._host}
            )
            await route.fulfill(response=response)

        await context.route("**/*", proxy)
        try:
            response = await page.goto(
                f"http://{self._host}/",
                wait_until="networkidle",
                timeout=PAGE_LOAD_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError:
            return
        if response is not None and response.status >= 400:
            raise RuntimeError(f"The app answered HTTP {response.status}")


async def capture(html: str, widths: tuple[int, ...] = QA_WIDTHS) -> CaptureResult:
    """Render ``html`` at each width (height 900; full page at 1280)."""
    return await _render(widths, _HtmlLoader(html))


async def capture_url(
    gateway_url: str, host: str, widths: tuple[int, ...] = QA_WIDTHS
) -> CaptureResult:
    """Render a running app reached through the gateway as ``Host: <host>``."""
    return await _render(widths, _GatewayLoader(gateway_url, host))


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


def gateway_internal_url() -> str:
    # Read at call time so tests (and late env changes) take effect.
    return os.environ.get("GATEWAY_INTERNAL_URL", DEFAULT_GATEWAY_INTERNAL_URL)


async def _mock_thumbnail(
    workspace: RunWorkspace, ui_commit_hash: str, option_index: int
) -> bytes | None:
    """The mock's 1280 screenshot from version QA, rendered now if missing."""
    number = option_index + 1
    path = qa_dir(workspace, ui_commit_hash) / f"op{number}-{THUMBNAIL_WIDTH}.png"
    if path.is_file():
        return await asyncio.to_thread(path.read_bytes)
    codes = await asyncio.to_thread(workspace.option_codes, ui_commit_hash)
    if option_index >= len(codes):
        return None
    result = await capture(codes[option_index], widths=(THUMBNAIL_WIDTH,))
    if result.thumbnail is not None:
        await asyncio.to_thread(
            _write_pngs, qa_dir(workspace, ui_commit_hash), "", number, result
        )
    return result.thumbnail


async def app_qa(
    workspace: RunWorkspace, ui_commit_hash: str, option_index: int, app_host: str
) -> dict[str, Any]:
    """Screenshot a running app through the gateway and compare it with its mock.

    Returns the ``OptionStatus`` QA fields: ``screenshot`` (URL of
    ``app-op<N>-1280.png``), ``parity`` (similarity to the mock's 1280
    screenshot), ``responsive`` and ``render_ok``.
    """
    _require_version(workspace, ui_commit_hash)
    number = option_index + 1
    result = await capture_url(gateway_internal_url(), app_host)
    app_thumbnail = result.thumbnail
    screenshot: str | None = None
    if app_thumbnail is not None:
        file_name = f"app-op{number}-{THUMBNAIL_WIDTH}.png"
        directory = qa_dir(workspace, ui_commit_hash)
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread((directory / file_name).write_bytes, app_thumbnail)
        screenshot = qa_url(workspace.run_id, ui_commit_hash, file_name)
    mock_thumbnail = await _mock_thumbnail(workspace, ui_commit_hash, option_index)
    parity = (
        round(similarity(mock_thumbnail, app_thumbnail), 4)
        if mock_thumbnail is not None and app_thumbnail is not None
        else None
    )
    return {
        "screenshot": screenshot,
        "parity": parity,
        "responsive": result.responsive(),
        "render_ok": result.render_ok,
    }
