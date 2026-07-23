import time
from ..config import settings

_ASSEMBLYAI_BASE = "https://api.assemblyai.com/v2"
_POLL_INTERVAL_SECONDS = 3
_POLL_TIMEOUT_SECONDS = 1800  # 30 min ceiling


class TranscriptionError(Exception):
    pass


def transcribe_via_provider(audio_url: str) -> list[dict] | None:
    """Transcribe audio at `audio_url` (must be reachable by the provider,
    e.g. a presigned S3 URL) via the configured TRANSCRIPTION_PROVIDER.

    Returns a list of {text, start, end, speaker} word entries (start/end
    in SECONDS, matching this app's timecode convention; speaker is a
    provider-assigned label like "A"/"B" for diarization, or None if the
    provider couldn't attribute a speaker), or None if transcription is
    disabled (provider == "none"). Raises TranscriptionError on failure —
    callers should treat that as best-effort, never fatal to the encode.
    """
    provider = (settings.transcription_provider or "none").lower()
    if provider == "none":
        return None
    if provider == "assemblyai":
        return _transcribe_via_assemblyai(audio_url)
    raise TranscriptionError(f"Unknown transcription provider: {provider}")


def _transcribe_via_assemblyai(audio_url: str) -> list[dict]:
    import httpx

    if not settings.assemblyai_api_key:
        raise TranscriptionError("ASSEMBLYAI_API_KEY is not configured")

    headers = {"authorization": settings.assemblyai_api_key}
    with httpx.Client(timeout=30) as client:
        submit = client.post(
            f"{_ASSEMBLYAI_BASE}/transcript",
            headers=headers,
            json={"audio_url": audio_url, "speaker_labels": True},
        )
        submit.raise_for_status()
        transcript_id = submit.json()["id"]

        deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
        while True:
            poll = client.get(f"{_ASSEMBLYAI_BASE}/transcript/{transcript_id}", headers=headers)
            poll.raise_for_status()
            data = poll.json()
            poll_status = data.get("status")

            if poll_status == "completed":
                words = data.get("words") or []
                return [
                    {
                        "text": w["text"],
                        "start": w["start"] / 1000.0,
                        "end": w["end"] / 1000.0,
                        "speaker": w.get("speaker"),
                    }
                    for w in words
                ]
            if poll_status == "error":
                raise TranscriptionError(data.get("error") or "AssemblyAI transcription failed")
            if time.monotonic() > deadline:
                raise TranscriptionError("AssemblyAI transcription timed out")
            time.sleep(_POLL_INTERVAL_SECONDS)
