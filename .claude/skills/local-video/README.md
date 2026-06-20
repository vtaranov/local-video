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
| `library.py {index\|folder\|sidecar}` | имя папки `<title> [id]`, метаданные источника `.source.json`, дедуп по id | JSON |
| `list_playlist.py <url>` | перечислить видео плейлиста/канала без скачивания | JSON |
| `download_video.py <url> --out DIR` | скачать видео | `{video_path}` |
| `fetch_subs.py <url> --langs en,es --out DIR [--auto]` | скачать субтитры → `.vtt` | `{files}` |
| `transcribe.py <media> --out FILE.vtt [--model medium] [--lang en]` | транскрипция Whisper | `{subtitle_path, language}` |
| `translate.py <in> --out OUT.vtt [--model gemma4:latest]` | перевод на русский | `{output_path}` |
| `summarize.py <in> --out OUT.md [--model gemma4:latest] [--lang ru]` | саммари транскрипта (Markdown, на его языке) | `{output_path}` |
| `download_model.py [--size small] [--out DIR] [--source modelscope\|hf-mirror\|hf]` | скачать CT2-модель faster-whisper | `{model_dir, source}` |
| `config.py` | напечатать итоговую конфигурацию (дефолты + config.json) | JSON |
| `play.py` | найти веб-плеер (`player/`) и интерпретатор для запуска | JSON |

`subs.py` — общий модуль: парсинг `.srt`/`.vtt`, сборка `.vtt`, детект языка.
Запускать скрипты из каталога `scripts/` (там лежит `subs.py`).

## Структура папки видео

Каждое видео — в своей подпапке `<library>/<title> [id]/`:

```
Andrej Karpathy_ From Vibe Coding... [96jN2OCOfLs]/
├── Andrej Karpathy_ ....mp4                    # видео
├── Andrej Karpathy_ ....en-orig.vtt            # субтитры, оригинал
├── Andrej Karpathy_ ....ru.vtt                 # субтитры, перевод
├── Andrej Karpathy_ ....en-orig.summary.md     # саммари (на языке оригинала)
├── Andrej Karpathy_ ....ru.summary.md          # саммари (на русском)
└── .source.json                                # метаданные источника
```

`.source.json` — сопроводительный файл (не видео, не субтитры), создаётся
`library.py sidecar` на последнем шаге пайплайна. Хранит `id`, `url`, `title`,
`extractor` и дату обработки. По нему, а не по совпадению названия, скрипт
определяет «это видео уже скачано» — на нём держится дедупликация при повторных
запусках и в пакетном режиме (плейлист/канал).

## Принципы

- Видео качается всегда; выходная папка задаётся аргументом.
- Субтитры на выходе всегда `.vtt`; вход — `.srt` и `.vtt`.
- Без hardsub. Перевод локальный (Ollama), без облачных API.

Полная инструкция по работе — в `SKILL.md`.
