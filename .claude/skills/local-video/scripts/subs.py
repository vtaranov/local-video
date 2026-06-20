"""Общий модуль работы с субтитрами: парсинг .srt/.vtt, сборка .vtt, детект языка.

Внутреннее представление — список Segment(start, end, text), время в секундах (float).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Segment:
    start: float
    end: float
    text: str


_TS = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[.,](?P<ms>\d{1,3})"
)
# inline-теги авто-субтитров YouTube: <00:00:00.000>, <c>, </c>
_INLINE_TAG = re.compile(r"<[^>]+>")


def parse_timestamp(value: str) -> float:
    m = _TS.search(value)
    if not m:
        raise ValueError(f"Не распознано время: {value!r}")
    h, mn, s = int(m["h"]), int(m["m"]), int(m["s"])
    ms = int(m["ms"].ljust(3, "0"))
    return h * 3600 + mn * 60 + s + ms / 1000.0


def format_vtt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _clean_text(text: str) -> str:
    text = _INLINE_TAG.sub("", text)
    return text.strip()


def detect_format(path: str | Path) -> str:
    p = Path(path)
    head = ""
    try:
        head = p.read_text(encoding="utf-8", errors="ignore")[:64].lstrip("﻿")
    except OSError:
        pass
    if p.suffix.lower() == ".vtt" or head.startswith("WEBVTT"):
        return "vtt"
    return "srt"


def parse_file(path: str | Path) -> list[Segment]:
    raw = Path(path).read_text(encoding="utf-8", errors="ignore").lstrip("﻿")
    return parse_text(raw)


def parse_text(raw: str) -> list[Segment]:
    """Парсит и .srt, и .vtt. Дедуплицирует подряд идущие одинаковые реплики
    (частый артефакт авто-субтитров YouTube)."""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", raw)
    segments: list[Segment] = []
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        if lines[0].strip().startswith("WEBVTT"):
            lines = lines[1:]
        if lines and lines[0].strip().upper().startswith(("NOTE", "STYLE", "REGION")):
            continue
        ts_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if ts_idx is None:
            continue
        left, _, right = lines[ts_idx].partition("-->")
        try:
            start = parse_timestamp(left)
            end = parse_timestamp(right)
        except ValueError:
            continue
        text = _clean_text("\n".join(lines[ts_idx + 1:]))
        if not text:
            continue
        if segments and segments[-1].text == text and abs(segments[-1].end - start) < 0.05:
            segments[-1].end = end
            continue
        segments.append(Segment(start, end, text))
    return segments


def parse_json3(raw: str, max_words: int = 16) -> list[Segment]:
    """Парсит сырые авто-субтитры YouTube в формате json3.

    В отличие от .vtt-экспорта, события здесь не дублируют текст (каждое —
    новый фрагмент речи); но их `dDurationMs` — это время показа в
    перекрывающемся окне прокрутки, а не длительность самой речи, поэтому
    соседние фрагменты по таймингу всё равно перекрываются. Конец каждого
    фрагмента обрезается началом следующего перед склейкой в фразы — иначе
    итоговые реплики получаются с пересекающимися/немонотонными таймингами.
    Фразы собираются по паузам в речи и знакам конца предложения; безостановочная
    речь (доклад без пауз) дополнительно дробится по max_words, чтобы не
    получить одну реплику на 70+ секунд — нечитаемую в плеере.
    """
    data = json.loads(raw)
    chunks: list[tuple[int, int, str]] = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        text = "".join(s.get("utf8", "") for s in segs).strip()
        if not text:
            continue
        start_ms = ev.get("tStartMs", 0)
        end_ms = start_ms + ev.get("dDurationMs", 0)
        chunks.append((start_ms, end_ms, text))
    for i in range(len(chunks)):
        start_ms, end_ms, text = chunks[i]
        if i + 1 < len(chunks):
            end_ms = min(end_ms, chunks[i + 1][0])
        chunks[i] = (start_ms, max(end_ms, start_ms), text)

    segments: list[Segment] = []
    buf_start: float | None = None
    buf_end: float = 0.0
    buf_text = ""
    prev_end_ms: int | None = None

    def flush() -> None:
        nonlocal buf_start, buf_text
        text = buf_text.strip()
        if text and buf_start is not None:
            segments.append(Segment(buf_start, buf_end, text))
        buf_start = None
        buf_text = ""

    for start_ms, end_ms, chunk in chunks:
        if buf_text and prev_end_ms is not None and start_ms - prev_end_ms > 600:
            flush()
        elif buf_text and len(buf_text.split()) >= max_words:
            flush()
        if buf_start is None:
            buf_start = start_ms / 1000.0
        buf_end = end_ms / 1000.0
        buf_text += (" " if buf_text else "") + chunk
        prev_end_ms = end_ms
        if len(buf_text.split()) >= 3 and re.search(r"[.!?][\"'”)\]]*$", buf_text):
            flush()
    flush()
    return segments


def write_vtt(segments: list[Segment], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    parts = ["WEBVTT", ""]
    for seg in segments:
        parts.append(
            f"{format_vtt_timestamp(seg.start)} --> {format_vtt_timestamp(seg.end)}"
        )
        parts.append(seg.text)
        parts.append("")
    out.write_text("\n".join(parts), encoding="utf-8")
    return out


def parse_extractor_args(specs: list[str]) -> dict:
    """Парсит CLI-спеки yt-dlp вида 'youtube:player_client=android,web;formats=missing_pot'
    в формат опции extractor_args для YoutubeDL (тот же синтаксис, что у --extractor-args
    самого yt-dlp; можно передавать несколько спек — они объединяются)."""
    result: dict[str, dict[str, list[str]]] = {}
    for spec in specs:
        key, _, vals = spec.partition(":")
        key = key.strip().lower().replace("-", "_")
        args: dict[str, list[str]] = {}
        for arg in vals.split(";") if vals else []:
            if not arg:
                continue
            argkey, _, argval = arg.partition("=")
            argkey = argkey.strip().lower().replace("-", "_")
            args[argkey] = [v.replace(r"\,", ",").strip() for v in re.split(r"(?<!\\),", argval)]
        result.setdefault(key, {}).update(args)
    return result


def detect_language(segments: list[Segment], sample: int = 80) -> str | None:
    """Возвращает ISO-код языка по тексту субтитров или None."""
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
    except ImportError:
        return None
    text = " ".join(s.text for s in segments[:sample]).strip()
    if not text:
        return None
    try:
        return detect(text)
    except Exception:
        return None
