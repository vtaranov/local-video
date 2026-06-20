"""Перевод субтитров на русский локальной моделью Ollama. Тайминги сохраняются.

Перевод идёт батчами (контекст соседних реплик), результат сверяется по числу
строк; при расхождении батч дробится, в пределе — построчный перевод.

Реплики внутри батча могут быть фрагментами одного предложения (актуально для
авто-субтитров: см. subs.parse_json3), а батчи переводятся независимыми
запросами к Ollama — без контекста соседнего батча швы на границе получаются
рваными (предложение обрывается на полуслове). Поэтому в каждый запрос
дополнительно передаются CONTEXT_LINES последних переведённых строк предыдущего
батча (для согласования терминологии/падежей) и CONTEXT_LINES следующих
оригинальных строк (чтобы модель знала, чем фраза продолжится, и не обрубала её
неестественно) — сам контекст не переводится и не попадает в ответ.

После каждого батча прогресс сохраняется в чекпойнт-файл `<out>.checkpoint.json`
рядом с выходным субтитром. При повторном запуске с тем же входным файлом,
моделью, target и batch — перевод продолжается с места останова (например,
после падения процесса или выключения компьютера), а не начинается заново.
Чекпойнт удаляется при успешном завершении.

Прогресс пишется построчно в stderr (`PROGRESS NN% (i/total реплик)`) с шагом
из конфига `translate_progress_step_pct` (по умолчанию 10%) — этого достаточно,
чтобы оркестратор мог подключить Monitor и получать редкие уведомления вместо
молчания до самого конца.

Использование:
  python translate.py <IN.vtt|srt> --out <OUT.vtt> [--model gemma4:latest]
        [--target ru] [--batch 40] [--host http://localhost:11434]
        [--progress-step 10]
Вывод: JSON {"output_path":..., "segments":..., "model":...}.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import subs as subs_mod
import config as config_mod

_CFG = config_mod.load()

LANG_NAME = {"ru": "русский", "en": "английский"}
CONTEXT_LINES = 2


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


def _translate_batch(
    host: str,
    model: str,
    target: str,
    texts: list[str],
    context_before: str = "",
    context_after: str = "",
) -> list[str]:
    tgt = LANG_NAME.get(target, target)
    system = (
        f"Ты профессиональный переводчик субтитров на {tgt} язык. "
        "Переводи естественно и связно, сохраняя смысл и тон. "
        "Реплики в \"lines\" могут быть фрагментами одного предложения, разорванными "
        "на стыке с соседним фрагментом речи. Если даны \"context_before\" (уже "
        "переведённый текст непосредственно перед lines) и/или \"context_after\" "
        "(оригинальный текст непосредственно после lines) — используй их только как "
        "контекст для согласования терминологии, рода и падежей и плавного продолжения "
        "мысли. НЕ переводи context_before/context_after и не включай их в ответ. "
        "Не добавляй пояснений. Верни СТРОГО JSON-объект вида "
        '{\"translations\": [...]} — массив переводов той же длины и в том же '
        "порядке, что и lines. Каждый элемент — перевод соответствующей строки lines."
    )
    payload: dict = {"lines": texts}
    if context_before:
        payload["context_before"] = context_before
    if context_after:
        payload["context_after"] = context_after
    user = json.dumps(payload, ensure_ascii=False)
    raw = _chat(host, model, system, user)
    obj = json.loads(raw)
    out = obj.get("translations")
    if not isinstance(out, list):
        raise ValueError("нет ключа translations")
    return [str(x) for x in out]


def _translate_safe(
    host, model, target, texts, context_before="", context_after="", depth=0
) -> list[str]:
    if not texts:
        return []
    try:
        out = _translate_batch(host, model, target, texts, context_before, context_after)
        if len(out) == len(texts):
            return out
    except (urllib.error.URLError, json.JSONDecodeError, ValueError, KeyError):
        pass
    if len(texts) == 1:
        # последний шанс — вернуть оригинал, чтобы не потерять реплику
        try:
            out = _translate_batch(host, model, target, texts, context_before, context_after)
            return out if len(out) == 1 else texts
        except Exception:  # noqa: BLE001
            return texts
    # при дроблении батча из-за расхождения длины контекст не передаём —
    # тут важнее не потерять реплики, чем сохранить связность шва
    mid = len(texts) // 2
    return (
        _translate_safe(host, model, target, texts[:mid], depth=depth + 1)
        + _translate_safe(host, model, target, texts[mid:], depth=depth + 1)
    )


def _fmt_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}ч{m:02d}м"
    if m:
        return f"{m}м{s:02d}с"
    return f"{s}с"


def _checkpoint_path(out: str) -> Path:
    return Path(str(out) + ".checkpoint.json")


def _checkpoint_key(source_hash: str, args) -> dict:
    return {
        "source_hash": source_hash,
        "model": args.model,
        "target": args.target,
        "batch": args.batch,
    }


def _load_checkpoint(path: Path, key: dict) -> list[str]:
    if not path.is_file():
        return []
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if obj.get("key") != key or not isinstance(obj.get("translated"), list):
        return []
    return obj["translated"]


def _save_checkpoint(path: Path, key: dict, translated: list[str]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps({"key": key, "translated": translated}, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=_CFG["ollama_model"])
    ap.add_argument("--target", default="ru")
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--host", default=_CFG["ollama_host"])
    ap.add_argument(
        "--progress-step", type=int, default=_CFG.get("translate_progress_step_pct", 10)
    )
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

    source_hash = hashlib.sha256(src.read_bytes()).hexdigest()
    key = _checkpoint_key(source_hash, args)
    ckpt_path = _checkpoint_path(args.out)
    translated: list[str] = _load_checkpoint(ckpt_path, key)
    if translated:
        print(
            f"[translate] возобновление с чекпойнта: {len(translated)}/{len(texts)} "
            "реплик уже переведено",
            file=sys.stderr,
        )

    step = max(1, args.progress_step)
    last_reported = (len(translated) * 100 // len(texts)) if texts else 0

    run_start_index = len(translated)
    run_start_time = time.monotonic()
    try:
        i = len(translated)
        while i < len(texts):
            chunk = texts[i:i + args.batch]
            context_before = " ".join(translated[-CONTEXT_LINES:])
            context_after = " ".join(texts[i + len(chunk):i + len(chunk) + CONTEXT_LINES])
            batch_start_time = time.monotonic()
            translated.extend(_translate_safe(
                args.host, args.model, args.target, chunk, context_before, context_after
            ))
            batch_elapsed = time.monotonic() - batch_start_time
            i += len(chunk)
            _save_checkpoint(ckpt_path, key, translated)
            pct = i * 100 // len(texts)
            if pct >= last_reported + step or i >= len(texts):
                done_this_run = i - run_start_index
                elapsed_this_run = time.monotonic() - run_start_time
                remaining = len(texts) - i
                eta = (
                    _fmt_duration(remaining * elapsed_this_run / done_this_run)
                    if done_this_run else "?"
                )
                print(
                    f"PROGRESS {pct}% ({i}/{len(texts)} реплик, "
                    f"батч {_fmt_duration(batch_elapsed)}, осталось ~{eta})",
                    file=sys.stderr, flush=True,
                )
                last_reported = pct
    except urllib.error.URLError as e:
        print(json.dumps(
            {"error": f"Ollama недоступен ({args.host}): {e}"}, ensure_ascii=False
        ))
        return 1

    if len(translated) != len(texts):
        print(json.dumps({
            "error": f"Несовпадение числа переводов: ожидалось {len(texts)}, "
                     f"получено {len(translated)}"
        }, ensure_ascii=False))
        return 1

    fallback_count = sum(
        1 for orig, tr in zip(texts, translated) if tr.strip() == orig.strip()
    )
    if fallback_count:
        print(
            f"[translate] предупреждение: {fallback_count}/{len(texts)} реплик "
            "остались непереведёнными (язык оригинала после всех попыток)",
            file=sys.stderr,
        )

    for seg, txt in zip(segments, translated):
        seg.text = txt.strip()

    out = subs_mod.write_vtt(segments, args.out)
    try:
        ckpt_path.unlink()
    except OSError:
        pass
    print(json.dumps({
        "output_path": str(out),
        "segments": len(segments),
        "model": args.model,
        "target": args.target,
        "untranslated_fallback": fallback_count,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
