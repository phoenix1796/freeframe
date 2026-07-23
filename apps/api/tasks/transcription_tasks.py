import json
import logging
import uuid

from .celery_app import celery_app
from ..database import SessionLocal
from ..models.asset import Asset, AssetVersion, MediaFile
from ..services.s3_service import generate_presigned_get_url, put_object
from ..services.transcription_service import transcribe_via_provider

log = logging.getLogger("celery.transcription")

_NOT_CONFIGURED_MESSAGE = "Transcription isn't set up for this instance yet."


@celery_app.task
def transcribe_asset(asset_id: str, version_id: str):
    """Generate a transcript for a version, independent of encoding.

    Dispatched alongside (not nested inside) process_asset, on the
    lightweight `default` queue rather than `transcoding` — this is
    I/O-bound (waiting on the provider's API), not CPU-bound, so it
    shouldn't compete with encode jobs for transcoding-queue concurrency.
    Never touches processing_status or blocks the video/audio from
    becoming ready — but DOES record failures on MediaFile.transcript_error
    so the frontend can show a real error instead of polling forever.
    """
    db = SessionLocal()
    try:
        version = db.query(AssetVersion).filter(AssetVersion.id == uuid.UUID(version_id)).first()
        if not version:
            return

        asset = db.query(Asset).filter(Asset.id == uuid.UUID(asset_id)).first()
        media_file = db.query(MediaFile).filter(MediaFile.version_id == version.id).first()
        if not asset or not media_file:
            return

        # Clear any previous error up front — a retry shouldn't show a stale
        # failure message while a fresh attempt is in progress.
        media_file.transcript_error = None
        db.commit()

        try:
            audio_url = generate_presigned_get_url(media_file.s3_key_raw, expires_in=7200)
            words = transcribe_via_provider(audio_url)
            if words is None:
                _fail(db, media_file, asset, version_id, _NOT_CONFIGURED_MESSAGE)
                return

            output_prefix = f"processed/{asset.project_id}/{asset_id}/{version_id}"
            transcript_key = f"{output_prefix}/transcript.json"
            put_object(
                transcript_key,
                json.dumps({"words": words}).encode("utf-8"),
                content_type="application/json",
                cache_control="max-age=31536000",
            )
            media_file.s3_key_transcript = transcript_key
            db.commit()

            _publish_event(str(asset.project_id), "transcript_complete", {
                "asset_id": asset_id,
                "version_id": version_id,
            })

        except Exception as exc:
            log.warning("transcription failed for version %s: %s", version_id, exc)
            _fail(db, media_file, asset, version_id, str(exc) or "Transcription failed.")

    finally:
        db.close()


def _fail(db, media_file: MediaFile, asset: Asset, version_id: str, message: str):
    media_file.transcript_error = message[:500]
    db.commit()
    _publish_event(str(asset.project_id), "transcript_failed", {
        "asset_id": str(asset.id),
        "version_id": version_id,
        "error": media_file.transcript_error,
    })


def _publish_event(project_id: str, event_type: str, payload: dict):
    """Publish SSE event via Redis from Celery worker context. Best-effort,
    same pattern as tasks/transcode_tasks.py."""
    try:
        import redis as sync_redis
        from ..config import settings
        r = sync_redis.from_url(settings.redis_url, decode_responses=True)
        message = json.dumps({"type": event_type, "payload": payload})
        r.publish(f"project:{project_id}", message)
        r.close()
    except Exception:
        pass
