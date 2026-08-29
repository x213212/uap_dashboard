#!/usr/bin/env python3
"""Create a source-traceable transcript with the local faster-whisper model."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from faster_whisper import BatchedInferencePipeline, WhisperModel


DEFAULT_MODEL = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"


@dataclass(frozen=True)
class TranscriptSegment:
    evidence_id: str
    source_id: str
    source_sha256: str
    start: float
    end: float
    text: str
    language: str
    engine: str
    model: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe a local audio/video file with faster-whisper."
    )
    parser.add_argument("media", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--language", default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--compute-type", default="int8_float16")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--beam-size", type=int, default=3)
    parser.add_argument(
        "--initial-prompt",
        default=(
            "David Icke interviews Credo Mutwa about Zulu traditions, Chitauri, "
            "Mantindane, extraterrestrials, UFOs, Africa, and the Illuminati."
        ),
    )
    parser.add_argument("--disable-vad", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe_media(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,format_name",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)["format"]
    return {
        "duration_seconds": float(payload["duration"]),
        "size_bytes": int(payload["size"]),
        "format_name": payload.get("format_name", ""),
    }


def compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def format_clock(seconds: float, separator: str = ".") -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def write_human_outputs(
    output_dir: Path,
    segments: list[TranscriptSegment],
    language: str,
) -> dict[str, str]:
    stem = f"transcript.{language}"
    transcript = "\n".join(
        f"[{format_clock(segment.start)[:8]}] {segment.text}" for segment in segments
    )
    text_name = f"{stem}.txt"
    srt_name = f"{stem}.srt"
    vtt_name = f"{stem}.vtt"
    (output_dir / text_name).write_text(transcript + "\n", encoding="utf-8")

    srt_blocks = []
    for index, segment in enumerate(segments, 1):
        srt_blocks.append(
            f"{index}\n{format_clock(segment.start, ',')} --> "
            f"{format_clock(segment.end, ',')}\n{segment.text}"
        )
    (output_dir / srt_name).write_text(
        "\n\n".join(srt_blocks) + "\n", encoding="utf-8"
    )

    vtt_blocks = ["WEBVTT", ""]
    for segment in segments:
        vtt_blocks.extend(
            [
                f"{format_clock(segment.start)} --> {format_clock(segment.end)}",
                segment.text,
                "",
            ]
        )
    (output_dir / vtt_name).write_text(
        "\n".join(vtt_blocks), encoding="utf-8"
    )
    return {"plain_text": text_name, "srt": srt_name, "vtt": vtt_name}


def main() -> int:
    args = parse_args()
    if not args.media.is_file():
        raise FileNotFoundError(args.media)
    if args.batch_size < 1 or args.beam_size < 1:
        raise ValueError("batch size and beam size must be positive")

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_partial = output_dir / "raw.jsonl.partial"
    normalized_partial = output_dir / "normalized.jsonl.partial"
    raw_final = output_dir / "raw.jsonl"
    normalized_final = output_dir / "normalized.jsonl"
    completed_outputs = [raw_final, normalized_final, output_dir / "metadata.json"]
    existing_outputs = [path for path in completed_outputs if path.exists()]
    if existing_outputs:
        joined = ", ".join(str(path) for path in existing_outputs)
        raise FileExistsError(
            f"refusing to overwrite completed ASR evidence: {joined}"
        )

    media_info = probe_media(args.media)
    source_sha256 = sha256_file(args.media)
    model_started = time.perf_counter()
    model = WhisperModel(
        args.model,
        device=args.device,
        compute_type=args.compute_type,
    )
    recognizer = model if args.disable_vad else BatchedInferencePipeline(model=model)
    model_load_seconds = time.perf_counter() - model_started

    transcribe_started = time.perf_counter()
    transcribe_options = {
        "language": args.language,
        "task": "transcribe",
        "beam_size": args.beam_size,
        "best_of": 1,
        "temperature": 0.0,
        "repetition_penalty": 1.1,
        "no_repeat_ngram_size": 3,
        "condition_on_previous_text": False,
        "initial_prompt": args.initial_prompt,
        "word_timestamps": args.disable_vad,
        "vad_filter": not args.disable_vad,
        "log_progress": True,
    }
    if args.disable_vad:
        engine = "faster-whisper/WhisperModel"
    else:
        engine = "faster-whisper/BatchedInferencePipeline"
        transcribe_options.update(
            {
                "without_timestamps": True,
                "vad_parameters": {
                    "threshold": 0.5,
                    "min_speech_duration_ms": 250,
                    "min_silence_duration_ms": 500,
                    "speech_pad_ms": 200,
                },
                "batch_size": args.batch_size,
            }
        )
    stream, info = recognizer.transcribe(str(args.media), **transcribe_options)
    segments: list[TranscriptSegment] = []
    with raw_partial.open("w", encoding="utf-8", buffering=1) as raw_handle, \
        normalized_partial.open("w", encoding="utf-8", buffering=1) as normalized_handle:
        for index, item in enumerate(stream, 1):
            text = compact_text(item.text)
            if not text:
                continue
            segment = TranscriptSegment(
                evidence_id=f"{args.source_id}:{index:06d}",
                source_id=args.source_id,
                source_sha256=source_sha256,
                start=round(float(item.start), 3),
                end=round(float(item.end), 3),
                text=text,
                language=info.language,
                engine=engine,
                model=args.model,
            )
            segments.append(segment)
            raw_handle.write(json.dumps(asdict(segment), ensure_ascii=False) + "\n")
            normalized = {
                **asdict(segment),
                "normalization": {
                    "method": "identity",
                    "corrections": [],
                    "raw_evidence_id": segment.evidence_id,
                },
            }
            normalized_handle.write(json.dumps(normalized, ensure_ascii=False) + "\n")

    raw_partial.replace(raw_final)
    normalized_partial.replace(normalized_final)
    human_artifacts = write_human_outputs(output_dir, segments, info.language)

    elapsed = time.perf_counter() - transcribe_started
    metadata = {
        "source_id": args.source_id,
        "title": args.title,
        "url": args.url,
        "source_sha256": source_sha256,
        "source_media_retained": False,
        "media": media_info,
        "transcription": {
            "engine": engine,
            "model": args.model,
            "device": args.device,
            "compute_type": args.compute_type,
            "batch_size": args.batch_size,
            "beam_size": args.beam_size,
            "language": info.language,
            "language_probability": round(float(info.language_probability), 6),
            "duration_after_vad_seconds": round(float(info.duration_after_vad), 3),
            "segment_count": len(segments),
            "model_load_seconds": round(model_load_seconds, 3),
            "transcription_seconds": round(elapsed, 3),
            "realtime_factor": round(elapsed / max(media_info["duration_seconds"], 1), 6),
        },
        "artifacts": {
            "raw_jsonl": "raw.jsonl",
            "normalized_jsonl": "normalized.jsonl",
            **human_artifacts,
        },
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
