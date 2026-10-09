from llm import Llm

# Video variants without frames (or with only a Gemini key) use Gemini.
VIDEO_VARIANT_MODELS = (
    Llm.GEMINI_3_FLASH_PREVIEW_MINIMAL,
    Llm.GEMINI_3_1_PRO_PREVIEW_HIGH,
)



def video_frames_variant_models(
    *, openai: bool, anthropic: bool, gemini: bool
) -> tuple[Llm, Llm] | None:
    """Two video variants when the browser sent sampled frames.

    Frame models (Claude/GPT) see the frames as images; Gemini keeps the
    video. Gemini-only keys keep VIDEO_VARIANT_MODELS (returns None).
    """
    if anthropic and gemini:
        return (Llm.CLAUDE_FABLE_5_1_HIGH, Llm.GEMINI_3_1_PRO_PREVIEW_HIGH)
    if openai and gemini:
        return (Llm.GPT_5_6_SOL_HIGH, Llm.GEMINI_3_1_PRO_PREVIEW_HIGH)
    if anthropic and openai:
        return (Llm.CLAUDE_FABLE_5_1_HIGH, Llm.GPT_5_6_SOL_HIGH)
    if anthropic:
        return (Llm.CLAUDE_FABLE_5_1_HIGH, Llm.CLAUDE_OPUS_5_5_MEDIUM)
    if openai:
        return (Llm.GPT_5_6_SOL_HIGH, Llm.GPT_5_6_SOL_MEDIUM)
    return None


# All API keys available.

# Image (Create)

# Refreshed 2026-10-08 for the 5.x registry: quality-first, and every
# option comes from a different provider (or model family) so the options
# visibly differ.
ALL_KEYS_MODELS_DEFAULT = (
    Llm.CLAUDE_FABLE_5_1_HIGH,
    Llm.GEMINI_3_1_PRO_PREVIEW_HIGH,
    Llm.GPT_5_6_SOL_HIGH,
    Llm.CLAUDE_OPUS_5_5_MEDIUM,
)

# Text (Create)

ALL_KEYS_MODELS_TEXT_CREATE = (
    Llm.CLAUDE_FABLE_5_1_HIGH,
    Llm.GPT_5_6_SOL_HIGH,
    Llm.GEMINI_3_8_FLASH_HIGH,
    Llm.CLAUDE_OPUS_5_5_MEDIUM,
)

# Image + Text (Update)

# Two providers so the two edit options differ (a single fast provider
# pair produced near-identical options).
ALL_KEYS_MODELS_UPDATE = (
    Llm.CLAUDE_OPUS_5_5_MEDIUM,
    Llm.GPT_5_6_SOL_HIGH,
)

# Key subset fallbacks.
GEMINI_ANTHROPIC_MODELS = (
    Llm.GEMINI_3_8_FLASH_MINIMAL,
    Llm.GEMINI_3_1_PRO_PREVIEW_LOW,
    Llm.CLAUDE_OPUS_5_5_MEDIUM,
    Llm.GEMINI_3_8_FLASH_HIGH,
    Llm.GEMINI_3_1_PRO_PREVIEW_HIGH,
)
GEMINI_OPENAI_MODELS = (
    Llm.GEMINI_3_8_FLASH_MINIMAL,
    Llm.GEMINI_3_1_PRO_PREVIEW_LOW,
    Llm.GPT_5_5_HIGH,
    Llm.GPT_5_5_LOW,
)
OPENAI_ANTHROPIC_MODELS = (
    Llm.CLAUDE_OPUS_5_5_MEDIUM,
    Llm.GPT_5_5_HIGH,
    Llm.GPT_5_5_LOW,
)
GEMINI_ONLY_MODELS = (
    Llm.GEMINI_3_8_FLASH_MINIMAL,
    Llm.GEMINI_3_1_PRO_PREVIEW_LOW,
    Llm.GEMINI_3_8_FLASH_HIGH,
    Llm.GEMINI_3_1_PRO_PREVIEW_HIGH,
)
ANTHROPIC_ONLY_MODELS = (
    Llm.CLAUDE_OPUS_5_5_MEDIUM,
    Llm.CLAUDE_SONNET_5_5,
)
OPENAI_ONLY_MODELS = (
    Llm.GPT_5_5_HIGH,
    Llm.GPT_5_5_LOW,
)
