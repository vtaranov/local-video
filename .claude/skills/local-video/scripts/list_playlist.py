"""Перечисление видео плейлиста/канала без скачивания (yt-dlp, flat).

Использование:
  python list_playlist.py "<PLAYLIST_URL>" [--limit N] [--cookies-from-browser chrome] [--cookies FILE]
--limit N        вернуть только первые N элементов (для «последних N» в плейлисте).
--cookies-from-browser / --cookies  доступ к приватному плейлисту (см. subs.add_cookie_args).
Вывод: JSON {"playlist": <название>, "count": N, "entries": [{id, title, url}, ...]}.
Если URL — одиночное видео, вернёт один элемент.
"""
from __future__ import annotations

import argparse
import json
import sys

import subs as subs_mod


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--limit", type=int, default=None, help="вернуть только первые N элементов")
    subs_mod.add_cookie_args(ap)
    args = ap.parse_args(argv)
    url = args.url
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print(json.dumps({"error": "yt-dlp не установлен"}, ensure_ascii=False))
        return 1

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",  # не лезть в каждое видео — только список
    }
    if args.limit and args.limit > 0:
        opts["playlistend"] = args.limit
    opts.update(subs_mod.cookie_opts(args))
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"yt-dlp: {e}"}, ensure_ascii=False))
        return 1

    raw = info.get("entries")
    entries = []
    if raw is None:
        # одиночное видео
        if info.get("id"):
            entries.append({
                "id": info.get("id"),
                "title": info.get("title"),
                "url": info.get("webpage_url", url),
            })
    else:
        for e in raw:
            if not e or not e.get("id"):
                continue  # недоступные/удалённые элементы плейлиста
            entries.append({
                "id": e.get("id"),
                "title": e.get("title"),
                "url": e.get("url") or e.get("webpage_url"),
            })

    print(json.dumps({
        "playlist": info.get("title"),
        "count": len(entries),
        "entries": entries,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
