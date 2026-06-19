"""Разведка видео: метаданные + список доступных дорожек субтитров. Ничего не качает.

Использование:  python probe.py <URL> [--extractor-args "youtube:player_client=android"]
--extractor-args можно указывать несколько раз; формат — как у одноимённой опции yt-dlp.
Полезно как обход, если yt-dlp ошибочно сообщает "video is not available" (баг
дефолтного web-клиента) — попробовать player_client=android.
Вывод: JSON в stdout. Код возврата 0 при успехе, 1 при ошибке.
"""
from __future__ import annotations

import argparse
import json
import sys

import subs as subs_mod


def _tracks(d: dict) -> list[dict]:
    out = []
    for lang, variants in (d or {}).items():
        exts = sorted({v.get("ext", "") for v in variants if v.get("ext")})
        name = next((v.get("name") for v in variants if v.get("name")), lang)
        out.append({"lang": lang, "name": name, "exts": exts})
    out.sort(key=lambda x: x["lang"])
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--extractor-args", dest="extractor_args", action="append", default=None)
    args = ap.parse_args(argv)
    url = args.url
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print(json.dumps({"error": "yt-dlp не установлен"}, ensure_ascii=False))
        return 1

    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    if args.extractor_args:
        opts["extractor_args"] = subs_mod.parse_extractor_args(args.extractor_args)
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"yt-dlp: {e}"}, ensure_ascii=False))
        return 1

    result = {
        "id": info.get("id"),
        "extractor": info.get("extractor_key") or info.get("extractor"),
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
