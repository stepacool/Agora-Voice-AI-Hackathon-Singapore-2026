"""Integration tests for Flask endpoints"""

import pytest
import responses
import json


@pytest.mark.integration
class TestStartAgentEndpoint:
    """Tests for /start-agent endpoint"""

    @responses.activate
    def test_start_agent_with_channel(self, client):
        """Test /start-agent with explicit channel parameter"""
        # Mock the Agora API response
        responses.add(
            responses.POST,
            "https://api.agora.io/v1/projects/test_app_id/join",
            json={"status": "success", "agent_id": "test_agent_123"},
            status=200
        )

        response = client.get('/start-agent?channel=test_channel&connect=false')

        assert response.status_code == 200
        data = response.json

        # Verify response structure
        assert 'token' in data
        assert 'uid' in data
        assert 'channel' in data
        assert 'appid' in data
        assert 'agent_response' in data

        # Verify channel name
        assert data['channel'] == 'test_channel'

    def test_start_agent_auto_channel(self, client):
        """Test /start-agent auto-generates channel when not provided"""
        response = client.get('/start-agent?connect=false')

        assert response.status_code == 200
        data = response.json

        # Should have auto-generated channel
        assert 'channel' in data
        assert len(data['channel']) == 10
        assert data['channel'].isalnum()

    def test_token_only_mode(self, client):
        """Test connect=false returns tokens without starting agent"""
        response = client.get('/start-agent?connect=false')

        assert response.status_code == 200
        data = response.json

        # Verify token-only response
        assert data['agent_response']['response']['mode'] == 'token_only'
        assert data['agent_response']['response']['connect'] is False
        assert data['agent_response']['success'] is True

    def test_start_agent_response_structure(self, client):
        """Test that response has all required fields"""
        response = client.get('/start-agent?connect=false')
        data = response.json

        # Required fields
        required_fields = [
            'audio_scenario',
            'token',
            'uid',
            'channel',
            'appid',
            'user_token',
            'agent_video_token',
            'agent',
            'agent_rtm_uid',
            'enable_string_uid',
            'agent_response'
        ]

        for field in required_fields:
            assert field in data, f"Missing required field: {field}"


@pytest.mark.integration
class TestHangupAgentEndpoint:
    """Tests for /hangup-agent endpoint"""

    @responses.activate
    def test_hangup_agent_success(self, client):
        """Test /hangup-agent with valid agent_id"""
        # Mock the Agora API response
        responses.add(
            responses.DELETE,
            "https://api.agora.io/v1/projects/test_app_id/test_agent_123",
            json={"status": "success"},
            status=200
        )

        response = client.get('/hangup-agent?agent_id=test_agent_123')

        assert response.status_code == 200
        data = response.json
        assert 'agent_response' in data

    def test_hangup_agent_missing_id(self, client):
        """Test /hangup-agent returns error without agent_id"""
        response = client.get('/hangup-agent')

        assert response.status_code == 400
        data = response.json
        assert 'error' in data
        assert 'agent_id' in data['error']


@pytest.mark.integration
class TestHealthEndpoint:
    """Tests for /health endpoint"""

    def test_health_check(self, client):
        """Test health endpoint returns OK"""
        response = client.get('/health')

        assert response.status_code == 200
        data = response.json

        assert data['status'] == 'ok'
        assert 'service' in data
