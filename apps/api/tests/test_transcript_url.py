"""Tests for GET /assets/{id}/transcript — mirrors test_assets_stream_url.py."""
import uuid
from unittest.mock import MagicMock, patch


def _setup_asset_with_version(mock_db, transcript_key):
    from apps.api.models.asset import AssetType

    mock_db.order_by.return_value = mock_db

    asset = MagicMock()
    asset.id = uuid.uuid4()
    asset.project_id = uuid.uuid4()
    asset.asset_type = AssetType.video
    asset.deleted_at = None

    version = MagicMock()
    version.id = uuid.uuid4()
    version.asset_id = asset.id
    version.deleted_at = None

    media_file = MagicMock()
    media_file.version_id = version.id
    media_file.s3_key_transcript = transcript_key
    media_file.transcript_error = None

    mock_db.first.side_effect = [asset, version, media_file]
    return asset, version, media_file


@patch("apps.api.routers.assets.generate_presigned_get_url")
@patch("apps.api.routers.assets.require_asset_access")
def test_returns_presigned_url_when_transcript_exists(
    mock_require_access, mock_presign, client, mock_db, auth_headers,
):
    mock_require_access.return_value = None
    mock_presign.return_value = "https://s3.example.com/transcript.json?sig=abc"

    asset, _, _ = _setup_asset_with_version(mock_db, "processed/proj/asset/version/transcript.json")

    response = client.get(f"/assets/{asset.id}/transcript", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["url"] == "https://s3.example.com/transcript.json?sig=abc"
    mock_presign.assert_called_once_with("processed/proj/asset/version/transcript.json")


@patch("apps.api.routers.assets.require_asset_access")
def test_returns_null_url_when_no_transcript_yet(
    mock_require_access, client, mock_db, auth_headers,
):
    mock_require_access.return_value = None
    _setup_asset_with_version(mock_db, transcript_key=None)

    response = client.get(f"/assets/{uuid.uuid4()}/transcript", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["url"] is None


@patch("apps.api.routers.assets.require_asset_access")
def test_404_when_asset_missing(mock_require_access, client, mock_db, auth_headers):
    mock_db.first.return_value = None
    response = client.get(f"/assets/{uuid.uuid4()}/transcript", headers=auth_headers)
    assert response.status_code == 404


@patch("apps.api.routers.assets.require_asset_access")
def test_returns_error_instead_of_polling_forever(
    mock_require_access, client, mock_db, auth_headers,
):
    """A failed/disabled-provider run must surface as an error, not look
    identical to "still generating" (url=None in both cases otherwise)."""
    mock_require_access.return_value = None
    asset, _, media_file = _setup_asset_with_version(mock_db, transcript_key=None)
    media_file.transcript_error = "Transcription isn't set up for this instance yet."

    response = client.get(f"/assets/{asset.id}/transcript", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["url"] is None
    assert body["error"] == "Transcription isn't set up for this instance yet."
