"""Скачивание CT2-модели faster-whisper в локальный хаб.

Источники (по убыванию скорости на «зарезанном» канале): ModelScope, HF-зеркало,
Hugging Face. Качает четыре файла модели через curl с возобновлением.

Использование:
  python download_model.py [--size small] [--out <DIR>] [--source modelscope|hf-mirror|hf]
        [--force]
По умолчанию размер и папка берутся из config.json (whisper_model / whisper_model_dir).
Вывод: JSON {"model_dir":..., "size":..., "source":..., "files":[...]}.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import config as config_mod

FILES = ["model.bin", "config.json", "tokenizer.json", "vocabulary.txt"]

# построители URL для одного файла модели заданного размера
SOURCES = {
    "modelscope": lambda size, f: (
        f"https://modelscope.cn/api/v1/models/pengzhendong/"
        f"faster-whisper-{size}/repo?Revision=master&FilePath={f}"
    ),
    "hf-mirror": lambda size, f: (
        f"https://hf-mirror.com/Systran/faster-whisper-{size}/resolve/main/{f}"
    ),
    "hf": lambda size, f: (
        f"https://huggingface.co/Systran/faster-whisper-{size}/resolve/main/{f}"
    ),
}
# порядок фолбэка для каждого «головного» источника
FALLBACK = {
    "modelscope": ["modelscope", "hf-mirror", "hf"],
    "hf-mirror": ["hf-mirror", "hf", "modelscope"],
    "hf": ["hf", "hf-mirror", "modelscope"],
}


def _curl(url: str, dest: Path) -> bool:
    if not shutil.which("curl"):
        print(json.dumps({"error": "curl не найден в системе"}, ensure_ascii=False))
        sys.exit(1)
    cmd = [
        "curl", "-L", "-C", "-", "--retry", "10", "--retry-delay", "5",
        "--fail", "-s", url, "-o", str(dest),
    ]
    return subprocess.run(cmd).returncode == 0


def _download_file(size: str, fname: str, dest: Path, order: list[str]) -> str | None:
    """Пробует источники по очереди. Возвращает имя сработавшего источника или None."""
    for src in order:
        url = SOURCES[src](size, fname)
        if _curl(url, dest):
            # модель не должна быть крошечной (защита от HTML-страниц ошибок)
            if fname == "model.bin" and dest.stat().st_size < 1_000_000:
                dest.unlink(missing_ok=True)
                continue
            return src
    return None


def main(argv: list[str]) -> int:
    cfg = config_mod.load()
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default=cfg["whisper_model"])
    ap.add_argument("--out", default=cfg["whisper_model_dir"])
    ap.add_argument("--source", default="modelscope", choices=list(SOURCES))
    ap.add_argument("--force", action="store_true", help="перекачать, даже если уже есть")
    args = ap.parse_args(argv)

    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    if not args.force and all((out / f).exists() for f in FILES) \
            and (out / "model.bin").stat().st_size > 1_000_000:
        print(json.dumps({
            "model_dir": str(out), "size": args.size, "source": "(уже скачано)",
            "files": FILES,
        }, ensure_ascii=False, indent=2))
        return 0

    order = FALLBACK[args.source]
    used: dict[str, str] = {}
    for fname in FILES:
        src = _download_file(args.size, fname, out / fname, order)
        if src is None:
            print(json.dumps(
                {"error": f"Не удалось скачать {fname} (размер '{args.size}') "
                          f"ни с одного источника: {order}"},
                ensure_ascii=False,
            ))
            return 1
        used[fname] = src

    print(json.dumps({
        "model_dir": str(out),
        "size": args.size,
        "source": used.get("model.bin"),
        "files": FILES,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
