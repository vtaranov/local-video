"""Разведка видео: метаданные + список доступных дорожек субтитров. Ничего не качает.

Использование:  python probe.py <URL>
Вывод: JSON в stdout. Код возврата 0 при успехе, 1 при ошибке.
"""
from __future__ import annotations

import json
import sys


def _tracks(d: dict) -> list[dict]:
    out = []
    for lang, variants in (d or {}).items():
        exts = sorted({v.get("ext", "") for v in variants if v.get("ext")})
        name = next((v.get("name") for v in variants if v.get("name")), lang)
        out.append({"lang": lang, "name": name, "exts": exts})
    out.sort(key=lambda x: x["lang"])
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(json.dumps({"error": "Ожидается ровно один аргумент: URL"}, ensure_ascii=False))
        return 1
    url = argv[0]
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print(json.dumps({"error": "yt-dlp не установлен"}, ensure_ascii=False))
        return 1

    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"yt-dlp: {e}"}, ensure_ascii=False))
        return 1

    result = {
        "title": info.get("title"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
        "url": info.get("webpage_url", url),
        "manual_subs": _tracks(info.get("subtitles")),
        "auto_subs": _tracks(info.get("automatic_captions")),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
