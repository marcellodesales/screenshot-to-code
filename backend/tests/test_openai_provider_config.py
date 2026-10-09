from llm import (
    OPENAI_MODELS,
    Llm,
    get_openai_api_name,
    get_openai_reasoning_effort,
)


def test_gpt_5_6_luna_reasoning_variants_map_to_same_api_model() -> None:
    expected_efforts = {
        Llm.GPT_5_6_LUNA_NONE: "none",
        Llm.GPT_5_6_LUNA_LOW: "low",
        Llm.GPT_5_6_LUNA_MEDIUM: "medium",
        Llm.GPT_5_6_LUNA_HIGH: "high",
        Llm.GPT_5_6_LUNA_XHIGH: "xhigh",
        Llm.GPT_5_6_LUNA_MAX: "max",
    }

    for model, effort in expected_efforts.items():
        assert model in OPENAI_MODELS
        assert get_openai_api_name(model) == "gpt-5.6-luna"
        assert get_openai_reasoning_effort(model) == effort
