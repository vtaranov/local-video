"""Скачивание выбранных дорожек субтитров (yt-dlp) и нормализация в .vtt.

Использование:
  python fetch_subs.py <URL> --langs en,es --out <DIR> [--auto]
--auto разрешает авто-сгенерированные субтитры (если ручных нет).
Вывод: JSON {"files": [{"lang":..., "path":...}, ...]}.
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
    ap.add_argument("--langs", required=True, help="коды языков через запятую")
    ap.add_argument("--out", required=True)
    ap.add_argument("--auto", action="store_true", help="разрешить авто-субтитры")
    args = ap.parse_args(argv)

    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print(json.dumps({"error": "yt-dlp не установлен"}, ensure_ascii=False))
        return 1

    langs = [s.strip() for s in args.langs.split(",") if s.strip()]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": args.auto,
        "subtitleslangs": langs,
        "subtitlesformat": "vtt",
        "outtmpl": str(out_dir / "%(title)s.%(ext)s"),
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(args.url, download=True)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"yt-dlp: {e}"}, ensure_ascii=False))
        return 1

    requested = ydl.prepare_filename(info)
    stem = Path(requested).with_suffix("")
    files = []
    for lang in langs:
        # yt-dlp пишет <stem>.<lang>.vtt
        cand = Path(f"{stem}.{lang}.vtt")
        if not cand.exists():
            matches = list(out_dir.glob(f"*.{lang}.vtt"))
            cand = matches[0] if matches else None
        if cand and cand.exists():
            # нормализуем через наш парсер -> чистый .vtt
            segs = subs_mod.parse_file(cand)
            subs_mod.write_vtt(segs, cand)
            files.append({"lang": lang, "path": str(cand)})

    if not files:
        print(json.dumps(
            {"error": "Субтитры не скачаны (нет запрошенных дорожек)", "files": []},
            ensure_ascii=False,
        ))
        return 1

    print(json.dumps({"files": files}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
