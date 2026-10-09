"""Mock -> stack migration: one LLM call per option, returned as a validated file map.

The LLM output is untrusted: every path is checked against the template's
``migration_targets`` before anything is written (spec §7 step 4).
"""

import json
import re
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Awaitable, Callable, cast

from openai.types.chat import ChatCompletionMessageParam

from agent.providers.base import StreamEvent
from agent.providers.factory import create_provider_session
from config import OPENAI_BASE_URL
from llm import Llm
from stack_generator.catalog import StackTemplate
from stack_generator.prompts import (
    MIGRATION_SYSTEM_PROMPT,
    migration_user_prompt,
    repair_user_prompt,
)

MigrationLlm = Callable[[str, str], Awaitable[str]]

ALLOWED_EXTENSIONS = frozenset({".tsx", ".ts", ".css", ".svg"})
MAX_FILE_BYTES = 200 * 1024
MAX_FILES = 40

# Preferred provider order for the migration call: Anthropic, OpenAI, Gemini.
ANTHROPIC_MIGRATION_MODEL = Llm.CLAUDE_OPUS_5_5_MEDIUM
OPENAI_MIGRATION_MODEL = Llm.GPT_5_6_SOL_HIGH
GEMINI_MIGRATION_MODEL = Llm.GEMINI_3_8_FLASH_HIGH

SYSTEM_SANS = (
    'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, '
    '"Helvetica Neue", Arial, "Noto Sans", sans-serif'
)
SYSTEM_MONO = (
    'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, '
    '"Liberation Mono", "Courier New", monospace'
)

_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n?```", re.DOTALL)


class MigrationError(Exception):
    pass


def parse_file_map(raw: str) -> dict[str, str]:
    """``{"files": {path: content}}``, optionally inside a ```json fence."""
    text = raw.strip()
    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise MigrationError("Migration output is not JSON")
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise MigrationError(f"Migration output is not valid JSON: {exc}") from exc

    files: object = (
        cast(dict[str, object], data).get("files") if isinstance(data, dict) else None
    )
    if not isinstance(files, dict):
        raise MigrationError('Migration output has no "files" object')
    result: dict[str, str] = {}
    entries = cast(dict[object, object], files)
    for path, content in entries.items():
        if not isinstance(path, str) or not isinstance(content, str):
            raise MigrationError("Migration file map must map paths to strings")
        result[path] = content
    return result


def _matches(path: str, pattern: str) -> bool:
    """Segment-wise glob match: ``*`` never crosses ``/``."""
    path_parts = path.split("/")
    pattern_parts = pattern.split("/")
    return len(path_parts) == len(pattern_parts) and all(
        fnmatchcase(part, pat) for part, pat in zip(path_parts, pattern_parts)
    )


def _check_path(path: str, allowed_globs: list[str]) -> None:
    if not path or "\\" in path or "\x00" in path:
        raise MigrationError(f"Invalid path: {path!r}")
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise MigrationError(f"Absolute path not allowed: {path}")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise MigrationError(f"Path traversal not allowed: {path}")
    if "node_modules" in parts:
        raise MigrationError(f"node_modules not allowed: {path}")
    if PurePosixPath(path).suffix not in ALLOWED_EXTENSIONS:
        raise MigrationError(f"File type not allowed: {path}")
    if not any(_matches(path, glob) for glob in allowed_globs):
        raise MigrationError(f"Path is not a migration target: {path}")


def validate_file_map(files: dict[str, str], allowed_globs: list[str]) -> dict[str, str]:
    if not files:
        raise MigrationError("Migration produced no files")
    if len(files) > MAX_FILES:
        raise MigrationError(f"Too many files ({len(files)} > {MAX_FILES})")
    for path, content in files.items():
        _check_path(path, allowed_globs)
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise MigrationError(f"File too large: {path}")
    return dict(files)


async def migrate_mock(
    *, mock_html: str, template: StackTemplate, app_title: str, llm: MigrationLlm
) -> dict[str, str]:
    """Files to write into the app dir (relative paths), incl. the mock itself."""
    if not template.has_scaffold:
        return {template.mock_path: mock_html}

    raw = await llm(
        MIGRATION_SYSTEM_PROMPT,
        migration_user_prompt(
            mock_html=mock_html,
            app_title=app_title,
            migration_targets=template.migration_targets,
        ),
    )
    files = validate_file_map(parse_file_map(raw), template.migration_targets)
    files[template.mock_path] = mock_html
    return files


async def repair_migration(
    *, files: dict[str, str], build_log: str, template: StackTemplate, llm: MigrationLlm
) -> dict[str, str]:
    """Corrected files after a failed production build (same contract as migrate_mock).

    Returns only the files the model sent back, validated against the
    template's ``migration_targets``; the caller writes them over the app.
    """
    if not template.has_scaffold:
        raise MigrationError("Static templates are not repaired")
    raw = await llm(
        MIGRATION_SYSTEM_PROMPT,
        repair_user_prompt(
            files=files,
            build_log=build_log,
            migration_targets=template.migration_targets,
        ),
    )
    return validate_file_map(parse_file_map(raw), template.migration_targets)


def _layout_tsx(title: str) -> str:
    return f"""import type {{ Metadata }} from "next";
import "./globals.css";

export const metadata: Metadata = {{
  title: {json.dumps(title)},
}};

export default function RootLayout({{
  children,
}}: Readonly<{{
  children: React.ReactNode;
}}>) {{
  return (
    <html lang="en">
      <body className="antialiased">{{children}}</body>
    </html>
  );
}}
"""


def _default_globals_css() -> str:
    return f"""@import "tailwindcss";

@theme inline {{
  --font-sans: {SYSTEM_SANS};
  --font-mono: {SYSTEM_MONO};
}}
"""


def apply_system_fonts(app_dir: Path, title: str) -> None:
    """Rewrite layout.tsx without next/font and point globals.css at system fonts.

    Builds then need no network access to Google Fonts.
    """
    app_src = app_dir / "src" / "app"
    app_src.mkdir(parents=True, exist_ok=True)
    (app_src / "layout.tsx").write_text(_layout_tsx(title), encoding="utf-8")

    globals_css = app_src / "globals.css"
    if not globals_css.exists():
        globals_css.write_text(_default_globals_css(), encoding="utf-8")
        return
    css = globals_css.read_text(encoding="utf-8")
    css = re.sub(r"var\(\s*--font-geist-sans\s*\)", SYSTEM_SANS, css)
    css = re.sub(r"var\(\s*--font-geist-mono\s*\)", SYSTEM_MONO, css)
    if "--font-sans:" not in css:
        css = css.rstrip() + "\n\n" + _default_globals_css().split("\n", 2)[2]
    globals_css.write_text(css, encoding="utf-8")


async def _ignore_event(_event: StreamEvent) -> None:
    return None


def default_migration_llm(
    *,
    openai_api_key: str | None,
    anthropic_api_key: str | None,
    gemini_api_key: str | None,
) -> MigrationLlm:
    """One completion through the provider layer (Anthropic > OpenAI > Gemini)."""
    if anthropic_api_key:
        model = ANTHROPIC_MIGRATION_MODEL
    elif openai_api_key:
        model = OPENAI_MIGRATION_MODEL
    elif gemini_api_key:
        model = GEMINI_MIGRATION_MODEL
    else:
        raise MigrationError("No API key for migration")

    async def call(system_prompt: str, user_prompt: str) -> str:
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        session = create_provider_session(
            model=model,
            prompt_messages=messages,
            should_generate_images=False,
            openai_api_key=openai_api_key,
            openai_base_url=OPENAI_BASE_URL,
            anthropic_api_key=anthropic_api_key,
            gemini_api_key=gemini_api_key,
            replicate_api_key=None,
            should_extract_assets=False,
            # The answer must be the JSON file map, never a tool call.
            tools_enabled=False,
        )
        try:
            turn = await session.stream_turn(_ignore_event)
        finally:
            await session.close()
        if not turn.assistant_text.strip():
            raise MigrationError("Migration model returned no text")
        return turn.assistant_text

    return call
