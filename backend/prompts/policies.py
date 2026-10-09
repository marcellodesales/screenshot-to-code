from prompts.prompt_types import Stack

# Shared by the generation system prompt (all stacks) and the Next.js
# migration prompt so generated pages grow with the viewport.
FLUID_LAYOUT_POLICY = """Fluid, full-canvas layout: the page root fills the whole viewport width and at least its height (`w-full min-h-screen`); never wrap the page in a fixed or max-width container; sections span the full width and reflow to use extra space at `lg`/`xl`/`2xl` (more columns, larger gutters) and stack cleanly at 375 px with no horizontal scrolling; cap width only for long-form text blocks (`max-w-prose`), never for the layout itself."""


def build_selected_stack_policy(stack: Stack) -> str:
    return f"Selected stack: {stack}."


def build_user_image_policy(image_generation_enabled: bool) -> str:
    if image_generation_enabled:
        return (
            "Image generation is enabled for this request. Use generate_images for "
            "missing assets when needed."
        )

    return (
        "Image generation is disabled for this request. Do not call generate_images. "
        "Use provided media, CSS effects, or placeholder URLs (https://placehold.co)."
    )
