"""Транскрипция аудиодорожки видео локальным faster-whisper -> .vtt.

Использование:
  python transcribe.py <MEDIA> --out <FILE.vtt> [--model medium] [--lang en]
--lang можно не указывать — будет автодетект.
Вывод: JSON {"subtitle_path":..., "language":..., "duration":...}.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import subs as subs_mod


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("media", help="путь к видео или аудио")
    ap.add_argument("--out", required=True, help="путь к выходному .vtt")
    ap.add_argument("--model", default="medium")
    ap.add_argument("--lang", default=None, help="язык оригинала (опц.)")
    ap.add_argument("--compute-type", default="int8")
    args = ap.parse_args(argv)

    media = Path(args.media)
    if not media.exists():
        print(json.dumps({"error": f"Файл не найден: {media}"}, ensure_ascii=False))
        return 1

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(json.dumps({"error": "faster-whisper не установлен"}, ensure_ascii=False))
        return 1

    try:
        model = WhisperModel(args.model, device="cpu", compute_type=args.compute_type)
        segments_iter, info = model.transcribe(
            str(media), language=args.lang, vad_filter=True
        )
        segments = [
            subs_mod.Segment(s.start, s.end, s.text.strip())
            for s in segments_iter if s.text.strip()
        ]
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"faster-whisper: {e}"}, ensure_ascii=False))
        return 1

    out = subs_mod.write_vtt(segments, args.out)
    print(json.dumps({
        "subtitle_path": str(out),
        "language": info.language,
        "language_probability": round(getattr(info, "language_probability", 0.0), 3),
        "duration": round(getattr(info, "duration", 0.0), 1),
        "segments": len(segments),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
