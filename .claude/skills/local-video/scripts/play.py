"""Локатор веб-плеера проекта. Сам ничего не запускает — печатает, где плеер и
чем его запускать; оркестратор (Claude) поднимает сервер по этим данным.

Плеер ищется так: `player_dir` из конфига, если задан; иначе — соседний `player/`
(поиск вверх от реального пути этого скрипта; работает и через глобальный симлинк,
т.к. resolve() ведёт в реальный репозиторий).

Использование:  python play.py
Вывод: JSON {player_dir, app, python, flask_ok, ready, hint}.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import config as config_mod


def find_player(cfg: dict) -> Path | None:
    override = cfg.get("player_dir")
    if override:
        p = Path(override).expanduser()
        return p if (p / "app.py").is_file() else p
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "player"
        if (cand / "app.py").is_file():
            return cand
    return None


def player_python(player_dir: Path) -> str:
    venv = player_dir / "venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def flask_ok(python: str) -> bool:
    try:
        return subprocess.run(
            [python, "-c", "import flask"], capture_output=True
        ).returncode == 0
    except OSError:
        return False


def main() -> int:
    cfg = config_mod.load()
    player_dir = find_player(cfg)
    if player_dir is None or not (player_dir / "app.py").is_file():
        print(json.dumps({
            "player_dir": str(player_dir) if player_dir else None,
            "ready": False,
            "error": "Плеер не найден (нет player/app.py). Задай player_dir в config.json "
                     "или запусти из полного репозитория.",
        }, ensure_ascii=False, indent=2))
        return 1

    python = player_python(player_dir)
    ok = flask_ok(python)
    app = player_dir / "app.py"
    print(json.dumps({
        "player_dir": str(player_dir),
        "app": str(app),
        "python": python,
        "flask_ok": ok,
        "ready": ok,
        "hint": f'запуск в фоне: "{python}" "{app}" [--dir "<папка видео>"] '
                "(без --dir — экран библиотеки). Если flask_ok=false — выполни install.sh.",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
