"""Перевод субтитров на русский локальной моделью Ollama. Тайминги сохраняются.

Перевод идёт батчами (контекст соседних реплик), результат сверяется по числу
строк; при расхождении батч дробится, в пределе — построчный перевод.

Использование:
  python translate.py <IN.vtt|srt> --out <OUT.vtt> [--model gemma4:latest]
        [--target ru] [--batch 40] [--host http://localhost:11434]
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

LANG_NAME = {"ru": "русский", "en": "английский"}


def _chat(host: str, model: str, system: str, user: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
    }
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["message"]["content"]


def _translate_batch(host: str, model: str, target: str, texts: list[str]) -> list[str]:
    tgt = LANG_NAME.get(target, target)
    system = (
        f"Ты профессиональный переводчик субтитров на {tgt} язык. "
        "Переводи естественно и связно, сохраняя смысл и тон. "
        "Не добавляй пояснений. Верни СТРОГО JSON-объект вида "
        '{\"translations\": [...]} — массив переводов той же длины и в том же '
        "порядке, что и входной массив. Каждый элемент — перевод соответствующей строки."
    )
    user = json.dumps({"lines": texts}, ensure_ascii=False)
    raw = _chat(host, model, system, user)
    obj = json.loads(raw)
    out = obj.get("translations")
    if not isinstance(out, list):
        raise ValueError("нет ключа translations")
    return [str(x) for x in out]


def _translate_safe(host, model, target, texts, depth=0) -> list[str]:
    if not texts:
        return []
    try:
        out = _translate_batch(host, model, target, texts)
        if len(out) == len(texts):
            return out
    except (urllib.error.URLError, json.JSONDecodeError, ValueError, KeyError):
        pass
    if len(texts) == 1:
        # последний шанс — вернуть оригинал, чтобы не потерять реплику
        try:
            out = _translate_batch(host, model, target, texts)
            return out if len(out) == 1 else texts
        except Exception:  # noqa: BLE001
            return texts
    mid = len(texts) // 2
    return (
        _translate_safe(host, model, target, texts[:mid], depth + 1)
        + _translate_safe(host, model, target, texts[mid:], depth + 1)
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="gemma4:latest")
    ap.add_argument("--target", default="ru")
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--host", default="http://localhost:11434")
    args = ap.parse_args(argv)

    src = Path(args.input)
    if not src.exists():
        print(json.dumps({"error": f"Файл не найден: {src}"}, ensure_ascii=False))
        return 1

    segments = subs_mod.parse_file(src)
    if not segments:
        print(json.dumps({"error": "Субтитры пусты или не распознаны"}, ensure_ascii=False))
        return 1

    texts = [s.text.replace("\n", " ") for s in segments]
    translated: list[str] = []
    try:
        for i in range(0, len(texts), args.batch):
            chunk = texts[i:i + args.batch]
            translated.extend(_translate_safe(args.host, args.model, args.target, chunk))
    except urllib.error.URLError as e:
        print(json.dumps(
            {"error": f"Ollama недоступен ({args.host}): {e}"}, ensure_ascii=False
        ))
        return 1

    for seg, txt in zip(segments, translated):
        seg.text = txt.strip()

    out = subs_mod.write_vtt(segments, args.out)
    print(json.dumps({
        "output_path": str(out),
        "segments": len(segments),
        "model": args.model,
        "target": args.target,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
