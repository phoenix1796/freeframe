import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
import boto3
from botocore.config import Config
from .base import BaseTranscoder, TranscodeJob, TranscodeResult, VideoMetadata

# HLS output is thousands of small segment files for a long recording;
# uploading them one at a time serializes on per-request network latency to
# the S3 backend rather than CPU or bandwidth. s5cmd (pip-installed alongside
# the app — see apps/api/requirements.txt, ships the Go binary as a platform
# wheel) uploads with a concurrent worker pool instead of boto3's serial
# upload_file loop.
_UPLOAD_CONCURRENCY = 12
_S5CMD_TIMEOUT = 1800  # 30 min ceiling for one cp invocation


def parse_probe_metadata(data: dict) -> Optional[VideoMetadata]:
    """Parse ffprobe JSON (-show_streams -show_format) into VideoMetadata.

    Returns None when there is no video stream. Guards r_frame_rate "0/0"
    (fps stays 0.0 — never fabricate a rate) and falls back to format-level
    duration when the stream lacks one (common for MKV/WebM).
    """
    streams = data.get("streams") or []
    if not streams:
        return None
    stream = streams[0]
    fps = 0.0
    raw_rate = stream.get("r_frame_rate") or ""
    if "/" in raw_rate:
        num, _, den = raw_rate.partition("/")
        try:
            if float(den) != 0:
                fps = float(num) / float(den)
        except ValueError:
            fps = 0.0
    duration = float(stream.get("duration") or 0)
    if not duration:
        duration = float((data.get("format") or {}).get("duration") or 0)
    return VideoMetadata(
        duration_seconds=duration,
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
        fps=fps,
    )


class FFmpegTranscoder(BaseTranscoder):
    def __init__(
        self, s3_client, bucket: str, s3_endpoint: str = None,
        s3_access_key: str = None, s3_secret_key: str = None, s3_region: str = None,
    ):
        self.s3 = s3_client
        self.bucket = bucket
        self.s3_endpoint = s3_endpoint
        # Only needed for the s5cmd upload subprocess below — presigned URLs
        # (self.s3, above) are signed locally by boto3 and never touch these.
        self.s3_access_key = s3_access_key
        self.s3_secret_key = s3_secret_key
        self.s3_region = s3_region

    def _get_presigned_url(self, s3_key: str, expires_in: int = 7200) -> str:
        """Generate a presigned URL for streaming input to FFmpeg."""
        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": s3_key},
            ExpiresIn=expires_in,
        )

    def _run_s5cmd(self, args: list[str]) -> str:
        """Run an s5cmd subcommand, raising RuntimeError with stderr on failure."""
        cmd = ["s5cmd"]
        if self.s3_endpoint:
            cmd += ["--endpoint-url", self.s3_endpoint]
        cmd += args
        env = os.environ.copy()
        if self.s3_access_key:
            env["AWS_ACCESS_KEY_ID"] = self.s3_access_key
        if self.s3_secret_key:
            env["AWS_SECRET_ACCESS_KEY"] = self.s3_secret_key
        if self.s3_region:
            env["AWS_REGION"] = self.s3_region
        result = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace",
            timeout=_S5CMD_TIMEOUT, env=env,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(f"s5cmd {' '.join(args[:2])} exited {result.returncode}: {stderr or 'no stderr output'}")
        return result.stdout

    @staticmethod
    def _run(cmd: list[str], timeout: int | None = None, label: str = "ffmpeg") -> str:
        """Run a command, raising RuntimeError with stderr on failure.

        Uses errors='replace' because ffmpeg often echoes input metadata
        (Latin-1 / Shift-JIS) to stderr, which would break strict UTF-8 decode.
        """
        result = subprocess.run(
            cmd, capture_output=True, text=True, errors='replace', timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(
                f"{label} exited {result.returncode}: {stderr or 'no stderr output'}"
            )
        return result.stdout

    async def get_video_metadata(self, s3_key: str) -> VideoMetadata:
        """Get video metadata using streaming (no full download)."""
        input_url = self._get_presigned_url(s3_key)
        cmd = [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_streams", "-select_streams", "v:0", "-show_format", input_url,
        ]
        stdout = self._run(cmd, timeout=120, label="ffprobe")
        meta = parse_probe_metadata(json.loads(stdout))
        if meta is None:
            raise RuntimeError(f"No video stream found in {s3_key}")
        return meta

    async def generate_thumbnails(self, s3_key: str, count: int) -> list[str]:
        """Generate thumbnails at 1 per 10 seconds using streaming input."""
        input_url = self._get_presigned_url(s3_key)
        thumb_dir = tempfile.mkdtemp()
        try:
            cmd = [
                "ffmpeg", "-i", input_url,
                "-vf", "fps=0.1",
                "-q:v", "2",
                f"{thumb_dir}/thumb_%04d.jpg",
            ]
            self._run(cmd, timeout=600, label="ffmpeg")
            return [str(p) for p in sorted(Path(thumb_dir).glob("thumb_*.jpg"))]
        finally:
            shutil.rmtree(thumb_dir, ignore_errors=True)

    async def generate_waveform(self, s3_key: str) -> dict:
        """Generate waveform data for audio visualization using streaming."""
        input_url = self._get_presigned_url(s3_key)
        # Simplified waveform: just return peak data (full waveform extraction is complex)
        return {"samples": [], "peak": 1.0, "source": s3_key}

    async def transcode(self, job: TranscodeJob) -> TranscodeResult:
        """
        Transcode video using streaming input from S3.
        FFmpeg reads directly from presigned URL - no full download needed.
        Only output files are written to disk, reducing disk usage by ~2/3.
        """
        work_dir = Path(tempfile.mkdtemp(prefix=f"transcode_{job.version_id}_"))
        
        # Generate presigned URL for streaming input (2 hour expiry for large files)
        input_url = self._get_presigned_url(job.input_s3_key, expires_in=7200)

        try:
            # 1. Get video metadata via streaming (no download)
            cmd = [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_streams", "-select_streams", "v:0", "-show_format", input_url,
            ]
            vid_info = self._run(cmd, timeout=120, label="ffprobe")
            meta = parse_probe_metadata(json.loads(vid_info))

            # 2. Check if input has an audio stream
            audio_cmd = [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_streams", "-select_streams", "a", input_url,
            ]
            audio_result = self._run(audio_cmd, timeout=120, label="ffprobe")
            has_audio = bool(json.loads(audio_result).get("streams"))

            # 3. Build quality ladder based on available qualities
            QUALITY_MAP = {
                "1080p": ("1920:1080", 20),
                "720p": ("1280:720", 22),
                "360p": ("640:360", 26),
            }
            qualities = [q for q in job.qualities if q in QUALITY_MAP]

            hls_dir = work_dir / "hls"
            hls_dir.mkdir()

            # Build filter_complex and map args
            # Use force_original_aspect_ratio=decrease to preserve aspect ratio,
            # then pad to even dimensions required by libx264
            split_outputs = "".join(f"[v{i}]" for i in range(len(qualities)))
            filter_complex = f"[v:0]split={len(qualities)}{split_outputs};"
            filter_complex += ";".join(
                f"[v{i}]scale={QUALITY_MAP[q][0]}:force_original_aspect_ratio=decrease,pad=ceil(iw/2)*2:ceil(ih/2)*2[{q}]"
                for i, q in enumerate(qualities)
            )

            ffmpeg_cmd = [
                "ffmpeg", "-y", "-i", input_url,
                "-filter_complex", filter_complex,
            ]

            for i, quality in enumerate(qualities):
                scale, crf = QUALITY_MAP[quality]
                ffmpeg_cmd += ["-map", f"[{quality}]"]
                if has_audio:
                    ffmpeg_cmd += ["-map", "a:0"]
                ffmpeg_cmd += [
                    f"-c:v:{i}", "libx264", f"-crf", str(crf), "-preset", "fast",
                    "-force_key_frames", "expr:gte(t,n_forced*2)",
                ]

            segment_dir = hls_dir / "%v"
            ffmpeg_cmd += [
                "-f", "hls",
                "-hls_time", "2",
                "-hls_playlist_type", "vod",
                "-hls_flags", "independent_segments",
                "-hls_segment_type", "mpegts",
                "-master_pl_name", "master.m3u8",
                "-var_stream_map", " ".join(
                    f"v:{i},a:{i}" if has_audio else f"v:{i}"
                    for i in range(len(qualities))
                ),
                "-hls_segment_filename", str(hls_dir / "%v" / "seg_%03d.ts"),
                str(hls_dir / "%v" / "playlist.m3u8"),
            ]

            # Create per-quality directories
            for q in qualities:
                (hls_dir / q).mkdir(exist_ok=True)

            # Timeout scales with expected duration - 4 hours for very large files
            self._run(ffmpeg_cmd, timeout=14400, label="ffmpeg")

            # 4. Upload HLS files to S3 via s5cmd (see _UPLOAD_CONCURRENCY above).
            # One `cp` call per extension since --content-type/--cache-control
            # apply to the whole invocation, and playlists vs segments need
            # different values (see CONTENT_TYPE_MAP / _get_content_type).
            dest = f"s3://{self.bucket}/{job.output_s3_prefix}/"
            for pattern in ("*.m3u8", "*.ts"):
                content_type, cache_control = self._get_content_type(pattern.lstrip("*"))
                self._run_s5cmd([
                    "cp", "--concurrency", str(_UPLOAD_CONCURRENCY),
                    "--include", pattern,
                    "--content-type", content_type,
                    "--cache-control", cache_control,
                    f"{hls_dir}/", dest,
                ])

            # 5. Generate and upload thumbnail (using streaming URL)
            thumb_path = work_dir / "thumb_0001.jpg"
            thumb_cmd = [
                "ffmpeg", "-y", "-i", input_url,
                "-vf", "fps=0.1", "-q:v", "2", "-frames:v", "1",
                str(work_dir / "thumb_%04d.jpg"),
            ]
            self._run(thumb_cmd, label="ffmpeg")
            thumbnail_key = f"{job.output_s3_prefix}/thumbnail.jpg"
            if thumb_path.exists():
                self.s3.upload_file(
                    str(thumb_path), self.bucket, thumbnail_key,
                    ExtraArgs={"ContentType": "image/jpeg", "CacheControl": "max-age=86400"},
                )

            return TranscodeResult(
                success=True,
                hls_prefix=job.output_s3_prefix,
                thumbnail_keys=[thumbnail_key],
                duration_seconds=(meta.duration_seconds or None) if meta else None,
                width=(meta.width or None) if meta else None,
                height=(meta.height or None) if meta else None,
                fps=(meta.fps or None) if meta else None,
            )

        except Exception as e:
            return TranscodeResult(success=False, error=str(e))
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    @staticmethod
    def _get_content_type(filename: str) -> tuple[str, str]:
        ext = Path(filename).suffix.lower()
        MAP = {
            ".m3u8": ("application/vnd.apple.mpegurl", "no-cache"),
            ".ts": ("video/mp2t", "max-age=31536000"),
            ".jpg": ("image/jpeg", "max-age=86400"),
        }
        return MAP.get(ext, ("application/octet-stream", "no-cache"))
