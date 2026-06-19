# local-video (skill)

Claude Code Skill: скачивание видео с YouTube и получение субтитров на русском.
Оркеструет Claude в интерактивном режиме; скрипты выполняют детерминированные операции.

## Установка зависимостей

```bash
# системно
brew install ffmpeg

# python (в активном окружении)
pip install -r requirements.txt

# модель перевода
ollama pull gemma4:latest      # уже установлена
```

## Скрипты (`scripts/`)

| Скрипт | Назначение | Вывод |
|---|---|---|
| `probe.py <url>` | метаданные (`id`, `extractor`, `title`, …) + дорожки субтитров | JSON |
| `library.py {index\|folder\|sidecar}` | имя папки `<title> [id]`, провенанс `.source.json`, дедуп по id | JSON |
| `download_video.py <url> --out DIR` | скачать видео | `{video_path}` |
| `fetch_subs.py <url> --langs en,es --out DIR [--auto]` | скачать субтитры → `.vtt` | `{files}` |
| `transcribe.py <media> --out FILE.vtt [--model medium] [--lang en]` | транскрипция Whisper | `{subtitle_path, language}` |
| `translate.py <in> --out OUT.vtt [--model gemma4:latest]` | перевод на русский | `{output_path}` |
| `summarize.py <in> --out OUT.md [--model gemma4:latest] [--lang ru]` | саммари транскрипта (Markdown, на его языке) | `{output_path}` |
| `download_model.py [--size small] [--out DIR] [--source modelscope\|hf-mirror\|hf]` | скачать CT2-модель faster-whisper | `{model_dir, source}` |
| `config.py` | напечатать итоговую конфигурацию (дефолты + config.json) | JSON |

`subs.py` — общий модуль: парсинг `.srt`/`.vtt`, сборка `.vtt`, детект языка.
Запускать скрипты из каталога `scripts/` (там лежит `subs.py`).

## Принципы

- Видео качается всегда; выходная папка задаётся аргументом.
- Субтитры на выходе всегда `.vtt`; вход — `.srt` и `.vtt`.
- Без hardsub. Перевод локальный (Ollama), без облачных API.

Полная инструкция по работе — в `SKILL.md`.
