import argparse
import json
import os
import re
import socket
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory, abort

BASE_DIR = Path(__file__).resolve().parent
SKILL_CONFIG = BASE_DIR.parent / ".claude" / "skills" / "local-video"
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".m4v"}
_ID_IN_NAME = re.compile(r"\s*\[[^\[\]]+\]\s*$")

LANG_LABELS = {
    "en": "English", "ru": "Русский", "de": "Deutsch", "fr": "Français",
    "es": "Español", "it": "Italiano", "ja": "日本語", "zh": "中文",
}

app = Flask(__name__)

# library — корень библиотеки (экран списка); media_dir — открытое видео (None = список)
state = {"library": None, "media_dir": None}


# ---------- конфиг / библиотека ----------

def config_library():
    """Папка-библиотека из конфига скилла (config.json → example → дефолт)."""
    for name in ("config.json", "config.example.json"):
        p = SKILL_CONFIG / name
        try:
            if p.is_file():
                lib = json.loads(p.read_text(encoding="utf-8")).get("library")
                if lib:
                    return Path(lib).expanduser()
        except (json.JSONDecodeError, OSError):
            pass
    return Path("~/all-local-videos").expanduser()


def set_library(path):
    state["library"] = Path(path).expanduser().resolve()
    return state["library"]


def set_media_dir(path):
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise NotADirectoryError(p)
    state["media_dir"] = p
    return p


def read_sidecar(directory):
    p = directory / ".source.json"
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


# ---------- сканирование ----------

def find_video(directory):
    videos = sorted(p for p in directory.iterdir() if p.suffix.lower() in VIDEO_EXTS)
    return videos[0] if videos else None


def lang_from_name(stem, video_stem):
    suffix = stem[len(video_stem):].lstrip(".") if stem.startswith(video_stem) else stem
    code = suffix.split(".")[-1] if "." in suffix else suffix
    return code or "sub"


def list_library():
    lib = state["library"]
    videos = []
    if lib and lib.is_dir():
        dirs = [p for p in lib.iterdir() if p.is_dir()]
        for d in sorted(dirs, key=lambda p: p.stat().st_mtime, reverse=True):
            video = find_video(d)
            if video is None:
                continue
            sc = read_sidecar(d)
            title = (sc or {}).get("title") or _ID_IN_NAME.sub("", d.name)
            vs = video.stem
            langs = [
                LANG_LABELS.get(lang_from_name(v.name[: -len(".vtt")], vs).lower(),
                                lang_from_name(v.name[: -len(".vtt")], vs).upper())
                for v in sorted(d.glob("*.vtt"))
            ]
            videos.append({"dir": str(d), "title": title, "langs": langs})
    return {"library": str(lib) if lib else None, "videos": videos}


def scan_media():
    directory = state["media_dir"]
    if directory is None:
        return {"current": None}
    video = find_video(directory)
    if video is None:
        return {"current": str(directory), "video": None, "tracks": []}

    video_stem = video.stem
    tracks = []
    for vtt in sorted(directory.glob("*.vtt")):
        stem = vtt.name[: -len(".vtt")]
        code = lang_from_name(stem, video_stem)
        summary = f"{stem}.summary.md"
        tracks.append({
            "file": vtt.name,
            "lang": code,
            "label": LANG_LABELS.get(code.lower(), code.upper()),
            "summary": summary if (directory / summary).is_file() else None,
        })
    sc = read_sidecar(directory)
    title = (sc or {}).get("title") or video.stem
    return {
        "current": str(directory),
        "video": {"file": video.name, "title": title},
        "tracks": tracks,
    }


# ---------- маршруты ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/library", methods=["GET", "POST"])
def api_library():
    if request.method == "POST":
        path = (request.get_json(silent=True) or {}).get("path", "").strip()
        if not path:
            return jsonify({"error": "Не указан путь"}), 400
        p = Path(path).expanduser()
        if not p.is_dir():
            return jsonify({"error": f"Папка не найдена: {path}"}), 400
        set_library(p)
        state["media_dir"] = None
    return jsonify(list_library())


@app.route("/api/media")
def api_media():
    return jsonify(scan_media())


@app.route("/api/open", methods=["POST"])
def api_open():
    path = (request.get_json(silent=True) or {}).get("dir", "").strip()
    if not path:
        return jsonify({"error": "Не указан путь"}), 400
    try:
        set_media_dir(path)
    except NotADirectoryError:
        return jsonify({"error": f"Папка не найдена: {path}"}), 400
    return jsonify(scan_media())


@app.route("/api/home", methods=["POST"])
def api_home():
    state["media_dir"] = None
    return jsonify(list_library())


@app.route("/media/<path:filename>")
def media(filename):
    directory = state["media_dir"]
    if directory is None:
        abort(404)
    target = (directory / filename).resolve()
    if directory not in target.parents or not target.is_file():
        abort(404)
    return send_from_directory(directory, filename, conditional=True)


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Видеоплеер с транскриптом")
    parser.add_argument("--library", default=os.environ.get("LIBRARY"),
                        help="корень библиотеки (по умолчанию из конфига скилла)")
    parser.add_argument("-d", "--dir", default=os.environ.get("MEDIA_DIR"),
                        help="открыть сразу одну папку с видео (минуя список)")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    set_library(args.library or config_library())
    if args.dir:
        try:
            set_media_dir(args.dir)
        except NotADirectoryError:
            state["media_dir"] = Path(args.dir).expanduser().resolve()
            print(f"⚠  Папка не найдена: {state['media_dir']}")

    host = "127.0.0.1"
    port = find_free_port(host, args.port)
    if port != args.port:
        print(f"⚠  Порт {args.port} занят, использую {port}")

    print(f"Библиотека: {state['library']}")
    print(f"Открой в браузере: http://{host}:{port}")
    app.run(host=host, port=port, debug=True, use_reloader=False)
