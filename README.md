# OmniContext

Local-first Windows ambient memory: sparse screenshots plus lightweight activity
signals become searchable memories you can query later.

OmniContext runs on your machine, captures context-aware snapshots, extracts text,
summarises activity with local Ollama models when available, stores embeddings in
FAISS, and exposes a small NiceGUI interface plus a REST API.

No video. No cloud API required. No continuous recording. Data stays under
`data/` in this project folder.

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
python -m pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

To start the UI/API without capturing immediately:

```powershell
$env:OMNICONTEXT_START_PAUSED = "1"
python main.py
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
python -m pytest -q
```

The smoke tests use temporary databases and vector indexes. They do not require
live screenshots, Ollama, EasyOCR model downloads, or the embedding model.

## API Reference

All routes are mounted under `/api`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/query` | Hybrid search query |
| `GET` | `/api/events` | List events, optionally by session |
| `GET` | `/api/events/{id}` | Get one event |
| `GET` | `/api/events/{id}/screenshot` | Serve event screenshot |
| `DELETE` | `/api/events/{id}` | Delete event, screenshot, FTS row, and vector metadata |
| `GET` | `/api/sessions` | List sessions |
| `GET` | `/api/status` | System status |
| `POST` | `/api/capture/pause` | Pause capture |
| `POST` | `/api/capture/resume` | Resume capture |
| `GET` | `/api/settings` | Read runtime settings |
| `PATCH` | `/api/settings` | Update runtime settings until restart |

Example query:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:7071/api/query `
  -ContentType application/json `
  -Body '{"query":"what did I work on today?","top_k":10}'
```

## Configuration

Edit `config.py` for permanent changes. The Settings tab and
`PATCH /api/settings` update runtime values until restart.

Common settings:

| Setting | Default | Description |
|---|---:|---|
| `CAPTURE_INTERVAL_SECONDS` | `90` | Periodic screenshot interval |
| `IDLE_THRESHOLD_SECONDS` | `120` | Skip periodic capture after this idle time |
| `SCREENSHOT_QUALITY` | `75` | WebP screenshot quality |
| `EXCLUDED_APPS` | list | Process-name fragments that are never captured |
| `EXCLUDED_TITLES` | list | Window-title fragments that are never captured |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local Ollama endpoint |
| `OLLAMA_VISION_MODEL` | `llava` | Vision model for screenshot summaries |
| `OLLAMA_TEXT_MODEL` | `mistral` | Text fallback model |
| `OCR_GPU` | `False` | Enable GPU for EasyOCR |
| `HOTKEY` | `ctrl+shift+space` | Global UI hotkey |

## Data Location

```text
data/
  omnicontext.db      SQLite events, sessions, and FTS index
  faiss.index         FAISS vector index
  faiss_meta.json     FAISS row to event ID mapping
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
  main.py                 Entry point
  config.py               Settings
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
  storage/vector_store.py FAISS wrapper
  ui/app.py               NiceGUI frontend
  tests/test_core.py      Smoke tests
```
