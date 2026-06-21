"""Скачивание выбранных дорожек субтитров (yt-dlp) и нормализация в .vtt.

Использование:
  python fetch_subs.py <URL> --langs en,es --out <DIR> [--auto] [--extractor-args "youtube:player_client=android"]
--auto разрешает авто-сгенерированные субтитры (если ручных нет). Для авто-субтитров
скачивается формат json3 (не vtt!) и конвертируется через subs.parse_json3 — родной
vtt-экспорт YouTube для авто-субтитров эмулирует побуквенную прокрутку перекрывающимися
репликами («I'm excited» / «I'm excited to be here» / ...), что портит и транскрипт,
и перевод. json3 этого артефакта не содержит.
--extractor-args можно указывать несколько раз; формат — как у одноимённой опции yt-dlp.
Полезно как обход, если yt-dlp ошибочно сообщает "video is not available" (баг
дефолтного web-клиента) — попробовать player_client=android.
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
    ap.add_argument("--extractor-args", dest="extractor_args", action="append", default=None)
    subs_mod.add_cookie_args(ap)
    args = ap.parse_args(argv)

    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print(json.dumps({"error": "yt-dlp не установлен"}, ensure_ascii=False))
        return 1

    langs = [s.strip() for s in args.langs.split(",") if s.strip()]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    ext = "json3" if args.auto else "vtt"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": args.auto,
        "subtitleslangs": langs,
        "subtitlesformat": ext,
        "outtmpl": str(out_dir / "%(title)s.%(ext)s"),
    }
    if args.extractor_args:
        opts["extractor_args"] = subs_mod.parse_extractor_args(args.extractor_args)
    opts.update(subs_mod.cookie_opts(args))
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
        # yt-dlp пишет <stem>.<lang>.<ext>
        cand = Path(f"{stem}.{lang}.{ext}")
        if not cand.exists():
            matches = list(out_dir.glob(f"*.{lang}.{ext}"))
            cand = matches[0] if matches else None
        if not (cand and cand.exists()):
            continue
        if ext == "json3":
            segs = subs_mod.parse_json3(cand.read_text(encoding="utf-8", errors="ignore"))
            vtt_path = cand.with_suffix(".vtt")
            subs_mod.write_vtt(segs, vtt_path)
            cand.unlink()
            cand = vtt_path
        else:
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
