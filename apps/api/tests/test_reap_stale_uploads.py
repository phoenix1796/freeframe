"""Tests for the stale-upload reaper and its S3 helpers."""
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from apps.api.services import s3_service


def _fake_s5cmd_run(returncode=0, stdout="", stderr=""):
    """A subprocess.run stand-in that records every invocation's argv."""
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        mock = MagicMock()
        mock.returncode = returncode
        mock.stdout = stdout
        mock.stderr = stderr
        return mock

    run.calls = calls
    return run


def test_list_stale_multipart_uploads_filters_by_initiated(monkeypatch):
    now = datetime.now(timezone.utc)
    fake = MagicMock()
    fake.list_multipart_uploads.return_value = {
        "Uploads": [
            {"Key": "raw/old", "UploadId": "u1", "Initiated": now - timedelta(hours=48)},
            {"Key": "raw/new", "UploadId": "u2", "Initiated": now - timedelta(hours=1)},
        ],
        "IsTruncated": False,
    }
    monkeypatch.setattr(s3_service, "get_s3_client", lambda: fake)
    result = s3_service.list_stale_multipart_uploads(now - timedelta(hours=24))
    assert result == [("raw/old", "u1")]


def test_delete_prefix_deletes_all_listed(monkeypatch):
    """delete_prefix shells out to `s5cmd rm` against the prefix wildcard (see
    perf(s3) commit) instead of boto3's list+batch-delete."""
    fake_run = _fake_s5cmd_run(returncode=0, stdout="")
    monkeypatch.setattr(s3_service.subprocess, "run", fake_run)
    s3_service.delete_prefix("p/")
    assert len(fake_run.calls) == 1
    cmd = fake_run.calls[0]
    assert cmd[0] == "s5cmd"
    assert cmd[-2] == "rm"
    assert cmd[-1] == f"s3://{s3_service.settings.s3_bucket}/p/*"


def test_delete_prefix_noop_when_empty(monkeypatch):
    """s5cmd exits 1 with "no object found" on a prefix matching nothing —
    delete_prefix must swallow that as a no-op, not raise (allow_no_match)."""
    fake_run = _fake_s5cmd_run(
        returncode=1, stderr='ERROR "rm s3://freeframe-test/p/*": no object found',
    )
    monkeypatch.setattr(s3_service.subprocess, "run", fake_run)
    s3_service.delete_prefix("p/")  # must not raise
    assert len(fake_run.calls) == 1


def test_list_keys_yields_key_last_modified_size(monkeypatch):
    """list_keys parses s5cmd's --json ls output into (key, last_modified, size)
    tuples, stripping the s3://bucket/ prefix back to a bare key."""
    bucket = s3_service.settings.s3_bucket
    ndjson = "\n".join([
        json.dumps({
            "key": f"s3://{bucket}/raw/a.mp4", "type": "file",
            "last_modified": "2026-07-23T02:05:15.656Z", "size": 289092060,
        }),
        json.dumps({
            "key": f"s3://{bucket}/raw/sub/", "type": "dir",
            "last_modified": "2026-07-23T02:05:15.656Z", "size": 0,
        }),
    ])
    fake_run = _fake_s5cmd_run(returncode=0, stdout=ndjson)
    monkeypatch.setattr(s3_service.subprocess, "run", fake_run)

    result = list(s3_service.list_keys("raw/"))

    assert len(result) == 1  # the "dir" entry is skipped, only files yielded
    key, last_modified, size = result[0]
    assert key == "raw/a.mp4"
    assert size == 289092060
    assert last_modified == datetime(2026, 7, 23, 2, 5, 15, 656000, tzinfo=timezone.utc)


def test_list_keys_empty_when_no_match(monkeypatch):
    fake_run = _fake_s5cmd_run(
        returncode=1, stderr='ERROR "ls s3://freeframe-test/raw/*": no object found',
    )
    monkeypatch.setattr(s3_service.subprocess, "run", fake_run)
    assert list(s3_service.list_keys("raw/")) == []


import uuid
import apps.api.tasks.cleanup_tasks as ct
from apps.api.models.user import User
from apps.api.models.project import Project, ProjectType
from apps.api.models.asset import (
    Asset, AssetType, AssetVersion, MediaFile, FileType, ProcessingStatus,
)


def test_reap_logic_soft_deletes_and_deletes_s3(mock_db, monkeypatch):
    """Unit: with one stale version + its media file, the reaper soft-deletes the version
    and issues best-effort S3 deletes."""
    monkeypatch.setattr(ct, "list_stale_multipart_uploads", lambda cutoff: [])
    deleted = []
    monkeypatch.setattr(ct, "delete_object", lambda k: deleted.append(k))
    monkeypatch.setattr(ct, "delete_prefix", lambda k: deleted.append(k))

    version = MagicMock(deleted_at=None)
    media = MagicMock(s3_key_raw="raw/x", s3_key_processed="processed/x", s3_key_thumbnail="thumb/x")
    # versions query returns [version]; media-files query (inside the loop) returns [media]
    mock_db.all.side_effect = [[version], [media]]

    n = ct._reap_stale_uploads(mock_db)

    assert n == 1
    assert version.deleted_at is not None
    assert set(deleted) == {"raw/x", "processed/x", "thumb/x"}


def _seed_version(db, status, created_shift_hours):
    owner = User(email=f"reap-{uuid.uuid4()}@t.local", name="t")
    db.add(owner); db.flush()
    project = Project(name="t", project_type=ProjectType.personal, created_by=owner.id)
    db.add(project); db.flush()
    asset = Asset(project_id=project.id, name="t", asset_type=AssetType.video, created_by=owner.id)
    db.add(asset); db.flush()
    v = AssetVersion(asset_id=asset.id, version_number=1, processing_status=status, created_by=owner.id)
    db.add(v); db.flush()
    # created_at is server-defaulted to now(); force it into the past when needed
    v.created_at = datetime.now(timezone.utc) - timedelta(hours=created_shift_hours)
    db.add(MediaFile(version_id=v.id, file_type=FileType.video, original_filename="f.mp4",
                     mime_type="video/mp4", file_size_bytes=1, s3_key_raw=f"raw/{v.id}"))
    db.flush()
    return v


def test_reap_selects_only_old_uploading_and_failed(real_db, monkeypatch):
    """Real DB: only old `uploading`/`failed` versions are soft-deleted; recent + ready are not."""
    monkeypatch.setattr(ct, "list_stale_multipart_uploads", lambda cutoff: [])
    monkeypatch.setattr(ct, "delete_object", lambda k: None)
    monkeypatch.setattr(ct, "delete_prefix", lambda k: None)

    old_uploading = _seed_version(real_db, ProcessingStatus.uploading, 48)
    old_failed = _seed_version(real_db, ProcessingStatus.failed, 48)
    recent_uploading = _seed_version(real_db, ProcessingStatus.uploading, 1)
    ready = _seed_version(real_db, ProcessingStatus.ready, 48)

    ct._reap_stale_uploads(real_db)

    assert old_uploading.deleted_at is not None
    assert old_failed.deleted_at is not None
    assert recent_uploading.deleted_at is None
    assert ready.deleted_at is None


def test_reaper_disabled_when_timeout_zero(mock_db, monkeypatch):
    """timeout <= 0 disables the reaper — it must not list multiparts or query/soft-delete anything."""
    from apps.api.config import settings
    monkeypatch.setattr(settings, "stale_upload_timeout_hours", 0)
    listed = []
    monkeypatch.setattr(ct, "list_stale_multipart_uploads", lambda cutoff: listed.append(cutoff) or [])

    assert ct._reap_stale_uploads(mock_db) == 0
    assert listed == []                 # never computed a cutoff / listed multiparts
    mock_db.query.assert_not_called()   # never selected any versions
