"""Библиотека видео: каноническое имя папки, провенанс и дедупликация по video ID.

Каждое видео живёт в подпапке `<очищенный заголовок> [<id>]/` с сайдкаром
`.source.json` (id, url, title, extractor, дата). Дедуп — по ID: авторитетен
сайдкар, запасной вариант — ID в скобках в имени папки.

Подкоманды:
  index   --library DIR                                  → JSON [{id, title, dir, transcripts}]
          transcripts = {langs:[...], ru:bool, orig:[языки кроме ru]}
  folder  --library DIR --title T --id ID                → JSON {dir, exists}
  sidecar --dir D --id ID --url U --title T [--extractor E]  → пишет .source.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SIDECAR = ".source.json"
_BAD = re.compile(r'[/\\:*?"<>|]')
_ID_IN_NAME = re.compile(r"\[([^\[\]]+)\]\s*$")


def sanitize(text: str) -> str:
    text = _BAD.sub("_", text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text or "video"


def folder_name(title: str, vid: str) -> str:
    return f"{sanitize(title)} [{vid}]"


def _read_sidecar(d: Path) -> dict | None:
    p = d / SIDECAR
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def transcripts(d: Path) -> dict:
    """Языки транскриптов в папке видео по файлам `<name>.<lang>.vtt`.

    Возвращает {"langs": [...], "ru": bool, "orig": [языки кроме ru]}.
    `ru` — есть ли русский перевод; `orig` — оригинальные дорожки (не ru).
    """
    langs: list[str] = []
    for p in sorted(d.glob("*.vtt")):
        parts = p.name.split(".")
        if len(parts) >= 3:  # <name>.<lang>.vtt — берём предпоследний сегмент
            lang = parts[-2].strip()
            if lang and lang not in langs:
                langs.append(lang)
    return {"langs": langs, "ru": "ru" in langs, "orig": [l for l in langs if l != "ru"]}


def index(library: Path) -> list[dict]:
    out: list[dict] = []
    if not library.is_dir():
        return out
    for d in sorted(p for p in library.iterdir() if p.is_dir()):
        tr = transcripts(d)
        sc = _read_sidecar(d)
        if sc and sc.get("id"):
            out.append({"id": sc["id"], "title": sc.get("title", d.name),
                        "dir": str(d), "transcripts": tr})
            continue
        m = _ID_IN_NAME.search(d.name)
        if m:
            out.append({"id": m.group(1), "title": d.name, "dir": str(d), "transcripts": tr})
    return out


def find(library: Path, vid: str) -> str | None:
    for e in index(library):
        if e["id"] == vid:
            return e["dir"]
    return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_idx = sub.add_parser("index")
    p_idx.add_argument("--library", required=True)

    p_fld = sub.add_parser("folder")
    p_fld.add_argument("--library", required=True)
    p_fld.add_argument("--title", required=True)
    p_fld.add_argument("--id", required=True)

    p_sc = sub.add_parser("sidecar")
    p_sc.add_argument("--dir", required=True)
    p_sc.add_argument("--id", required=True)
    p_sc.add_argument("--url", required=True)
    p_sc.add_argument("--title", required=True)
    p_sc.add_argument("--extractor", default=None)

    args = ap.parse_args(argv)

    if args.cmd == "index":
        print(json.dumps(index(Path(args.library).expanduser()),
                         ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "folder":
        lib = Path(args.library).expanduser()
        existing = find(lib, args.id)
        if existing:
            result = {"dir": existing, "exists": True}
        else:
            result = {"dir": str(lib / folder_name(args.title, args.id)), "exists": False}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "sidecar":
        d = Path(args.dir).expanduser()
        d.mkdir(parents=True, exist_ok=True)
        data = {
            "id": args.id,
            "url": args.url,
            "title": args.title,
            "extractor": args.extractor,
            "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        (d / SIDECAR).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"sidecar": str(d / SIDECAR), **data}, ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
