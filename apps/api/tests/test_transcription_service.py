"""Tests for services/transcription_service.py — provider selection and the
AssemblyAI submit+poll flow, without hitting the network."""
from unittest.mock import MagicMock, patch

import pytest

from apps.api.services.transcription_service import transcribe_via_provider, TranscriptionError


@patch("apps.api.services.transcription_service.settings")
def test_returns_none_when_provider_disabled(mock_settings):
    mock_settings.transcription_provider = "none"
    assert transcribe_via_provider("https://example.com/audio.mp4") is None


@patch("apps.api.services.transcription_service.settings")
def test_raises_on_unknown_provider(mock_settings):
    mock_settings.transcription_provider = "not_a_real_provider"
    with pytest.raises(TranscriptionError):
        transcribe_via_provider("https://example.com/audio.mp4")


@patch("apps.api.services.transcription_service.settings")
def test_raises_when_assemblyai_key_missing(mock_settings):
    mock_settings.transcription_provider = "assemblyai"
    mock_settings.assemblyai_api_key = None
    with pytest.raises(TranscriptionError):
        transcribe_via_provider("https://example.com/audio.mp4")


@patch("apps.api.services.transcription_service.settings")
def test_assemblyai_happy_path_converts_ms_to_seconds(mock_settings):
    mock_settings.transcription_provider = "assemblyai"
    mock_settings.assemblyai_api_key = "test-key"

    submit_response = MagicMock()
    submit_response.json.return_value = {"id": "transcript-123", "status": "queued"}
    submit_response.raise_for_status.return_value = None

    poll_response = MagicMock()
    poll_response.json.return_value = {
        "status": "completed",
        "words": [
            {"text": "Hello", "start": 340, "end": 620, "confidence": 0.99},
            {"text": "world", "start": 620, "end": 980, "confidence": 0.97},
        ],
    }
    poll_response.raise_for_status.return_value = None

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = submit_response
    mock_client.get.return_value = poll_response

    with patch("httpx.Client", return_value=mock_client):
        words = transcribe_via_provider("https://example.com/audio.mp4")

    assert words == [
        {"text": "Hello", "start": 0.34, "end": 0.62},
        {"text": "world", "start": 0.62, "end": 0.98},
    ]
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert call_kwargs.kwargs["json"] == {"audio_url": "https://example.com/audio.mp4"}
    assert call_kwargs.kwargs["headers"] == {"authorization": "test-key"}


@patch("apps.api.services.transcription_service.settings")
def test_assemblyai_polls_until_completed(mock_settings):
    mock_settings.transcription_provider = "assemblyai"
    mock_settings.assemblyai_api_key = "test-key"

    submit_response = MagicMock()
    submit_response.json.return_value = {"id": "transcript-123"}
    submit_response.raise_for_status.return_value = None

    processing_response = MagicMock()
    processing_response.json.return_value = {"status": "processing"}
    processing_response.raise_for_status.return_value = None

    done_response = MagicMock()
    done_response.json.return_value = {"status": "completed", "words": []}
    done_response.raise_for_status.return_value = None

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = submit_response
    mock_client.get.side_effect = [processing_response, processing_response, done_response]

    with patch("httpx.Client", return_value=mock_client), patch("time.sleep"):
        words = transcribe_via_provider("https://example.com/audio.mp4")

    assert words == []
    assert mock_client.get.call_count == 3


@patch("apps.api.services.transcription_service.settings")
def test_assemblyai_raises_on_provider_error_status(mock_settings):
    mock_settings.transcription_provider = "assemblyai"
    mock_settings.assemblyai_api_key = "test-key"

    submit_response = MagicMock()
    submit_response.json.return_value = {"id": "transcript-123"}
    submit_response.raise_for_status.return_value = None

    error_response = MagicMock()
    error_response.json.return_value = {"status": "error", "error": "bad audio file"}
    error_response.raise_for_status.return_value = None

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = submit_response
    mock_client.get.return_value = error_response

    with patch("httpx.Client", return_value=mock_client):
        with pytest.raises(TranscriptionError, match="bad audio file"):
            transcribe_via_provider("https://example.com/audio.mp4")
