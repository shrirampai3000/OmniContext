# OmniContext

Local-first Windows ambient memory: sparse screenshots plus lightweight activity
signals become searchable memories you can query later.

OmniContext runs on your machine, captures context-aware snapshots, extracts text,
summarises activity with local Ollama models when available, stores embeddings in
FAISS, and exposes a small NiceGUI interface plus a REST API.

No video. No cloud API required. No continuous recording. Data stays in your 
local application data folder.

## Features

- Smart capture from active-window changes, clipboard changes, and periodic
  intervals while you are active.
- Privacy exclusions for password managers, private browsing windows, and any
  custom process/title fragments you add.
- Local AI pipeline: screenshot OCR, Ollama summarisation, sentence-transformer
  embeddings, SQLite FTS5, and FAISS vector search.
- Hybrid retrieval with keyword search, vector search, reciprocal-rank fusion,
  and recency boosting.
- NiceGUI desktop-style UI for search, timeline, sessions, capture control, and
  runtime settings.
- REST API under `/api` for search, event browsing, screenshots, deletes,
  status, capture pause/resume, and settings.

## Prerequisites

- Windows 10/11
- Python 3.10+
- Ollama, optional but recommended for AI summaries

Optional Ollama models:

```powershell
ollama pull llava
ollama pull mistral
```

If Ollama, EasyOCR, or sentence-transformers are unavailable, OmniContext falls
back gracefully where possible. First model downloads can be large.

## Install

```powershell
cd D:\OmniContext
python -m pip install -e .
```

## Run

```powershell
scripts\run.bat
```

Or run directly:

```powershell
python main.py
```

To start the UI/API without capturing immediately:

```powershell
$env:OMNICONTEXT_START_PAUSED = "1"
scripts\run.bat
```

The UI opens at:

```text
http://127.0.0.1:7071
```

Useful URLs:

- UI: `http://127.0.0.1:7071`
- API base: `http://127.0.0.1:7071/api`
- API docs: `http://127.0.0.1:7071/api/docs`

Global hotkey:

```text
Ctrl+Shift+Space
```

On some Windows setups, the hotkey package requires running the terminal as
Administrator.

## Test

```powershell
scripts\test.bat
```

The smoke tests use temporary databases and vector indexes. They do not require
live screenshots, Ollama, EasyOCR model downloads, or the embedding model.

## API Reference

All routes are mounted under `/api`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/search` | Hybrid search query |
| `GET` | `/api/events` | List events, optionally by session |
| `GET` | `/api/events/{id}` | Get one event |
| `GET` | `/api/events/{id}/screenshot` | Serve event screenshot |
| `DELETE` | `/api/events/{id}` | Delete event, screenshot, FTS row, and vector metadata |
| `GET` | `/api/sessions` | List sessions |
| `GET` | `/api/status` | System status |
| `POST` | `/api/control/pause` | Pause capture |
| `POST` | `/api/control/resume` | Resume capture |
| `GET` | `/api/settings` | Read runtime settings |
| `PATCH` | `/api/settings` | Update persistent settings |

## Configuration

Settings are managed via the UI Settings tab and persisted to `settings.json` 
in the data directory. `config.py` contains core configuration paths and defaults.

Common settings configurable via the UI or `PATCH /api/settings`:

| Setting | Default | Description |
|---|---:|---|
| `capture_interval_seconds` | `90` | Periodic screenshot interval |
| `idle_threshold_seconds` | `120` | Skip periodic capture after this idle time |
| `screenshot_quality` | `75` | WebP screenshot quality |
| `excluded_apps` | list | Process-name fragments that are never captured |
| `excluded_titles` | list | Window-title fragments that are never captured |
| `ollama_base_url` | `http://localhost:11434` | Local Ollama endpoint |
| `ollama_vision_model` | `llava` | Vision model for screenshot summaries |
| `ollama_text_model` | `mistral` | Text fallback model |
| `clipboard_capture_enabled` | `False` | Capture text copied to clipboard |
| `capture_paused_on_startup` | `True` | Do not capture until explicitly resumed |

## Data Location

By default, data is stored in the user's Local App Data directory:
`%LOCALAPPDATA%\OmniContext\`

```text
%LOCALAPPDATA%\OmniContext\
  omnicontext.db      SQLite events, sessions, and FTS index
  faiss.index         FAISS vector index
  faiss_meta.json     FAISS row to event ID mapping
  settings.json       Persistent application settings
  screenshots/        WebP captures
```

## Architecture

```text
Capture monitor
  -> raw event in SQLite
  -> pipeline queue
  -> OCR + summarise + embed
  -> SQLite + FAISS
  -> hybrid retrieval
  -> FastAPI routes mounted inside NiceGUI
  -> NiceGUI UI on port 7071
```

## Project Structure

```text
OmniContext/
  pyproject.toml          Project metadata and dependencies
  main.py                 Entry point
  config.py               Static settings and defaults
  scripts/                Batch scripts for running and testing
  api/routes.py           FastAPI routes
  capture/monitor.py      Window, clipboard, and activity watcher
  capture/screenshot.py   WebP screenshot capture
  capture/session.py      Session grouping
  pipeline/ocr.py         EasyOCR wrapper
  pipeline/summarizer.py  Ollama summariser
  pipeline/embedder.py    sentence-transformers wrapper
  pipeline/processor.py   Background AI pipeline worker
  search/retrieval.py     Hybrid search
  storage/database.py     SQLite + FTS5
  storage/models.py       Pydantic models
  storage/settings.py     Persistent settings manager
  storage/vector_store.py FAISS wrapper
  ui/app.py               NiceGUI frontend
  ui/styles.css           Frontend stylesheet
  tests/test_core.py      Smoke tests
```
