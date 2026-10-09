from enum import Enum
from typing import TypedDict


# Actual model versions that are passed to the LLMs and stored in our logs
class Llm(Enum):
    # GPT
    GPT_5_4_MINI_LOW = "gpt-5.4-mini (low thinking)"
    GPT_5_4_2026_03_05_NONE = "gpt-5.4-2026-03-05 (no thinking)"
    GPT_5_4_2026_03_05_LOW = "gpt-5.4-2026-03-05 (low thinking)"
    GPT_5_4_2026_03_05_MEDIUM = "gpt-5.4-2026-03-05 (medium thinking)"
    GPT_5_4_2026_03_05_HIGH = "gpt-5.4-2026-03-05 (high thinking)"
    GPT_5_4_2026_03_05_XHIGH = "gpt-5.4-2026-03-05 (xhigh thinking)"
    GPT_5_5_NONE = "gpt-5.5 (no thinking)"
    GPT_5_5_LOW = "gpt-5.5 (low thinking)"
    GPT_5_5_MEDIUM = "gpt-5.5 (medium thinking)"
    GPT_5_5_HIGH = "gpt-5.5 (high thinking)"
    GPT_5_5_XHIGH = "gpt-5.5 (xhigh thinking)"
    GPT_5_6_SOL_NONE = "gpt-5.6-sol (no thinking)"
    GPT_5_6_SOL_LOW = "gpt-5.6-sol (low thinking)"
    GPT_5_6_SOL_MEDIUM = "gpt-5.6-sol (medium thinking)"
    GPT_5_6_SOL_HIGH = "gpt-5.6-sol (high thinking)"
    GPT_5_6_SOL_XHIGH = "gpt-5.6-sol (xhigh thinking)"
    GPT_5_6_SOL_MAX = "gpt-5.6-sol (max thinking)"
    GPT_5_6_TERRA_LOW = "gpt-5.6-terra (low thinking)"
    GPT_5_6_LUNA_NONE = "gpt-5.6-luna (no thinking)"
    GPT_5_6_LUNA_LOW = "gpt-5.6-luna (low thinking)"
    GPT_5_6_LUNA_MEDIUM = "gpt-5.6-luna (medium thinking)"
    GPT_5_6_LUNA_HIGH = "gpt-5.6-luna (high thinking)"
    GPT_5_6_LUNA_XHIGH = "gpt-5.6-luna (xhigh thinking)"
    GPT_5_6_LUNA_MAX = "gpt-5.6-luna (max thinking)"
    # Claude
    CLAUDE_SONNET_4_6 = "claude-sonnet-4-6"
    CLAUDE_OPUS_5_LOW = "claude-opus-5 (low effort)"
    CLAUDE_OPUS_5_MEDIUM = "claude-opus-5 (medium effort)"
    CLAUDE_OPUS_5_HIGH = "claude-opus-5 (high effort)"
    CLAUDE_OPUS_5_XHIGH = "claude-opus-5 (xhigh effort)"
    CLAUDE_OPUS_5_MAX = "claude-opus-5 (max effort)"
    CLAUDE_OPUS_4_8_LOW = "claude-opus-4-8 (low effort)"
    CLAUDE_OPUS_4_8_MEDIUM = "claude-opus-4-8 (medium effort)"
    CLAUDE_OPUS_4_8_HIGH = "claude-opus-4-8 (high effort)"
    CLAUDE_OPUS_4_8_XHIGH = "claude-opus-4-8 (xhigh effort)"
    CLAUDE_OPUS_4_8_MAX = "claude-opus-4-8 (max effort)"
    CLAUDE_FABLE_5_LOW = "claude-fable-5 (low effort)"
    CLAUDE_FABLE_5_MEDIUM = "claude-fable-5 (medium effort)"
    CLAUDE_FABLE_5_HIGH = "claude-fable-5 (high effort)"
    CLAUDE_FABLE_5_XHIGH = "claude-fable-5 (xhigh effort)"
    CLAUDE_FABLE_5_MAX = "claude-fable-5 (max effort)"
    CLAUDE_FABLE_5_1_LOW = "claude-fable-5-1 (low effort)"
    CLAUDE_FABLE_5_1_MEDIUM = "claude-fable-5-1 (medium effort)"
    CLAUDE_FABLE_5_1_HIGH = "claude-fable-5-1 (high effort)"
    CLAUDE_FABLE_5_1_XHIGH = "claude-fable-5-1 (xhigh effort)"
    CLAUDE_FABLE_5_1_MAX = "claude-fable-5-1 (max effort)"
    CLAUDE_OPUS_5_5_LOW = "claude-opus-5-5 (low effort)"
    CLAUDE_OPUS_5_5_MEDIUM = "claude-opus-5-5 (medium effort)"
    CLAUDE_OPUS_5_5_HIGH = "claude-opus-5-5 (high effort)"
    CLAUDE_OPUS_5_5_XHIGH = "claude-opus-5-5 (xhigh effort)"
    CLAUDE_OPUS_5_5_MAX = "claude-opus-5-5 (max effort)"
    CLAUDE_SONNET_5_5 = "claude-sonnet-5-5"
    CLAUDE_HAIKU_5_5 = "claude-haiku-5-5"
    # Gemini
    GEMINI_3_FLASH_PREVIEW_HIGH = "gemini-3-flash-preview (high thinking)"
    GEMINI_3_FLASH_PREVIEW_MINIMAL = "gemini-3-flash-preview (minimal thinking)"
    GEMINI_3_1_PRO_PREVIEW_HIGH = "gemini-3.1-pro-preview (high thinking)"
    GEMINI_3_1_PRO_PREVIEW_MEDIUM = "gemini-3.1-pro-preview (medium thinking)"
    GEMINI_3_1_PRO_PREVIEW_LOW = "gemini-3.1-pro-preview (low thinking)"
    GEMINI_3_5_FLASH_HIGH = "gemini-3.5-flash (high thinking)"
    GEMINI_3_5_FLASH_MEDIUM = "gemini-3.5-flash (medium thinking)"
    GEMINI_3_5_FLASH_LOW = "gemini-3.5-flash (low thinking)"
    GEMINI_3_5_FLASH_MINIMAL = "gemini-3.5-flash (minimal thinking)"
    GEMINI_3_6_FLASH_HIGH = "gemini-3.6-flash (high thinking)"
    GEMINI_3_6_FLASH_MEDIUM = "gemini-3.6-flash (medium thinking)"
    GEMINI_3_6_FLASH_LOW = "gemini-3.6-flash (low thinking)"
    GEMINI_3_6_FLASH_MINIMAL = "gemini-3.6-flash (minimal thinking)"
    GEMINI_3_8_FLASH_HIGH = "gemini-3.8-flash (high thinking)"
    GEMINI_3_8_FLASH_MEDIUM = "gemini-3.8-flash (medium thinking)"
    GEMINI_3_8_FLASH_LOW = "gemini-3.8-flash (low thinking)"
    GEMINI_3_8_FLASH_MINIMAL = "gemini-3.8-flash (minimal thinking)"


class Completion(TypedDict):
    duration: float
    code: str


# Explicitly map each model to the provider backing it.  This keeps provider
# groupings authoritative and avoids relying on name conventions when checking
# models elsewhere in the codebase.
MODEL_PROVIDER: dict[Llm, str] = {
    # OpenAI models
    Llm.GPT_5_4_MINI_LOW: "openai",
    Llm.GPT_5_4_2026_03_05_NONE: "openai",
    Llm.GPT_5_4_2026_03_05_LOW: "openai",
    Llm.GPT_5_4_2026_03_05_MEDIUM: "openai",
    Llm.GPT_5_4_2026_03_05_HIGH: "openai",
    Llm.GPT_5_4_2026_03_05_XHIGH: "openai",
    Llm.GPT_5_5_NONE: "openai",
    Llm.GPT_5_5_LOW: "openai",
    Llm.GPT_5_5_MEDIUM: "openai",
    Llm.GPT_5_5_HIGH: "openai",
    Llm.GPT_5_5_XHIGH: "openai",
    Llm.GPT_5_6_SOL_NONE: "openai",
    Llm.GPT_5_6_SOL_LOW: "openai",
    Llm.GPT_5_6_SOL_MEDIUM: "openai",
    Llm.GPT_5_6_SOL_HIGH: "openai",
    Llm.GPT_5_6_SOL_XHIGH: "openai",
    Llm.GPT_5_6_SOL_MAX: "openai",
    Llm.GPT_5_6_TERRA_LOW: "openai",
    Llm.GPT_5_6_LUNA_NONE: "openai",
    Llm.GPT_5_6_LUNA_LOW: "openai",
    Llm.GPT_5_6_LUNA_MEDIUM: "openai",
    Llm.GPT_5_6_LUNA_HIGH: "openai",
    Llm.GPT_5_6_LUNA_XHIGH: "openai",
    Llm.GPT_5_6_LUNA_MAX: "openai",
    # Anthropic models
    Llm.CLAUDE_SONNET_4_6: "anthropic",
    Llm.CLAUDE_OPUS_5_LOW: "anthropic",
    Llm.CLAUDE_OPUS_5_MEDIUM: "anthropic",
    Llm.CLAUDE_OPUS_5_HIGH: "anthropic",
    Llm.CLAUDE_OPUS_5_XHIGH: "anthropic",
    Llm.CLAUDE_OPUS_5_MAX: "anthropic",
    Llm.CLAUDE_OPUS_4_8_LOW: "anthropic",
    Llm.CLAUDE_OPUS_4_8_MEDIUM: "anthropic",
    Llm.CLAUDE_OPUS_4_8_HIGH: "anthropic",
    Llm.CLAUDE_OPUS_4_8_XHIGH: "anthropic",
    Llm.CLAUDE_OPUS_4_8_MAX: "anthropic",
    Llm.CLAUDE_FABLE_5_LOW: "anthropic",
    Llm.CLAUDE_FABLE_5_MEDIUM: "anthropic",
    Llm.CLAUDE_FABLE_5_HIGH: "anthropic",
    Llm.CLAUDE_FABLE_5_XHIGH: "anthropic",
    Llm.CLAUDE_FABLE_5_MAX: "anthropic",
    Llm.CLAUDE_FABLE_5_1_LOW: "anthropic",
    Llm.CLAUDE_FABLE_5_1_MEDIUM: "anthropic",
    Llm.CLAUDE_FABLE_5_1_HIGH: "anthropic",
    Llm.CLAUDE_FABLE_5_1_XHIGH: "anthropic",
    Llm.CLAUDE_FABLE_5_1_MAX: "anthropic",
    Llm.CLAUDE_OPUS_5_5_LOW: "anthropic",
    Llm.CLAUDE_OPUS_5_5_MEDIUM: "anthropic",
    Llm.CLAUDE_OPUS_5_5_HIGH: "anthropic",
    Llm.CLAUDE_OPUS_5_5_XHIGH: "anthropic",
    Llm.CLAUDE_OPUS_5_5_MAX: "anthropic",
    Llm.CLAUDE_SONNET_5_5: "anthropic",
    Llm.CLAUDE_HAIKU_5_5: "anthropic",
    # Gemini models
    Llm.GEMINI_3_FLASH_PREVIEW_HIGH: "gemini",
    Llm.GEMINI_3_FLASH_PREVIEW_MINIMAL: "gemini",
    Llm.GEMINI_3_1_PRO_PREVIEW_HIGH: "gemini",
    Llm.GEMINI_3_1_PRO_PREVIEW_MEDIUM: "gemini",
    Llm.GEMINI_3_1_PRO_PREVIEW_LOW: "gemini",
    Llm.GEMINI_3_5_FLASH_HIGH: "gemini",
    Llm.GEMINI_3_5_FLASH_MEDIUM: "gemini",
    Llm.GEMINI_3_5_FLASH_LOW: "gemini",
    Llm.GEMINI_3_5_FLASH_MINIMAL: "gemini",
    Llm.GEMINI_3_6_FLASH_HIGH: "gemini",
    Llm.GEMINI_3_6_FLASH_MEDIUM: "gemini",
    Llm.GEMINI_3_6_FLASH_LOW: "gemini",
    Llm.GEMINI_3_6_FLASH_MINIMAL: "gemini",
    Llm.GEMINI_3_8_FLASH_HIGH: "gemini",
    Llm.GEMINI_3_8_FLASH_MEDIUM: "gemini",
    Llm.GEMINI_3_8_FLASH_LOW: "gemini",
    Llm.GEMINI_3_8_FLASH_MINIMAL: "gemini",
}

# Convenience sets for membership checks
OPENAI_MODELS = {m for m, p in MODEL_PROVIDER.items() if p == "openai"}
ANTHROPIC_MODELS = {m for m, p in MODEL_PROVIDER.items() if p == "anthropic"}
GEMINI_MODELS = {m for m, p in MODEL_PROVIDER.items() if p == "gemini"}

OPENAI_MODEL_CONFIG: dict[Llm, dict[str, str]] = {
    Llm.GPT_5_4_MINI_LOW: {"api_name": "gpt-5.4-mini", "reasoning_effort": "low"},
    Llm.GPT_5_4_2026_03_05_NONE: {
        "api_name": "gpt-5.4-2026-03-05",
        "reasoning_effort": "none",
    },
    Llm.GPT_5_4_2026_03_05_LOW: {
        "api_name": "gpt-5.4-2026-03-05",
        "reasoning_effort": "low",
    },
    Llm.GPT_5_4_2026_03_05_MEDIUM: {
        "api_name": "gpt-5.4-2026-03-05",
        "reasoning_effort": "medium",
    },
    Llm.GPT_5_4_2026_03_05_HIGH: {
        "api_name": "gpt-5.4-2026-03-05",
        "reasoning_effort": "high",
    },
    Llm.GPT_5_4_2026_03_05_XHIGH: {
        "api_name": "gpt-5.4-2026-03-05",
        "reasoning_effort": "xhigh",
    },
    Llm.GPT_5_5_NONE: {"api_name": "gpt-5.5", "reasoning_effort": "none"},
    Llm.GPT_5_5_LOW: {"api_name": "gpt-5.5", "reasoning_effort": "low"},
    Llm.GPT_5_5_MEDIUM: {"api_name": "gpt-5.5", "reasoning_effort": "medium"},
    Llm.GPT_5_5_HIGH: {"api_name": "gpt-5.5", "reasoning_effort": "high"},
    Llm.GPT_5_5_XHIGH: {"api_name": "gpt-5.5", "reasoning_effort": "xhigh"},
    Llm.GPT_5_6_SOL_NONE: {"api_name": "gpt-5.6-sol", "reasoning_effort": "none"},
    Llm.GPT_5_6_SOL_LOW: {"api_name": "gpt-5.6-sol", "reasoning_effort": "low"},
    Llm.GPT_5_6_SOL_MEDIUM: {"api_name": "gpt-5.6-sol", "reasoning_effort": "medium"},
    Llm.GPT_5_6_SOL_HIGH: {"api_name": "gpt-5.6-sol", "reasoning_effort": "high"},
    Llm.GPT_5_6_SOL_XHIGH: {"api_name": "gpt-5.6-sol", "reasoning_effort": "xhigh"},
    Llm.GPT_5_6_SOL_MAX: {"api_name": "gpt-5.6-sol", "reasoning_effort": "max"},
    Llm.GPT_5_6_TERRA_LOW: {"api_name": "gpt-5.6-terra", "reasoning_effort": "low"},
    Llm.GPT_5_6_LUNA_NONE: {"api_name": "gpt-5.6-luna", "reasoning_effort": "none"},
    Llm.GPT_5_6_LUNA_LOW: {"api_name": "gpt-5.6-luna", "reasoning_effort": "low"},
    Llm.GPT_5_6_LUNA_MEDIUM: {"api_name": "gpt-5.6-luna", "reasoning_effort": "medium"},
    Llm.GPT_5_6_LUNA_HIGH: {"api_name": "gpt-5.6-luna", "reasoning_effort": "high"},
    Llm.GPT_5_6_LUNA_XHIGH: {"api_name": "gpt-5.6-luna", "reasoning_effort": "xhigh"},
    Llm.GPT_5_6_LUNA_MAX: {"api_name": "gpt-5.6-luna", "reasoning_effort": "max"},
}


def get_openai_api_name(model: Llm) -> str:
    return OPENAI_MODEL_CONFIG[model]["api_name"]


def get_openai_reasoning_effort(model: Llm) -> str | None:
    return OPENAI_MODEL_CONFIG.get(model, {}).get("reasoning_effort")
