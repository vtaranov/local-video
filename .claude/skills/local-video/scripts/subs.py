"""Общий модуль работы с субтитрами: парсинг .srt/.vtt, сборка .vtt, детект языка.

Внутреннее представление — список Segment(start, end, text), время в секундах (float).
"""
from __future__ import annotations

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
