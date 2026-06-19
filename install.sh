#!/usr/bin/env bash
# Установка local-video: конфиг из шаблона + глобальный доступ к скиллу + проверка окружения.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_SRC="$REPO/.claude/skills/local-video"
SKILL_DST_DIR="$HOME/.claude/skills"
SKILL_DST="$SKILL_DST_DIR/local-video"
CONFIG="$SKILL_SRC/config.json"
CONFIG_EXAMPLE="$SKILL_SRC/config.example.json"

echo "local-video · установка"
echo "репозиторий: $REPO"
echo

# 1. config.json из шаблона
if [ -f "$CONFIG" ]; then
  echo "✓ config.json уже есть — не трогаю"
else
  cp "$CONFIG_EXAMPLE" "$CONFIG"
  echo "✓ создан config.json из шаблона — при необходимости отредактируй пути под себя"
fi

# 2. глобальный доступ к скиллу (симлинк в ~/.claude/skills)
mkdir -p "$SKILL_DST_DIR"
if [ -L "$SKILL_DST" ]; then
  ln -sfn "$SKILL_SRC" "$SKILL_DST"
  echo "✓ симлинк обновлён: $SKILL_DST → $SKILL_SRC"
elif [ -e "$SKILL_DST" ]; then
  echo "⚠ $SKILL_DST существует и это не симлинк — пропускаю."
  echo "  Удали его вручную, если нужен глобальный доступ к скиллу."
else
  ln -s "$SKILL_SRC" "$SKILL_DST"
  echo "✓ скилл доступен глобально: $SKILL_DST → $SKILL_SRC"
fi

# 3. настройка плеера (venv + Flask)
PLAYER="$REPO/player"
if [ -f "$PLAYER/requirements.txt" ]; then
  echo
  if [ ! -x "$PLAYER/venv/bin/python" ]; then
    echo "плеер: создаю venv…"
    python3 -m venv "$PLAYER/venv"
  fi
  if "$PLAYER/venv/bin/python" -m pip install -q -r "$PLAYER/requirements.txt"; then
    echo "✓ плеер готов (venv + Flask)"
  else
    echo "⚠ не удалось установить зависимости плеера ($PLAYER/requirements.txt)"
  fi
fi

# 4. проверка окружения
echo
echo "проверка окружения:"
check() { if command -v "$1" >/dev/null 2>&1; then echo "  ✓ $1"; else echo "  ✗ $1 — $2"; fi; }
check python3 "установи Python 3.10+"
check ffmpeg  "brew install ffmpeg  /  apt install ffmpeg"
check ollama  "https://ollama.com, затем: ollama pull <модель>"

if python3 -c "import yt_dlp, faster_whisper, langdetect" >/dev/null 2>&1; then
  echo "  ✓ python-зависимости"
else
  echo "  ✗ python-зависимости — pip install -r \"$SKILL_SRC/requirements.txt\""
fi

# 5. модель faster-whisper
MODEL_DIR="$(python3 "$SKILL_SRC/scripts/config.py" 2>/dev/null \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['whisper_model_dir'])" 2>/dev/null || true)"
if [ -n "${MODEL_DIR:-}" ] && [ -f "$MODEL_DIR/model.bin" ]; then
  echo "  ✓ модель faster-whisper: $MODEL_DIR"
else
  echo "  ✗ модель faster-whisper не найдена: ${MODEL_DIR:-?}"
  echo "    скачай её командой:  python3 \"$SKILL_SRC/scripts/download_model.py\""
  echo "    (или поправь whisper_model_dir в config.json)"
fi

echo
echo "готово."
