"""Саммари транскрипта на его же языке через Ollama. Формат — Markdown.

Саммари пишется НА ТОМ ЖЕ языке, что и транскрипт. Для длинных транскриптов
применяется map-reduce (поблочное саммари + финальный свод).

Использование:
  python summarize.py <IN.vtt|srt> --out <OUT.md> [--model gemma4:latest]
        [--lang ru] [--title "..."] [--host http://localhost:11434]
Вывод: JSON {"output_path":..., "segments":..., "model":...}.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import subs as subs_mod

LANG_NAME = {
    "ru": "русском", "en": "английском", "de": "немецком", "fr": "французском",
    "es": "испанском", "it": "итальянском", "uk": "украинском", "pl": "польском",
}
# порог одиночного прохода по числу символов; выше — map-reduce
SINGLE_PASS_CHARS = 24000
CHUNK_CHARS = 12000


def _chat(host: str, model: str, system: str, user: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.3},
    }
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=900) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["message"]["content"]


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip()


def _lang_phrase(lang: str | None) -> str:
    if not lang:
        return "том же языке, что и расшифровка"
    base = lang.split("-")[0].lower()
    return LANG_NAME.get(base, f"языке с кодом '{base}'")


def _ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


def _transcript_text(segments: list, with_ts: bool = True) -> str:
    if with_ts:
        return "\n".join(f"[{_ts(s.start)}] {s.text}" for s in segments)
    return "\n".join(s.text for s in segments)


def _summary_system(lang_phrase: str) -> str:
    return (
        f"Ты делаешь структурированное саммари расшифровки видео. Пиши строго на "
        f"{lang_phrase}. Формат — Markdown со разделами: '## Краткое содержание' "
        "(2–4 предложения), '## Ключевые тезисы' (маркированный список), "
        "'## Структура по таймкодам' (пункты вида `MM:SS — тема`, опирайся на "
        "таймкоды из расшифровки). Опирайся только на содержание расшифровки, "
        "ничего не выдумывай. Не добавляй вступлений и заключений от себя. "
        "Не оборачивай ответ в тройные кавычки."
    )


def _chunks(segments: list, max_chars: int) -> list[list]:
    out, cur, size = [], [], 0
    for s in segments:
        ln = len(s.text) + 12
        if cur and size + ln > max_chars:
            out.append(cur)
            cur, size = [], 0
        cur.append(s)
        size += ln
    if cur:
        out.append(cur)
    return out


def _summarize(host, model, lang_phrase, segments) -> str:
    full = _transcript_text(segments)
    if len(full) <= SINGLE_PASS_CHARS:
        return _strip_fences(_chat(host, model, _summary_system(lang_phrase), full))

    # map-reduce для длинных
    partials = []
    for chunk in _chunks(segments, CHUNK_CHARS):
        sys_p = (
            f"Кратко изложи на {lang_phrase} ключевые мысли этого фрагмента "
            "расшифровки маркированным списком с таймкодами. Только факты из текста."
        )
        partials.append(_strip_fences(_chat(host, model, sys_p, _transcript_text(chunk))))
    combined = "\n\n".join(partials)
    return _strip_fences(_chat(host, model, _summary_system(lang_phrase), combined))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="gemma4:latest")
    ap.add_argument("--lang", default=None, help="код языка транскрипта (для заголовка)")
    ap.add_argument("--title", default=None)
    ap.add_argument("--host", default="http://localhost:11434")
    args = ap.parse_args(argv)

    src = Path(args.input)
    if not src.exists():
        print(json.dumps({"error": f"Файл не найден: {src}"}, ensure_ascii=False))
        return 1

    segments = subs_mod.parse_file(src)
    if not segments:
        print(json.dumps({"error": "Транскрипт пуст или не распознан"}, ensure_ascii=False))
        return 1

    lang_phrase = _lang_phrase(args.lang)
    try:
        body = _summarize(args.host, args.model, lang_phrase, segments)
    except urllib.error.URLError as e:
        print(json.dumps(
            {"error": f"Ollama недоступен ({args.host}): {e}"}, ensure_ascii=False
        ))
        return 1

    title = args.title or src.stem
    header = f"# {title}\n"
    if args.lang:
        header += f"\n*Саммари по транскрипту (`{src.name}`), язык: {args.lang}*\n"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"{header}\n{body}\n", encoding="utf-8")

    print(json.dumps({
        "output_path": str(out),
        "segments": len(segments),
        "model": args.model,
        "lang": args.lang,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
