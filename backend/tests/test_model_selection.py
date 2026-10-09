import pytest
from unittest.mock import AsyncMock
from routes.generate_code import ModelSelectionStage
from llm import Llm


class TestModelSelectionAllKeys:
    """Test model selection when Gemini, Anthropic, and OpenAI API keys are present."""

    def setup_method(self):
        """Set up test fixtures."""
        mock_throw_error = AsyncMock()
        self.model_selector = ModelSelectionStage(mock_throw_error)

    @pytest.mark.asyncio
    async def test_gemini_anthropic_create(self):
        """All keys text create: fixed order for four variants."""
        models = await self.model_selector.select_models(
            generation_type="create",
            input_mode="text",
            openai_api_key="key",
            anthropic_api_key="key",
            gemini_api_key="key",
        )

        expected = [
            Llm.CLAUDE_FABLE_5_1_HIGH,
            Llm.GPT_5_6_SOL_HIGH,
            Llm.GEMINI_3_8_FLASH_HIGH,
            Llm.CLAUDE_OPUS_5_5_MEDIUM,
        ]
        assert models == expected

    @pytest.mark.asyncio
    async def test_gemini_anthropic_create_image(self):
        """All keys image create: fixed order for four variants."""
        models = await self.model_selector.select_models(
            generation_type="create",
            input_mode="image",
            openai_api_key="key",
            anthropic_api_key="key",
            gemini_api_key="key",
        )

        expected = [
            Llm.CLAUDE_FABLE_5_1_HIGH,
            Llm.GEMINI_3_1_PRO_PREVIEW_HIGH,
            Llm.GPT_5_6_SOL_HIGH,
            Llm.CLAUDE_OPUS_5_5_MEDIUM,
        ]
        assert models == expected

    @pytest.mark.asyncio
    async def test_gemini_anthropic_update_text(self):
        """All keys text update: Claude and GPT so the two options differ."""
        models = await self.model_selector.select_models(
            generation_type="update",
            input_mode="text",
            openai_api_key="key",
            anthropic_api_key="key",
            gemini_api_key="key",
        )

        expected = [
            Llm.CLAUDE_OPUS_5_5_MEDIUM,
            Llm.GPT_5_6_SOL_HIGH,
        ]
        assert models == expected

    @pytest.mark.asyncio
    async def test_gemini_anthropic_update(self):
        """All keys image update: Claude and GPT so the two options differ."""
        models = await self.model_selector.select_models(
            generation_type="update",
            input_mode="image",
            openai_api_key="key",
            anthropic_api_key="key",
            gemini_api_key="key",
        )

        expected = [
            Llm.CLAUDE_OPUS_5_5_MEDIUM,
            Llm.GPT_5_6_SOL_HIGH,
        ]
        assert models == expected

    @pytest.mark.asyncio
    async def test_video_create_prefers_gemini_minimal_then_3_1_high(self):
        """Video create always uses two Gemini variants in fixed order."""
        models = await self.model_selector.select_models(
            generation_type="create",
            input_mode="video",
            openai_api_key="key",
            anthropic_api_key="key",
            gemini_api_key="key",
        )

        expected = [
            Llm.GEMINI_3_FLASH_PREVIEW_MINIMAL,
            Llm.GEMINI_3_1_PRO_PREVIEW_HIGH,
        ]
        assert models == expected

    @pytest.mark.asyncio
    async def test_video_update_prefers_gemini_minimal_then_3_1_high(self):
        """Video update always uses the same two Gemini variants as video create."""
        models = await self.model_selector.select_models(
            generation_type="update",
            input_mode="video",
            openai_api_key="key",
            anthropic_api_key="key",
            gemini_api_key="key",
        )

        expected = [
            Llm.GEMINI_3_FLASH_PREVIEW_MINIMAL,
            Llm.GEMINI_3_1_PRO_PREVIEW_HIGH,
        ]
        assert models == expected


class TestModelSelectionOpenAIAnthropic:
    """Test model selection when only OpenAI and Anthropic keys are present."""

    def setup_method(self):
        """Set up test fixtures."""
        mock_throw_error = AsyncMock()
        self.model_selector = ModelSelectionStage(mock_throw_error)

    @pytest.mark.asyncio
    async def test_openai_anthropic(self):
        """OpenAI + Anthropic: Claude Opus 5.5 medium, GPT 5.5 high, GPT 5.5 low, cycling"""
        models = await self.model_selector.select_models(
            generation_type="create",
            input_mode="text",
            openai_api_key="key",
            anthropic_api_key="key",
            gemini_api_key=None,
        )

        expected = [
            Llm.CLAUDE_OPUS_5_5_MEDIUM,
            Llm.GPT_5_5_HIGH,
            Llm.GPT_5_5_LOW,
            Llm.CLAUDE_OPUS_5_5_MEDIUM,
        ]
        assert models == expected


class TestModelSelectionGeminiSubsets:
    """Key subsets that include Gemini use the 3.8 Flash generation."""

    @pytest.mark.asyncio
    async def test_gemini_anthropic(self):
        model_selector = ModelSelectionStage(AsyncMock())
        models = await model_selector.select_models(
            generation_type="create",
            input_mode="text",
            openai_api_key=None,
            anthropic_api_key="key",
            gemini_api_key="key",
        )

        assert models == [
            Llm.GEMINI_3_8_FLASH_MINIMAL,
            Llm.GEMINI_3_1_PRO_PREVIEW_LOW,
            Llm.CLAUDE_OPUS_5_5_MEDIUM,
            Llm.GEMINI_3_8_FLASH_HIGH,
        ]

    @pytest.mark.asyncio
    async def test_gemini_openai(self):
        model_selector = ModelSelectionStage(AsyncMock())
        models = await model_selector.select_models(
            generation_type="create",
            input_mode="text",
            openai_api_key="key",
            anthropic_api_key=None,
            gemini_api_key="key",
        )

        assert models == [
            Llm.GEMINI_3_8_FLASH_MINIMAL,
            Llm.GEMINI_3_1_PRO_PREVIEW_LOW,
            Llm.GPT_5_5_HIGH,
            Llm.GPT_5_5_LOW,
        ]

    @pytest.mark.asyncio
    async def test_gemini_only(self):
        model_selector = ModelSelectionStage(AsyncMock())
        models = await model_selector.select_models(
            generation_type="create",
            input_mode="text",
            openai_api_key=None,
            anthropic_api_key=None,
            gemini_api_key="key",
        )

        assert models == [
            Llm.GEMINI_3_8_FLASH_MINIMAL,
            Llm.GEMINI_3_1_PRO_PREVIEW_LOW,
            Llm.GEMINI_3_8_FLASH_HIGH,
            Llm.GEMINI_3_1_PRO_PREVIEW_HIGH,
        ]


class TestModelSelectionAnthropicOnly:
    """Test model selection when only Anthropic key is present."""

    def setup_method(self):
        """Set up test fixtures."""
        mock_throw_error = AsyncMock()
        self.model_selector = ModelSelectionStage(mock_throw_error)

    @pytest.mark.asyncio
    async def test_anthropic_only(self):
        """Anthropic only: Claude Opus 5.5 medium and Claude Sonnet 5.5 cycling"""
        models = await self.model_selector.select_models(
            generation_type="create",
            input_mode="text",
            openai_api_key=None,
            anthropic_api_key="key",
            gemini_api_key=None,
        )

        expected = [
            Llm.CLAUDE_OPUS_5_5_MEDIUM,
            Llm.CLAUDE_SONNET_5_5,
            Llm.CLAUDE_OPUS_5_5_MEDIUM,
            Llm.CLAUDE_SONNET_5_5,
        ]
        assert models == expected


class TestModelSelectionOpenAIOnly:
    """Test model selection when only OpenAI key is present."""

    def setup_method(self):
        """Set up test fixtures."""
        mock_throw_error = AsyncMock()
        self.model_selector = ModelSelectionStage(mock_throw_error)

    @pytest.mark.asyncio
    async def test_openai_only(self):
        """OpenAI only: GPT 5.5 high and low, cycling"""
        models = await self.model_selector.select_models(
            generation_type="create",
            input_mode="text",
            openai_api_key="key",
            anthropic_api_key=None,
            gemini_api_key=None,
        )

        expected = [
            Llm.GPT_5_5_HIGH,
            Llm.GPT_5_5_LOW,
            Llm.GPT_5_5_HIGH,
            Llm.GPT_5_5_LOW,
        ]
        assert models == expected


class TestModelSelectionNoKeys:
    """Test model selection when no API keys are present."""

    def setup_method(self):
        """Set up test fixtures."""
        mock_throw_error = AsyncMock()
        self.model_selector = ModelSelectionStage(mock_throw_error)

    @pytest.mark.asyncio
    async def test_no_keys_raises_error(self):
        """No keys: Should raise an exception"""
        with pytest.raises(Exception, match="No API key"):
            await self.model_selector.select_models(
                generation_type="create",
                input_mode="text",
                openai_api_key=None,
                anthropic_api_key=None,
                gemini_api_key=None,
            )

    @pytest.mark.asyncio
    async def test_no_keys_reports_generic_missing_key_error(self):
        """No keys: the client is told that no provider key was found."""
        mock_throw_error = AsyncMock()
        model_selector = ModelSelectionStage(mock_throw_error)

        with pytest.raises(Exception, match="No API key"):
            await model_selector.select_models(
                generation_type="create",
                input_mode="image",
                openai_api_key=None,
                anthropic_api_key=None,
                gemini_api_key=None,
            )

        mock_throw_error.assert_awaited_once()
        assert "No OpenAI, Anthropic, or Gemini API key found" in (
            mock_throw_error.await_args_list[0].args[0]
        )


class TestModelSelectionVideoWithoutGemini:
    """Video mode needs Gemini even when other provider keys are present."""

    @pytest.mark.asyncio
    async def test_video_without_gemini_reports_gemini_requirement(self):
        """The client sees the Gemini requirement, not the generic no-key error."""
        mock_throw_error = AsyncMock()
        model_selector = ModelSelectionStage(mock_throw_error)

        with pytest.raises(Exception, match="No API key"):
            await model_selector.select_models(
                generation_type="create",
                input_mode="video",
                openai_api_key="key",
                anthropic_api_key="key",
                gemini_api_key=None,
            )

        mock_throw_error.assert_awaited_once()
        message = mock_throw_error.await_args_list[0].args[0]
        assert "Video mode requires a Gemini API key" in message
        assert "No OpenAI, Anthropic, or Gemini API key found" not in message
