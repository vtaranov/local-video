"""Перевод субтитров на русский локальной моделью Ollama.

Перевод идёт батчами (контекст соседних реплик). Модель не обязана вернуть
ровно столько строк перевода, сколько было реплик в батче: авто-субтитры режут
предложения произвольно (см. subs.parse_json3), и при переводе "естественно и
связно" модель сама решает границы фраз, иногда сливая несколько реплик в одну.
Подгонять её под исходное число строк (повторами/построчным распадом) дорого и
не нужно — вместо этого окно времени всего батча (от начала первой реплики до
конца последней) делится между ВСЕМИ полученными переводами пропорционально их
длине. Сумма длительностей новых реплик точно равна длительности батча, поэтому
показ перевода батча начинается и заканчивается в то же время, что и оригинал —
просто реплик внутри батча может быть больше или меньше, чем в исходнике.

Если модель схлопнула почти весь батч в одну-две реплики (а не просто пару
соседних фрагментов), пропорциональное деление дало бы один кусок текста на
весь батч — например, реплику на экране на 3+ минуты, пока произносится
десяток разных фраз. От этого защищает отдельный шаг: любая реплика длиннее
MAX_CUE_SECONDS дробится по границам предложений, а если их нет — по запятым/
тире (_split_oversized), и тайминг распределяется внутри её собственного окна —
без обращения к модели.

ВАЖНО (защита от регресса): дробление НЕ режет по каждой запятой подряд —
соседние фрагменты сперва жадно упаковываются в куски ~MAX_CUE_SECONDS по
времени чтения (_pack_parts), а итог дополнительно проходит флор
MIN_CUE_SECONDS (_merge_short склеивает слишком короткие реплики с соседом
внутри батча). Без этого длинное предложение с десятком запятых рассыпалось
в нечитаемое «конфетти» по 0.4–0.6с на одну-две слова.

Реплики внутри батча могут быть фрагментами одного предложения, а батчи
переводятся независимыми запросами к Ollama — без контекста соседнего батча швы
на границе получаются рваными (предложение обрывается на полуслове). Поэтому в
каждый запрос дополнительно передаются последние CONTEXT_LINES переведённых
реплик предыдущего батча (для согласования терминологии/падежей) и CONTEXT_LINES
следующих оригинальных строк (чтобы модель знала, чем фраза продолжится, и не
обрубала её неестественно) — сам контекст не переводится и не попадает в ответ.

После каждого батча прогресс сохраняется в чекпойнт-файл `<out>.checkpoint.json`
рядом с выходным субтитром: сколько исходных реплик уже обработано и какие
переведённые реплики (с их таймингом) уже готовы. При повторном запуске с тем же
входным файлом, моделью, target и batch — перевод продолжается с места останова,
а не начинается заново. Чекпойнт удаляется при успешном завершении.

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
import re
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
# дольше этого один субтитр на экране висеть не должен — иначе ловим случаи,
# когда модель схлопывает большую часть батча в одну-две реплики
MAX_CUE_SECONDS = 8.0
MIN_CUE_SECONDS = 1.0
READING_CPS = 17  # комфортная скорость чтения, символов в секунду
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_CLAUSE_SPLIT = re.compile(r"(?<=[,;:—-])\s+")
# с запасом под самый длинный батч (по умолчанию 40 строк + контекст); без явного
# num_predict Ollama берёт дефолт модели, которого иногда не хватает — JSON-режим
# (format: "json") в этом случае не выдаёт ошибку, а принудительно закрывает
# массив translations раньше времени
NUM_PREDICT = 4096


def _chat(host: str, model: str, system: str, user: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2, "num_predict": NUM_PREDICT},
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
        "на стыке с соседним фрагментом речи — в этом случае можешь объединить ровно "
        "эти 2, максимум 3 соседние реплики в один элемент translations. Старайся "
        "держать соответствие lines и translations как можно ближе к 1:1 — это не "
        "жёсткое требование точного количества, но НЕ сливай в один элемент весь "
        "батч или большую его часть: переводи каждую реплику из lines отдельным "
        "элементом, если только её смысл не обрывается на середине фразы. Если даны "
        "\"context_before\" (уже переведённый текст непосредственно перед lines) "
        "и/или \"context_after\" (оригинальный текст непосредственно после lines) — "
        "используй их только как контекст для согласования терминологии, рода и "
        "падежей и плавного продолжения мысли. context_before может обрываться на "
        "полуслове — незаконченной грамматической конструкции (предлог/союз без "
        "дополнения). Если это так, начинай перевод так, чтобы он был прямым "
        "грамматическим продолжением именно этой конструкции (тот же падеж, то же "
        "дополнение), а не самостоятельной новой мыслью. НЕ переводи "
        "context_before/context_after и не включай их в ответ. Не добавляй пояснений. "
        "Верни СТРОГО JSON-объект вида "
        '{\"translations\": [...]} — массив переводов в том же порядке, что и lines.'
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
    if not isinstance(out, list) or not out:
        raise ValueError("нет непустого ключа translations")
    return [str(x) for x in out]


def _translate_batch_safe(
    host: str, model: str, target: str, texts: list[str],
    context_before: str = "", context_after: str = "",
) -> list[str]:
    """Переводит батч; при сетевом/форматном сбое — один повтор, а если не
    помогло — возвращает исходные строки без перевода (батч не теряется,
    остаётся на языке оригинала)."""
    for attempt in range(2):
        try:
            return _translate_batch(host, model, target, texts, context_before, context_after)
        except (urllib.error.URLError, json.JSONDecodeError, ValueError, KeyError) as e:
            print(
                f"[translate] батч из {len(texts)} реплик (попытка {attempt + 1}): "
                f"{type(e).__name__}",
                file=sys.stderr, flush=True,
            )
    print(
        f"[translate] батч из {len(texts)} реплик — не удалось перевести, "
        "оставляем оригинал",
        file=sys.stderr, flush=True,
    )
    return list(texts)


def _distribute_timing(cues: list[str], start: float, end: float) -> list[tuple[float, float]]:
    """Делит [start, end] между cues пропорционально длине текста (в символах),
    так что сумма длительностей точно равна end - start независимо от того,
    сколько переведённых реплик получилось — больше или меньше исходного числа."""
    weights = [max(len(c), 1) for c in cues]
    wsum = sum(weights)
    total = max(end - start, 0.0)
    spans = []
    t = start
    for idx, w in enumerate(weights):
        is_last = idx == len(weights) - 1
        seg_end = end if is_last else t + total * w / wsum
        spans.append((t, seg_end))
        t = seg_end
    return spans


def _natural_duration(text: str) -> float:
    """Сколько времени нужно показывать text на экране при комфортной скорости
    чтения — не больше MAX_CUE_SECONDS и не меньше MIN_CUE_SECONDS."""
    return min(MAX_CUE_SECONDS, max(MIN_CUE_SECONDS, len(text) / READING_CPS))


def _pack_parts(parts: list[str]) -> list[str]:
    """Жадно объединяет последовательные предложения/клаузы в куски, каждый из
    которых читается не дольше MAX_CUE_SECONDS. Иначе дробление по КАЖДОЙ запятой
    плодит нечитаемые реплики по одному-два слова: для попадания под лимит обычно
    хватает 2–3 кусков, а не десятка."""
    groups: list[str] = []
    cur = ""
    for p in parts:
        cand = (cur + " " + p) if cur else p
        if cur and len(cand) / READING_CPS > MAX_CUE_SECONDS:
            groups.append(cur)
            cur = p
        else:
            cur = cand
    if cur:
        groups.append(cur)
    return groups


def _split_oversized(text: str, start: float, end: float) -> list[tuple[float, float, str]]:
    """Если реплика длиннее MAX_CUE_SECONDS — дробит её по границам предложений,
    а если их нет (длинный кусок без точек — рваная речь без пауз) — по запятым/
    тире. Соседние фрагменты при этом жадно упаковываются в куски ~MAX_CUE_SECONDS
    по времени чтения (см. _pack_parts), а не выдаются по одному. Тайминг
    распределяется внутри [start, end] (см. _distribute_timing) на каждом уровне.

    Если границ нет вообще (один сплошной фрагмент без пунктуации, обычно когда
    модель схлопнула большую часть батча в малое число реплик и на короткий
    текст пришлась несоразмерно долгая доля времени) — дробить по словам не
    вариант: получаются нечитаемые куски по одному-два слова на несколько секунд
    каждый. Вместо этого показываем текст ровно по времени чтения, а остаток
    окна оставляем пустым — для субтитров это нормально, не каждая секунда
    видео обязана быть покрыта репликой."""
    if end - start <= MAX_CUE_SECONDS:
        return [(start, end, text)]
    parts = [p for p in _SENTENCE_SPLIT.split(text) if p.strip()]
    if len(parts) <= 1:
        parts = [p for p in _CLAUSE_SPLIT.split(text) if p.strip()]
    groups = _pack_parts(parts) if len(parts) > 1 else parts
    if len(groups) <= 1:
        return [(start, min(end, start + _natural_duration(text)), text)]
    result: list[tuple[float, float, str]] = []
    for (s, e), g in zip(_distribute_timing(groups, start, end), groups):
        result.extend(_split_oversized(g, s, e))
    return result


def _merge_short(spans: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    """Склеивает реплики короче MIN_CUE_SECONDS с соседом, чтобы они не мелькали
    нечитаемо (0.4–0.6с на фразу). Применяется к репликам ОДНОГО батча, поэтому
    начало первой и конец последней не меняются — окно батча сохраняется."""
    out: list[tuple[float, float, str]] = []
    for s, e, t in spans:
        if out and (out[-1][1] - out[-1][0]) < MIN_CUE_SECONDS:
            ps, _, pt = out[-1]
            out[-1] = (ps, e, (pt + " " + t).strip())
        else:
            out.append((s, e, t))
    # хвост: если последняя реплика всё ещё короткая — приклеить к предыдущей
    if len(out) >= 2 and (out[-1][1] - out[-1][0]) < MIN_CUE_SECONDS:
        ps, _, pt = out[-2]
        _, e, t = out.pop()
        out[-1] = (ps, e, (pt + " " + t).strip())
    return out


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


def _load_checkpoint(path: Path, key: dict) -> tuple[int, list[subs_mod.Segment]]:
    if not path.is_file():
        return 0, []
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, []
    if obj.get("key") != key or not isinstance(obj.get("cues"), list):
        return 0, []
    cues = [subs_mod.Segment(c["start"], c["end"], c["text"]) for c in obj["cues"]]
    return int(obj.get("consumed", 0)), cues


def _save_checkpoint(
    path: Path, key: dict, consumed: int, cues: list[subs_mod.Segment]
) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "key": key,
        "consumed": consumed,
        "cues": [{"start": c.start, "end": c.end, "text": c.text} for c in cues],
    }
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
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
    consumed, cues = _load_checkpoint(ckpt_path, key)
    if consumed:
        print(
            f"[translate] возобновление с чекпойнта: {consumed}/{len(texts)} "
            f"реплик обработано, {len(cues)} переведённых реплик готово",
            file=sys.stderr,
        )

    step = max(1, args.progress_step)
    last_reported = (consumed * 100 // len(texts)) if texts else 0

    run_start_index = consumed
    run_start_time = time.monotonic()
    try:
        i = consumed
        while i < len(texts):
            chunk = texts[i:i + args.batch]
            batch_start = segments[i].start
            batch_end = segments[i + len(chunk) - 1].end
            context_before = " ".join(c.text for c in cues[-CONTEXT_LINES:])
            context_after = " ".join(texts[i + len(chunk):i + len(chunk) + CONTEXT_LINES])
            batch_start_time = time.monotonic()
            batch_translated = _translate_batch_safe(
                args.host, args.model, args.target, chunk, context_before, context_after
            )
            batch_spans: list[tuple[float, float, str]] = []
            for (s, e), txt in zip(
                _distribute_timing(batch_translated, batch_start, batch_end),
                batch_translated,
            ):
                for s2, e2, t2 in _split_oversized(txt.strip(), s, e):
                    batch_spans.append((s2, e2, t2.strip()))
            for s2, e2, t2 in _merge_short(batch_spans):
                cues.append(subs_mod.Segment(s2, e2, t2))
            batch_elapsed = time.monotonic() - batch_start_time
            i += len(chunk)
            _save_checkpoint(ckpt_path, key, i, cues)
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

    out = subs_mod.write_vtt(cues, args.out)
    try:
        ckpt_path.unlink()
    except OSError:
        pass
    print(json.dumps({
        "output_path": str(out),
        "segments": len(cues),
        "source_segments": len(segments),
        "model": args.model,
        "target": args.target,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
