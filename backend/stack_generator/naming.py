"""Names derived from a run: compose/DNS ``APP_ID`` and the npm app slug."""

import re

_MAX_APP_ID_LENGTH = 63
_MAX_SLUG_LENGTH = 40
_STOP_WORDS = {
    "build",
    "make",
    "create",
    "me",
    "a",
    "an",
    "the",
    "please",
    "for",
    "with",
}


def app_id_for(run_id: str, option_index: int) -> str:
    """DNS label (``[a-z0-9-]``, <= 63 chars) for option ``option_index`` (0-based)."""
    suffix = f"-op{option_index + 1}"
    prefix = re.sub(r"[^a-z0-9-]", "-", run_id.replace("_", "-").lower())
    prefix = prefix[: _MAX_APP_ID_LENGTH - len(suffix)].strip("-") or "run"
    return prefix + suffix


def app_slug_from_prompt(prompt_text: str, run_id: str) -> str:
    """npm-safe package name from the prompt; ``app-<run suffix>`` fallback."""
    words = [
        word
        for word in re.findall(r"[a-z0-9]+", prompt_text.lower())
        if word not in _STOP_WORDS
    ]
    slug = "-".join(words)[:_MAX_SLUG_LENGTH].strip("-")
    if slug:
        return slug
    return f"app-{run_id[-8:].lower()}"
