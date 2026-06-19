"""Скачивание видео (yt-dlp). Видео качается всегда.

Использование:  python download_video.py <URL> --out <DIR> [--extractor-args "youtube:player_client=android"]
--extractor-args можно указывать несколько раз; формат — как у одноимённой опции yt-dlp.
Полезно как обход, если yt-dlp ошибочно сообщает "video is not available" (баг
дефолтного web-клиента) — попробовать player_client=android.
Вывод: JSON {"video_path": ..., "title": ...}.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import subs as subs_mod


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", required=True, help="папка для сохранения")
    ap.add_argument("--extractor-args", dest="extractor_args", action="append", default=None)
    args = ap.parse_args(argv)

    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print(json.dumps({"error": "yt-dlp не установлен"}, ensure_ascii=False))
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, str] = {}

    def hook(d: dict) -> None:
        if d.get("status") == "finished":
            saved["path"] = d.get("filename", "")

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "outtmpl": str(out_dir / "%(title)s.%(ext)s"),
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "restrictfilenames": False,
        "progress_hooks": [hook],
    }
    if args.extractor_args:
        opts["extractor_args"] = subs_mod.parse_extractor_args(args.extractor_args)
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(args.url, download=True)
            path = ydl.prepare_filename(info)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"yt-dlp: {e}"}, ensure_ascii=False))
        return 1

    # после merge расширение может стать .mp4
    final = Path(path)
    if not final.exists():
        cand = final.with_suffix(".mp4")
        final = cand if cand.exists() else Path(saved.get("path", path))

    print(json.dumps(
        {"video_path": str(final), "title": info.get("title")},
        ensure_ascii=False, indent=2,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
