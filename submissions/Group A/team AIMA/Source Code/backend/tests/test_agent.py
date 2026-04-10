"""Tests for core.agent module"""

import pytest
from core.agent import build_tts_config, build_asr_config, create_agent_payload


@pytest.mark.unit
class TestBuildTTSConfig:
    """Tests for build_tts_config function"""

    def test_openai_tts_config(self, test_constants):
        """Test OpenAI TTS configuration"""
        config = build_tts_config("openai", test_constants)

        assert config["vendor"] == "openai"
        assert "params" in config
        assert config["params"]["api_key"] == "test_tts_key"
        assert config["params"]["model"] == "tts-1"
        assert config["params"]["voice"] == "alloy"
        assert config["params"]["response_format"] == "pcm"
        assert config["params"]["speed"] == 1.0

    def test_elevenlabs_tts_config(self, test_constants):
        """Test ElevenLabs TTS configuration"""
        constants = test_constants.copy()
        constants["TTS_VENDOR"] = "elevenlabs"
        constants["TTS_VOICE_ID"] = "test_voice_id"

        config = build_tts_config("elevenlabs", constants)

        assert config["vendor"] == "elevenlabs"
        assert "params" in config
        assert config["params"]["key"] == "test_tts_key"
        assert config["params"]["voice_id"] == "test_voice_id"
        assert config["params"]["model_id"] == "eleven_turbo_v2_5"
        assert config["params"]["stability"] == 0.5

    def test_elevenlabs_missing_voice_id(self, test_constants):
        """Test that ElevenLabs raises error without voice_id"""
        constants = test_constants.copy()
        constants["TTS_VOICE_ID"] = ""  # Empty voice ID
        with pytest.raises(ValueError, match="TTS_VOICE_ID is required"):
            build_tts_config("elevenlabs", constants)

    def test_query_param_overrides(self, test_constants):
        """Test that query params override defaults"""
        query_params = {
            "voice_id": "custom_voice",
            "voice_speed": "1.5"
        }

        config = build_tts_config("openai", test_constants, query_params)

        assert config["params"]["voice"] == "custom_voice"
        assert config["params"]["speed"] == 1.5


@pytest.mark.unit
class TestBuildASRConfig:
    """Tests for build_asr_config function"""

    def test_ares_asr_config(self, test_constants):
        """Test Ares ASR configuration"""
        constants = test_constants.copy()
        constants["ASR_VENDOR"] = "ares"
        constants["ASR_LANGUAGE"] = "en-US"

        config = build_asr_config("ares", constants)

        assert config["vendor"] == "ares"
        assert "language" in config
        assert config["language"] == "en-US"


@pytest.mark.unit
class TestCreateAgentPayload:
    """Tests for create_agent_payload function"""

    def test_basic_payload_structure(self, test_constants):
        """Test basic agent payload structure"""
        # Add required constants
        constants = test_constants.copy()
        constants.update({
            "LLM_URL": "https://api.openai.com/v1/chat/completions",
            "DEFAULT_PROMPT": "You are a helpful assistant",
            "DEFAULT_GREETING": "Hello",
            "DEFAULT_FAILURE_MESSAGE": "Sorry, I encountered an error",
            "MAX_HISTORY": 10,
            "IDLE_TIMEOUT": 300,
            "VAD_SILENCE_DURATION_MS": 500,
            "ENABLE_AIVAD": "false",
            "ASR_VENDOR": "ares",
            "ASR_LANGUAGE": "en-US",
            "AVATAR_VENDOR": ""
        })

        payload = create_agent_payload(
            channel="test_channel",
            constants=constants,
            query_params={},
            agent_video_token="test_token"
        )

        # Check required fields
        assert "name" in payload
        assert payload["name"] == "test_channel"
        assert "properties" in payload
        assert "tts" in payload["properties"]
        assert "llm" in payload["properties"]
        assert "asr" in payload["properties"]

    def test_payload_with_avatar(self, test_constants):
        """Test payload includes avatar when vendor is set"""
        constants = test_constants.copy()
        constants.update({
            "LLM_URL": "https://api.openai.com/v1/chat/completions",
            "DEFAULT_PROMPT": "You are a helpful assistant",
            "DEFAULT_GREETING": "Hello",
            "DEFAULT_FAILURE_MESSAGE": "Error",
            "MAX_HISTORY": 10,
            "IDLE_TIMEOUT": 300,
            "VAD_SILENCE_DURATION_MS": 500,
            "ENABLE_AIVAD": "false",
            "ASR_VENDOR": "ares",
            "ASR_LANGUAGE": "en-US",
            "AVATAR_VENDOR": "heygen",
            "AVATAR_API_KEY": "test_key",
            "AVATAR_ID": "test_avatar",
            "HEYGEN_QUALITY": "high",
            "HEYGEN_ACTIVITY_IDLE_TIMEOUT": 60
        })

        payload = create_agent_payload(
            channel="test_channel",
            constants=constants,
            query_params={},
            agent_video_token="video_token_here"
        )

        assert "avatar" in payload["properties"]
        assert payload["properties"]["avatar"]["vendor"] == "heygen"

    def test_payload_missing_tts_vendor(self, test_constants):
        """Test that missing TTS_VENDOR raises error"""
        constants = test_constants.copy()
        constants["TTS_VENDOR"] = ""
        constants.update({
            "LLM_URL": "https://api.openai.com/v1/chat/completions",
            "DEFAULT_PROMPT": "You are a helpful assistant",
            "DEFAULT_GREETING": "Hello",
            "DEFAULT_FAILURE_MESSAGE": "Error",
            "MAX_HISTORY": 10,
            "IDLE_TIMEOUT": 300,
            "VAD_SILENCE_DURATION_MS": 500,
            "ENABLE_AIVAD": "false",
            "ASR_VENDOR": "ares",
            "ASR_LANGUAGE": "en-US",
            "AVATAR_VENDOR": ""
        })

        with pytest.raises(ValueError, match="TTS_VENDOR must be set"):
            create_agent_payload(
                channel="test_channel",
                constants=constants,
                query_params={},
                agent_video_token=""
            )

    def test_heygen_missing_api_key(self, test_constants):
        """Test that HeyGen without API key raises error"""
        constants = test_constants.copy()
        constants.update({
            "LLM_URL": "https://api.openai.com/v1/chat/completions",
            "DEFAULT_PROMPT": "You are a helpful assistant",
            "DEFAULT_GREETING": "Hello",
            "DEFAULT_FAILURE_MESSAGE": "Error",
            "MAX_HISTORY": 10,
            "IDLE_TIMEOUT": 300,
            "VAD_SILENCE_DURATION_MS": 500,
            "ENABLE_AIVAD": "false",
            "ASR_VENDOR": "ares",
            "ASR_LANGUAGE": "en-US",
            "AVATAR_VENDOR": "heygen",
            "AVATAR_API_KEY": "",  # Missing
            "AVATAR_ID": "test_avatar",
            "HEYGEN_QUALITY": "high",
            "HEYGEN_ACTIVITY_IDLE_TIMEOUT": 60
        })

        with pytest.raises(ValueError, match="AVATAR_API_KEY is required"):
            create_agent_payload(
                channel="test_channel",
                constants=constants,
                query_params={},
                agent_video_token="video_token"
            )

    def test_heygen_missing_avatar_id(self, test_constants):
        """Test that HeyGen without avatar ID raises error"""
        constants = test_constants.copy()
        constants.update({
            "LLM_URL": "https://api.openai.com/v1/chat/completions",
            "DEFAULT_PROMPT": "You are a helpful assistant",
            "DEFAULT_GREETING": "Hello",
            "DEFAULT_FAILURE_MESSAGE": "Error",
            "MAX_HISTORY": 10,
            "IDLE_TIMEOUT": 300,
            "VAD_SILENCE_DURATION_MS": 500,
            "ENABLE_AIVAD": "false",
            "ASR_VENDOR": "ares",
            "ASR_LANGUAGE": "en-US",
            "AVATAR_VENDOR": "heygen",
            "AVATAR_API_KEY": "test_key",
            "AVATAR_ID": "",  # Missing
            "HEYGEN_QUALITY": "high",
            "HEYGEN_ACTIVITY_IDLE_TIMEOUT": 60
        })

        with pytest.raises(ValueError, match="AVATAR_ID is required"):
            create_agent_payload(
                channel="test_channel",
                constants=constants,
                query_params={},
                agent_video_token="video_token"
            )

    def test_anam_missing_api_key(self, test_constants):
        """Test that Anam without API key raises error"""
        constants = test_constants.copy()
        constants.update({
            "LLM_URL": "https://api.openai.com/v1/chat/completions",
            "DEFAULT_PROMPT": "You are a helpful assistant",
            "DEFAULT_GREETING": "Hello",
            "DEFAULT_FAILURE_MESSAGE": "Error",
            "MAX_HISTORY": 10,
            "IDLE_TIMEOUT": 300,
            "VAD_SILENCE_DURATION_MS": 500,
            "ENABLE_AIVAD": "false",
            "ASR_VENDOR": "ares",
            "ASR_LANGUAGE": "en-US",
            "AVATAR_VENDOR": "anam",
            "AVATAR_API_KEY": "",  # Missing
            "AVATAR_ID": "test_avatar",
            "ANAM_AGENT_ENDPOINT": "https://test.endpoint.com"
        })

        with pytest.raises(ValueError, match="AVATAR_API_KEY is required"):
            create_agent_payload(
                channel="test_channel",
                constants=constants,
                query_params={},
                agent_video_token="video_token"
            )

    def test_anam_missing_avatar_id(self, test_constants):
        """Test that Anam without avatar ID raises error"""
        constants = test_constants.copy()
        constants.update({
            "LLM_URL": "https://api.openai.com/v1/chat/completions",
            "DEFAULT_PROMPT": "You are a helpful assistant",
            "DEFAULT_GREETING": "Hello",
            "DEFAULT_FAILURE_MESSAGE": "Error",
            "MAX_HISTORY": 10,
            "IDLE_TIMEOUT": 300,
            "VAD_SILENCE_DURATION_MS": 500,
            "ENABLE_AIVAD": "false",
            "ASR_VENDOR": "ares",
            "ASR_LANGUAGE": "en-US",
            "AVATAR_VENDOR": "anam",
            "AVATAR_API_KEY": "test_key",
            "AVATAR_ID": "",  # Missing
            "ANAM_AGENT_ENDPOINT": "https://test.endpoint.com"
        })

        with pytest.raises(ValueError, match="AVATAR_ID is required"):
            create_agent_payload(
                channel="test_channel",
                constants=constants,
                query_params={},
                agent_video_token="video_token"
            )
