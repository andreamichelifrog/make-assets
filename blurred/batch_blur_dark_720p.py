#!/usr/bin/env python3

import argparse
import os
import shlex
import subprocess
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi"}


def build_filter(*, sigma: int, steps: int, dark: float, fade_end: float) -> str:
    # fade_end is fraction of height where effects fade to zero (e.g. 0.5 = mid-screen)
    # t = clip((Y - H*fade_end) / (H*(1-fade_end)), 0, 1)
    # At Y<=H*fade_end -> t=0 (no blur/dark). At Y=H -> t=1 (full blur/dark).
    denom = f"(H*(1-{fade_end}))"
    t = f"clip((Y-H*{fade_end})/{denom},0,1)"

    # 1) Scale down to fit within 1280x720 while keeping aspect ratio (no padding).
    # 2) Blur a copy, then blend blurred/original with vertical gradient.
    # 3) Create black overlay with alpha gradient using geq, then overlay.
    return (
        "[0:v]"
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "scale=trunc(iw/2)*2:trunc(ih/2)*2,"
        "setsar=1,"
        "split=2[base][b];"
        f"[b]gblur=sigma={sigma}:steps={steps}[blur];"
        f"[base][blur]blend=all_expr='A*(1-{t}) + B*({t})'[v1];"
        "[v1]format=yuva444p[ref];"
        "color=c=black@1:s=16x16,format=yuva444p[ov];"
        "[ov][ref]scale2ref[ovr][ref2];"
        f"[ovr]geq=lum=0:cb=128:cr=128:a='255*{dark}*{t}'[ovm];"
        "[ref2][ovm]overlay=shortest=1:eof_action=pass:format=auto[v]"
    )


def run_ffmpeg(
    *,
    input_path: Path,
    output_path: Path,
    sigma: int,
    steps: int,
    dark: float,
    fade_end: float,
    crf: int,
    preset: str,
    audio_bitrate: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    filter_complex = build_filter(sigma=sigma, steps=steps, dark=dark, fade_end=fade_end)

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-shortest",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        str(output_path),
    ]

    print(f"\n==> {input_path.name} -> {output_path.name}")
    print(" ".join(shlex.quote(c) for c in cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Batch apply bottom blur (fading to none) + dark overlay (fading to transparent) and export 720p H.264."
    )
    p.add_argument(
        "--dir",
        default=".",
        help="Folder containing videos (default: current directory)",
    )
    p.add_argument(
        "--out",
        default="out",
        help="Output folder (relative to --dir unless absolute). Default: out",
    )
    p.add_argument("--sigma", type=int, default=70, help="Gaussian blur strength. Typical 70-110 for 1254x704")
    p.add_argument("--steps", type=int, default=3, help="Blur steps (higher = smoother but slower)")
    p.add_argument("--dark", type=float, default=0.60, help="Dark overlay intensity at bottom (0..1)")
    p.add_argument(
        "--fade-end",
        type=float,
        default=0.50,
        help="Where effects fade to zero as fraction of height (0.5=mid-screen)",
    )
    p.add_argument("--crf", type=int, default=30, help="x264 CRF (higher = smaller/less detail). Try 28-32")
    p.add_argument("--preset", default="slow", help="x264 preset (slower = smaller). e.g. slow, medium")
    p.add_argument("--audio-bitrate", default="80k", help="AAC audio bitrate, e.g. 80k")
    args = p.parse_args()

    in_dir = Path(args.dir).expanduser().resolve()
    out_dir = Path(args.out).expanduser()
    if not out_dir.is_absolute():
        out_dir = (in_dir / out_dir).resolve()

    if not in_dir.exists() or not in_dir.is_dir():
        raise SystemExit(f"Input dir not found: {in_dir}")

    # Collect videos in top-level of folder (non-recursive). Change to rglob if needed.
    videos = [p for p in in_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    videos.sort(key=lambda x: x.name.lower())

    if not videos:
        print(f"No videos found in {in_dir}")
        return 0

    # Avoid accidentally re-processing outputs.
    videos = [v for v in videos if v.parent != out_dir]

    for src in videos:
        dst = out_dir / f"{src.stem}_blur720.mp4"
        try:
            run_ffmpeg(
                input_path=src,
                output_path=dst,
                sigma=args.sigma,
                steps=args.steps,
                dark=args.dark,
                fade_end=args.fade_end,
                crf=args.crf,
                preset=args.preset,
                audio_bitrate=args.audio_bitrate,
            )
        except subprocess.CalledProcessError as e:
            print(f"ERROR processing {src}: ffmpeg exited with {e.returncode}")

    print(f"\nDone. Outputs in: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
