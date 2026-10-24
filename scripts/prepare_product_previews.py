"""Encode labeled review drafts from actual product-browser recordings, offline."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-directory", required=True, type=Path)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--game-revision", required=True)
    parser.add_argument("--sky-revision", required=True)
    args = parser.parse_args(argv)
    capture, ffmpeg, output = (
        p.resolve(strict=True) for p in (args.capture_directory, args.ffmpeg, args.output_directory.parent)
    )
    output = output / args.output_directory.name
    if output.exists():
        parser.error("Choose a new output directory; prior assets are retained")
    evidence = json.loads((capture / "evidence.json").read_text(encoding="utf8"))
    if evidence.get("status") != "PASS":
        parser.error("Successful real product capture evidence is required")
    output.mkdir()
    records = []
    for product, title, revision, thumbnail in (
        ("game", "Game Platform", args.game_revision, "game-world-preview.png"),
        ("sky", "Sky Tablet", args.sky_revision, "sky-royal-game.png"),
    ):
        if not re.fullmatch(r"[a-f0-9]{40}", revision):
            parser.error("Supply exact owning source revisions")
        videos = sorted((capture / (product + "-recordings")).glob("*.webm"))
        if len(videos) != 1:
            parser.error("Exactly one real product recording is required")
        source = videos[0]
        label = output / (product + "-label.txt")
        note = (
            " | historical scene is an artistic interpretation"
            if product == "sky"
            else " | server-resolved combat and persisted state"
        )
        label.write_text(title + " | DRAFT | actual product capture" + note, encoding="utf8")
        for duration, purpose in ((60, "preview-montage"), (30, "technical-demo"), (15, "teaser")):
            target = output / f"{product}-{purpose}-{duration}s-draft.mp4"
            filters = (
                "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,"
                "drawbox=x=0:y=ih-80:w=iw:h=80:color=black@0.78:t=fill,"
                f"drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':textfile={label.name}:"
                "fontcolor=white:fontsize=18:x=24:y=h-th-28"
            )
            command = [
                str(ffmpeg),
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-stream_loop",
                "-1",
                "-i",
                str(source),
                "-t",
                str(duration),
                "-vf",
                filters,
                "-an",
                "-r",
                "24",
                "-c:v",
                "libx264",
                "-threads",
                "2",
                "-preset",
                "veryfast",
                "-crf",
                "24",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(target),
            ]
            process = subprocess.run(command, cwd=output, capture_output=True, text=True, timeout=180)
            if process.returncode:
                (output / "encoding-failure.log").write_text(process.stderr, encoding="utf8")
                raise RuntimeError("Video encoding failed; inspect preserved encoding-failure.log")
            decoded = subprocess.run(
                [str(ffmpeg), "-v", "error", "-nostdin", "-i", str(target), "-map", "0:v:0", "-f", "null", "-"],
                capture_output=True,
                timeout=120,
            )
            if decoded.returncode:
                raise RuntimeError("Encoded video failed complete decoding")
            meta = subprocess.run(
                [str(ffmpeg), "-hide_banner", "-i", str(target)], capture_output=True, text=True, timeout=15
            )
            found = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", meta.stderr)
            if not found:
                raise RuntimeError("Encoded duration unavailable")
            measured = int(found[1]) * 3600 + int(found[2]) * 60 + float(found[3])
            if abs(measured - duration) > 0.1:
                raise RuntimeError("Encoded duration differs from requested duration")
            captions = target.with_suffix(".vtt")
            captions.write_text(
                "WEBVTT\n\n00:00.000 --> 00:"
                + f"{duration // 60:02d}:{duration % 60:02d}.000"
                + "\n"
                + title
                + ". Actual product capture. Review draft. "
                + (
                    "Historical scene is an artistic interpretation, not an authentic artifact or an ephemeris."
                    if product == "sky"
                    else "This capture verifies guest access, server-resolved combat and persistence. It does not demonstrate an AI narration turn."
                )
                + "\n",
                encoding="utf8",
            )
            records.append(
                {
                    "product": product,
                    "path": target.name,
                    "purpose": purpose,
                    "duration_seconds": measured,
                    "bytes": target.stat().st_size,
                    "sha256": sha(target),
                    "codec": "H264",
                    "pixel_format": "yuv420p",
                    "resolution": [1280, 720],
                    "fps": 24,
                    "complete_decode": "PASS",
                    "audio": "NONE",
                    "captions": captions.name,
                    "captions_sha256": sha(captions),
                    "owning_source_revision": revision,
                    "input_capture_sha256": sha(source),
                    "scope": "edited actual capture; montage may repeat recorded material; no newly generated cinematic footage",
                }
            )
        for kind, name in (("homepage-poster", product + "-homepage-poster.png"), ("thumbnail", thumbnail)):
            original = capture / name
            target = output / (product + "-" + kind + ".png")
            shutil.copyfile(original, target)
            records.append(
                {
                    "product": product,
                    "path": target.name,
                    "purpose": kind,
                    "sha256": sha(target),
                    "source_capture_sha256": sha(original),
                    "edited": False,
                    "owning_source_revision": revision,
                }
            )
    manifest = {
        "schema": "orqevia.media-review.v1",
        "execution_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "DRAFT_REQUIRES_HUMAN_REVIEW",
        "capture_evidence_sha256": sha(capture / "evidence.json"),
        "ffmpeg_sha256": sha(ffmpeg),
        "assets": records,
        "new_paid_generation_calls": 0,
        "new_paid_generation_cost_usd": 0,
        "publication_approved": False,
        "cinematic_generation_completed": False,
        "required_review": [
            "visual pacing",
            "caption accuracy",
            "source attribution",
            "existing asset rights",
            "human approval",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf8")
    cards = []
    for item in records:
        if item["path"].endswith(".mp4"):
            cards.append(
                f'<article><h2>{item["product"]}: {item["purpose"]}</h2><video controls preload="metadata" width="640"><source src="{item["path"]}" type="video/mp4"><track kind="captions" srclang="en" label="English" default src="{item["captions"]}"></video></article>'
            )
    html = (
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Product preview review drafts</title><style>body{font:17px system-ui;background:#0b1120;color:#eee;margin:30px}video{max-width:100%;height:auto}article{margin-bottom:35px}a{color:#9df}</style><h1>Product preview review drafts</h1><p>Actual public product capture. No new paid generation. Human review and publication approval remain pending. The 60-second previews are edited capture montages; cinematic generation is not complete.</p>'
        + "".join(cards)
    )
    (output / "index.html").write_text(html, encoding="utf8")
    print(
        json.dumps(
            {
                "output_directory": str(output),
                "status": manifest["status"],
                "videos": 6,
                "images": 4,
                "complete_decode": "PASS",
                "new_paid_cost_usd": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
