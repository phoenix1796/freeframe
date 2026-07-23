"""Tests for POST /assets/{id}/transcript — owner-only on-demand trigger."""
import uuid
from unittest.mock import MagicMock, patch

from apps.api.models.project import ProjectRole


def _setup(mock_db, role, asset_type="video"):
    from apps.api.models.asset import AssetType

    mock_db.order_by.return_value = mock_db

    asset = MagicMock()
    asset.id = uuid.uuid4()
    asset.project_id = uuid.uuid4()
    asset.asset_type = AssetType.video if asset_type == "video" else AssetType.image
    asset.deleted_at = None

    version = MagicMock()
    version.id = uuid.uuid4()
    version.asset_id = asset.id
    version.deleted_at = None
    version.transcript_requested = False

    media_file = MagicMock()
    media_file.version_id = version.id

    member = MagicMock()
    member.role = role

    mock_db.first.side_effect = [asset, member, version, media_file]
    return asset, version, media_file


def test_owner_can_request_transcript(client, mock_db, auth_headers):
    asset, version, media_file = _setup(mock_db, ProjectRole.owner)

    with patch("apps.api.tasks.celery_app.send_task_safe") as mock_send:
        resp = client.post(f"/assets/{asset.id}/transcript", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "requested"
    assert version.transcript_requested is True
    mock_db.commit.assert_called()
    mock_send.assert_called_once()


def test_editor_is_forbidden(client, mock_db, auth_headers):
    asset, version, media_file = _setup(mock_db, ProjectRole.editor)

    resp = client.post(f"/assets/{asset.id}/transcript", headers=auth_headers)

    assert resp.status_code == 403, resp.text
    assert version.transcript_requested is False


def test_viewer_is_forbidden(client, mock_db, auth_headers):
    asset, version, media_file = _setup(mock_db, ProjectRole.viewer)

    resp = client.post(f"/assets/{asset.id}/transcript", headers=auth_headers)

    assert resp.status_code == 403, resp.text


def test_non_member_is_forbidden(client, mock_db, auth_headers):
    from apps.api.models.asset import AssetType

    mock_db.order_by.return_value = mock_db
    asset = MagicMock()
    asset.id = uuid.uuid4()
    asset.project_id = uuid.uuid4()
    asset.asset_type = AssetType.video
    asset.deleted_at = None

    # asset lookup -> asset, then require_project_role's member lookup -> None
    mock_db.first.side_effect = [asset, None]

    resp = client.post(f"/assets/{asset.id}/transcript", headers=auth_headers)

    assert resp.status_code == 403, resp.text


def test_image_asset_rejected(client, mock_db, auth_headers):
    asset, version, media_file = _setup(mock_db, ProjectRole.owner, asset_type="image")

    resp = client.post(f"/assets/{asset.id}/transcript", headers=auth_headers)

    assert resp.status_code == 400, resp.text


def test_404_when_asset_missing(client, mock_db, auth_headers):
    mock_db.first.return_value = None
    resp = client.post(f"/assets/{uuid.uuid4()}/transcript", headers=auth_headers)
    assert resp.status_code == 404
