"""Tests for tasks/transcription_tasks.py — independent, best-effort task
that must never raise (a failure here must never look like a failed upload)."""
import uuid
from unittest.mock import MagicMock, patch


def _mock_db(version, asset, media_file):
    db = MagicMock()
    db.query.return_value = db
    db.filter.return_value = db
    db.first.side_effect = [version, asset, media_file]
    db.close.return_value = None
    return db


def _entities():
    asset_id = uuid.uuid4()
    version_id = uuid.uuid4()
    version = MagicMock(id=version_id)
    asset = MagicMock(id=asset_id, project_id=uuid.uuid4())
    media_file = MagicMock(version_id=version_id, s3_key_raw="raw/proj/asset/version/original.mp4", s3_key_transcript=None)
    return asset_id, version_id, asset, version, media_file


def test_uploads_transcript_and_sets_key_on_success():
    from apps.api.tasks.transcription_tasks import transcribe_asset

    asset_id, version_id, asset, version, media_file = _entities()
    db = _mock_db(version, asset, media_file)

    with patch("apps.api.tasks.transcription_tasks.SessionLocal", return_value=db), \
         patch("apps.api.tasks.transcription_tasks.generate_presigned_get_url", return_value="https://example/presigned"), \
         patch("apps.api.tasks.transcription_tasks.transcribe_via_provider", return_value=[{"text": "hi", "start": 0.0, "end": 0.3}]), \
         patch("apps.api.tasks.transcription_tasks.put_object") as mock_put, \
         patch("apps.api.tasks.transcription_tasks._publish_event") as mock_publish:
        transcribe_asset.apply(args=(str(asset_id), str(version_id)))

    assert media_file.s3_key_transcript == f"processed/{asset.project_id}/{asset_id}/{version_id}/transcript.json"
    mock_put.assert_called_once()
    db.commit.assert_called()
    mock_publish.assert_called_once_with(
        str(asset.project_id), "transcript_complete",
        {"asset_id": str(asset_id), "version_id": str(version_id)},
    )


def test_noop_when_provider_disabled():
    from apps.api.tasks.transcription_tasks import transcribe_asset

    asset_id, version_id, asset, version, media_file = _entities()
    db = _mock_db(version, asset, media_file)

    with patch("apps.api.tasks.transcription_tasks.SessionLocal", return_value=db), \
         patch("apps.api.tasks.transcription_tasks.generate_presigned_get_url", return_value="https://example/presigned"), \
         patch("apps.api.tasks.transcription_tasks.transcribe_via_provider", return_value=None), \
         patch("apps.api.tasks.transcription_tasks.put_object") as mock_put:
        transcribe_asset.apply(args=(str(asset_id), str(version_id)))

    mock_put.assert_not_called()
    assert media_file.s3_key_transcript is None


def test_provider_exception_is_swallowed_not_raised():
    from apps.api.tasks.transcription_tasks import transcribe_asset

    asset_id, version_id, asset, version, media_file = _entities()
    db = _mock_db(version, asset, media_file)

    with patch("apps.api.tasks.transcription_tasks.SessionLocal", return_value=db), \
         patch("apps.api.tasks.transcription_tasks.generate_presigned_get_url", return_value="https://example/presigned"), \
         patch("apps.api.tasks.transcription_tasks.transcribe_via_provider", side_effect=RuntimeError("provider blew up")):
        result = transcribe_asset.apply(args=(str(asset_id), str(version_id)))

    assert result.successful()
    assert media_file.s3_key_transcript is None


def test_returns_early_when_version_missing():
    from apps.api.tasks.transcription_tasks import transcribe_asset

    db = MagicMock()
    db.query.return_value = db
    db.filter.return_value = db
    db.first.return_value = None

    with patch("apps.api.tasks.transcription_tasks.SessionLocal", return_value=db), \
         patch("apps.api.tasks.transcription_tasks.transcribe_via_provider") as mock_transcribe:
        result = transcribe_asset.apply(args=(str(uuid.uuid4()), str(uuid.uuid4())))

    assert result.successful()
    mock_transcribe.assert_not_called()
