import json
from pathlib import Path

import pytest

from stack_generator.catalog import StackTemplate
from stack_generator.migrate import (
    MigrationError,
    apply_system_fonts,
    default_migration_llm,
    migrate_mock,
    parse_file_map,
    validate_file_map,
)

NEXTJS_TARGETS = [
    "src/app/page.tsx",
    "src/app/layout.tsx",
    "src/components/*.tsx",
    "public/*",
]

MOCK_HTML = """<!DOCTYPE html>
<html><head><title>Coffee</title></head>
<body><div id="root"></div>
<script type="text/babel">
function App() { return <h1 className="text-3xl">Coffee</h1>; }
ReactDOM.createRoot(document.getElementById("root")).render(<App />);
</script></body></html>
"""


def _template(*, has_scaffold: bool, tmp_path: Path) -> StackTemplate:
    if has_scaffold:
        return StackTemplate(
            id="nextjs-pnpm-react-tailwind",
            source_stacks=["react_tailwind"],
            build_system="pnpm",
            phase=2,
            status="available",
            path=tmp_path,
            mock_path="design/mock.html",
            has_scaffold=True,
            migration_targets=list(NEXTJS_TARGETS),
        )
    return StackTemplate(
        id="static-pnpm-html",
        source_stacks=["html_css", "react_tailwind"],
        build_system="pnpm",
        phase=1,
        status="available",
        path=tmp_path,
        mock_path="public/index.html",
        has_scaffold=False,
        migration_targets=[],
    )


def test_parse_file_map_accepts_fenced_json() -> None:
    payload = {"files": {"src/app/page.tsx": "export default function P() {}"}}
    raw = f"Here you go:\n```json\n{json.dumps(payload)}\n```\n"
    assert parse_file_map(raw) == payload["files"]
    # Plain JSON works too.
    assert parse_file_map(json.dumps(payload)) == payload["files"]


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        json.dumps({"nofiles": {}}),
        json.dumps({"files": ["src/app/page.tsx"]}),
        json.dumps({"files": {"src/app/page.tsx": 42}}),
    ],
)
def test_parse_file_map_rejects_malformed(raw: str) -> None:
    with pytest.raises(MigrationError):
        parse_file_map(raw)


@pytest.mark.parametrize(
    "path",
    [
        "../x.tsx",
        "/etc/passwd",
        "src/app/../../x.tsx",
        "src\\app\\page.tsx",
        "C:/x.tsx",
        "",
    ],
)
def test_validate_rejects_traversal_and_absolute(path: str) -> None:
    with pytest.raises(MigrationError):
        validate_file_map({path: "x"}, NEXTJS_TARGETS)


@pytest.mark.parametrize(
    "path",
    [
        "package.json",
        "node_modules/a.ts",
        "src/components/nested/Deep.tsx",
        "next.config.ts",
        "Dockerfile",
        "public/logo.png",
        "public/evil.js",
    ],
)
def test_validate_rejects_disallowed_targets(path: str) -> None:
    with pytest.raises(MigrationError):
        validate_file_map({path: "x"}, NEXTJS_TARGETS)


def test_validate_rejects_oversize() -> None:
    with pytest.raises(MigrationError):
        validate_file_map({"src/app/page.tsx": "a" * (200 * 1024 + 1)}, NEXTJS_TARGETS)
    too_many = {f"src/components/C{i}.tsx": "x" for i in range(41)}
    with pytest.raises(MigrationError):
        validate_file_map(too_many, NEXTJS_TARGETS)


def test_validate_accepts_allowed_files() -> None:
    files = {
        "src/app/page.tsx": "page",
        "src/components/Card.tsx": "card",
        "public/logo.svg": "<svg/>",
    }
    assert validate_file_map(files, NEXTJS_TARGETS) == files


def test_validate_rejects_empty_map() -> None:
    with pytest.raises(MigrationError):
        validate_file_map({}, NEXTJS_TARGETS)


@pytest.mark.asyncio
async def test_migrate_static_skips_llm(tmp_path: Path) -> None:
    async def llm(system: str, user: str) -> str:
        raise AssertionError("static templates must not call the LLM")

    files = await migrate_mock(
        mock_html=MOCK_HTML,
        template=_template(has_scaffold=False, tmp_path=tmp_path),
        app_title="Coffee",
        llm=llm,
    )
    assert files == {"public/index.html": MOCK_HTML}


@pytest.mark.asyncio
async def test_migrate_nextjs_uses_llm_and_validates(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    page = 'export default function Page() { return <h1 className="text-3xl">Coffee</h1>; }'

    async def llm(system: str, user: str) -> str:
        calls.append((system, user))
        return "```json\n" + json.dumps({"files": {"src/app/page.tsx": page}}) + "\n```"

    template = _template(has_scaffold=True, tmp_path=tmp_path)
    files = await migrate_mock(
        mock_html=MOCK_HTML, template=template, app_title="Coffee", llm=llm
    )

    assert len(calls) == 1
    system, user = calls[0]
    assert "next/font" in system
    for target in NEXTJS_TARGETS:
        assert target in user
    assert MOCK_HTML in user
    assert files["src/app/page.tsx"] == page
    # The original mock is kept at the template's mock_path.
    assert files["design/mock.html"] == MOCK_HTML


@pytest.mark.asyncio
async def test_migrate_nextjs_rejects_malicious_output(tmp_path: Path) -> None:
    async def llm(system: str, user: str) -> str:
        return json.dumps({"files": {"../../etc/cron.d/x.ts": "boom"}})

    with pytest.raises(MigrationError):
        await migrate_mock(
            mock_html=MOCK_HTML,
            template=_template(has_scaffold=True, tmp_path=tmp_path),
            app_title="Coffee",
            llm=llm,
        )


SCAFFOLD_LAYOUT = """import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Create Next App",
  description: "Generated by create next app",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        {children}
      </body>
    </html>
  );
}
"""

SCAFFOLD_GLOBALS = """@import "tailwindcss";

:root {
  --background: #ffffff;
  --foreground: #171717;
}

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --font-sans: var(--font-geist-sans);
  --font-mono: var(--font-geist-mono);
}
"""


def test_apply_system_fonts_removes_next_font(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    (app_dir / "src/app").mkdir(parents=True)
    (app_dir / "src/app/layout.tsx").write_text(SCAFFOLD_LAYOUT)
    (app_dir / "src/app/globals.css").write_text(SCAFFOLD_GLOBALS)

    apply_system_fonts(app_dir, 'Joe\'s "Coffee"')

    layout = (app_dir / "src/app/layout.tsx").read_text()
    assert "next/font" not in layout
    assert "Geist" not in layout
    assert 'import "./globals.css";' in layout
    assert '<html lang="en">' in layout
    assert '<body className="antialiased">' in layout
    assert json.dumps('Joe\'s "Coffee"') in layout

    css = (app_dir / "src/app/globals.css").read_text()
    assert "geist" not in css.lower()
    assert '@import "tailwindcss";' in css
    assert "--font-sans:" in css
    assert "system-ui" in css


def test_apply_system_fonts_writes_globals_when_missing(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    apply_system_fonts(app_dir, "T")
    assert '@import "tailwindcss";' in (app_dir / "src/app/globals.css").read_text()
    assert (app_dir / "src/app/layout.tsx").exists()


def test_default_migration_llm_requires_a_key() -> None:
    with pytest.raises(MigrationError, match="No API key for migration"):
        default_migration_llm(
            openai_api_key=None, anthropic_api_key=None, gemini_api_key=None
        )


class _FakeSession:
    def __init__(self, text: str) -> None:
        self.text = text
        self.closed = False

    async def stream_turn(self, on_event):  # type: ignore[no-untyped-def]
        from agent.providers.base import ProviderTurn

        return ProviderTurn(assistant_text=self.text, tool_calls=[])

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_default_migration_llm_prefers_anthropic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import stack_generator.migrate as migrate_module
    from llm import ANTHROPIC_MODELS, OPENAI_MODELS, GEMINI_MODELS

    seen: list[dict[str, object]] = []
    session = _FakeSession('{"files": {}}')

    def fake_factory(**kwargs: object) -> _FakeSession:
        seen.append(kwargs)
        return session

    monkeypatch.setattr(migrate_module, "create_provider_session", fake_factory)

    llm = default_migration_llm(
        openai_api_key="sk-o", anthropic_api_key="sk-a", gemini_api_key="g"
    )
    assert await llm("SYSTEM", "USER") == '{"files": {}}'
    assert seen[0]["model"] in ANTHROPIC_MODELS
    assert seen[0]["tools_enabled"] is False
    messages = seen[0]["prompt_messages"]
    assert isinstance(messages, list)
    assert messages[0] == {"role": "system", "content": "SYSTEM"}
    assert messages[1] == {"role": "user", "content": "USER"}
    assert session.closed

    llm = default_migration_llm(
        openai_api_key="sk-o", anthropic_api_key=None, gemini_api_key="g"
    )
    await llm("S", "U")
    assert seen[1]["model"] in OPENAI_MODELS
    assert seen[1]["tools_enabled"] is False

    llm = default_migration_llm(
        openai_api_key=None, anthropic_api_key=None, gemini_api_key="g"
    )
    await llm("S", "U")
    assert seen[2]["model"] in GEMINI_MODELS
    assert seen[2]["tools_enabled"] is False
