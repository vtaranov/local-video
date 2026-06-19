"""Перечисление видео плейлиста/канала без скачивания (yt-dlp, flat).

Использование:  python list_playlist.py "<PLAYLIST_URL>"
Вывод: JSON {"playlist": <название>, "count": N, "entries": [{id, title, url}, ...]}.
Если URL — одиночное видео, вернёт один элемент.
"""
from __future__ import annotations

import json
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(json.dumps({"error": "Ожидается один аргумент: URL плейлиста"},
                         ensure_ascii=False))
        return 1
    url = argv[0]
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
