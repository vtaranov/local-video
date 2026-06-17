import argparse
import os
import socket
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory, abort

BASE_DIR = Path(__file__).resolve().parent
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".m4v"}

LANG_LABELS = {
    "en": "English",
    "ru": "Русский",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
    "it": "Italiano",
    "ja": "日本語",
    "zh": "中文",
}

app = Flask(__name__)

# текущая папка с видео; меняется через CLI/env или из интерфейса
state = {"media_dir": None}


def set_media_dir(path):
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise NotADirectoryError(p)
    state["media_dir"] = p
    return p


def media_dir():
    return state["media_dir"]


def find_video(directory):
    videos = sorted(p for p in directory.iterdir() if p.suffix.lower() in VIDEO_EXTS)
    return videos[0] if videos else None


def lang_from_name(stem, video_stem):
    # "Title.en" -> "en"; запасной разбор по последнему сегменту через точку
    suffix = stem[len(video_stem):].lstrip(".") if stem.startswith(video_stem) else stem
    code = suffix.split(".")[-1] if "." in suffix else suffix
    return code or "sub"


def scan_media():
    directory = media_dir()
    video = find_video(directory)
    if video is None:
        return {"dir": str(directory), "video": None, "tracks": []}

    video_stem = video.stem
    tracks = []
    for vtt in sorted(directory.glob("*.vtt")):
        stem = vtt.name[: -len(".vtt")]
        code = lang_from_name(stem, video_stem)
        tracks.append(
            {
                "file": vtt.name,
                "lang": code,
                "label": LANG_LABELS.get(code.lower(), code.upper()),
            }
        )

    return {
        "dir": str(directory),
        "video": {"file": video.name, "title": video.stem},
        "tracks": tracks,
    }


@app.route("/")
def index():
    return render_template("index.html")


def find_free_port(host, start, attempts=20):
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise OSError(f"Свободный порт не найден в диапазоне {start}–{start + attempts - 1}")


@app.route("/api/media")
def api_media():
    return jsonify(scan_media())


@app.route("/api/folder", methods=["POST"])
def api_folder():
    path = (request.get_json(silent=True) or {}).get("path", "").strip()
    if not path:
        return jsonify({"error": "Не указан путь"}), 400
    try:
        set_media_dir(path)
    except NotADirectoryError:
        return jsonify({"error": f"Папка не найдена: {path}"}), 400
    return jsonify(scan_media())


@app.route("/media/<path:filename>")
def media(filename):
    directory = media_dir()
    target = (directory / filename).resolve()
    if directory not in target.parents or not target.is_file():
        abort(404)
    # conditional=True включает поддержку HTTP Range -> быстрая перемотка
    return send_from_directory(directory, filename, conditional=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Видеоплеер с транскриптом")
    parser.add_argument(
        "-d", "--dir",
        default=os.environ.get("MEDIA_DIR", BASE_DIR.parent / "output"),
        help="Папка с видео и субтитрами (по умолчанию ../output)",
    )
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    try:
        set_media_dir(args.dir)
    except NotADirectoryError:
        # папка может появиться/смениться позже из интерфейса
        state["media_dir"] = Path(args.dir).expanduser().resolve()
        print(f"⚠  Стартовая папка не найдена: {state['media_dir']}")

    host = "127.0.0.1"
    port = find_free_port(host, args.port)
    if port != args.port:
        print(f"⚠  Порт {args.port} занят, использую {port}")

    print(f"Папка с медиа: {media_dir()}")
    print(f"Открой в браузере: http://{host}:{port}")
    # use_reloader=False: иначе перезапуск Flask заново займёт уже выбранный порт
    app.run(host=host, port=port, debug=True, use_reloader=False)
