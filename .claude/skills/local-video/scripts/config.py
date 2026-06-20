"""Конфигурация скилла local-video: встроенные дефолты + перекрытие из config.json.

Порядок поиска config.json:
  1. путь из переменной окружения LOCAL_VIDEO_CONFIG
  2. <корень скилла>/config.json
  3. ~/.config/local-video/config.json
Если файла нет — используются дефолты ниже.

Запуск напрямую печатает итоговую конфигурацию (JSON) — этим пользуется оркестратор.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULTS = {
    "library": "~/all-local-videos",
    "whisper_model": "small",
    "whisper_model_dir": "~/ai-models/faster-whisper/small",
    "ollama_model": "gemma4:latest",
    "ollama_host": "http://localhost:11434",
    "player_dir": "",  # пусто → плеер ищется как соседний player/ (см. play.py)
    "translate_progress_step_pct": 10,  # шаг прогресса translate.py, % (для Monitor)
}
# поля, которые нужно разворачивать как пути (~ → домашняя папка)
PATH_KEYS = {"library", "whisper_model_dir", "player_dir"}


def _skill_root() -> Path:
    return Path(__file__).resolve().parent.parent  # scripts/ -> корень скилла


def _candidates() -> list[Path]:
    out: list[Path] = []
    env = os.environ.get("LOCAL_VIDEO_CONFIG")
    if env:
        out.append(Path(env))
    out.append(_skill_root() / "config.json")
    out.append(Path.home() / ".config" / "local-video" / "config.json")
    return out


def load() -> dict:
    cfg = dict(DEFAULTS)
    for p in _candidates():
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                cfg.update({k: v for k, v in data.items() if v is not None})
            except (json.JSONDecodeError, OSError):
                pass
            break
    for k in PATH_KEYS:
        if isinstance(cfg.get(k), str) and cfg[k]:
            cfg[k] = str(Path(cfg[k]).expanduser())
    return cfg


if __name__ == "__main__":
    json.dump(load(), sys.stdout, ensure_ascii=False, indent=2)
    print()
