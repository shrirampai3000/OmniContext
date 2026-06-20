# OmniContext

OmniContext is a local-first ambient memory layer for Windows. It continuously builds a searchable, highly contextual memory of your digital activity by combining sparse screenshot captures with underlying system signals.

Operating entirely on your local machine, OmniContext captures context-aware snapshots, performs Optical Character Recognition (OCR), generates activity summaries using local Large Language Models (LLMs) via Ollama, and stores high-dimensional embeddings in FAISS. The system exposes a comprehensive REST API alongside a lightweight NiceGUI interface for retrieval and timeline visualization.

 OmniContext respects user privacy by design: no video is recorded, no cloud APIs are utilized, and all data remains strictly within your local environment.

## Key Features

- **Intelligent Activity Capture:** Automatically captures context based on active window changes, clipboard modifications, and periodic intervals tied to user activity.
- **Strict Privacy Controls:** Supports exclusion lists for password managers, private browsing sessions, and custom process or window title fragments. Capture can be paused entirely or disabled for specific modalities like the clipboard.
- **Local AI Pipeline:** Integrates seamlessly with EasyOCR for text extraction, Ollama for summarization, and SentenceTransformers for generating embeddings.
- **Hybrid Retrieval Engine:** Combines keyword search (SQLite FTS5) with semantic vector search (FAISS) using Reciprocal Rank Fusion (RRF), further optimized with recency boosting.
- **Premium UI:** Features a beautifully designed, desktop-style web interface using a pristine light-mode glassmorphism aesthetic, backed by a fully documented REST API.

## System Requirements

- **Operating System:** Windows 10 or Windows 11
- **Runtime:** Python 3.10 or higher
- **Optional Dependencies:** Ollama (highly recommended for local AI summarization and embedding generation)

### Recommended Ollama Models

```powershell
ollama pull llava
ollama pull mistral
```

*Note: If Ollama, EasyOCR, or SentenceTransformers are unavailable, the system will fall back to available capabilities. Initial model downloads may require significant bandwidth.*

## Installation

```powershell
cd D:\OmniContext
python -m pip install -e .
```

## Usage

Start the application using the provided batch script:

```powershell
scripts\run.bat
```

Alternatively, run the Python module directly:

```powershell
python main.py
```

### Privacy-First Initialization

To launch the application with capturing disabled by default, set the appropriate environment variable prior to execution:

```powershell
$env:OMNICONTEXT_START_PAUSED = "1"
scripts\run.bat
```

### Accessing the Interface

Once running, the web interface and API documentation are accessible locally:

- **User Interface:** `http://127.0.0.1:7071`
- **REST API Base URL:** `http://127.0.0.1:7071/api`
- **Swagger Documentation:** `http://127.0.0.1:7071/api/docs`

**Global UI Hotkey:** `Ctrl+Shift+Space`
*(Depending on system configuration, the hotkey listener may require elevated administrative privileges.)*

## Testing

Execute the automated test suite using the provided script:

```powershell
scripts\test.bat
```

The smoke tests utilize temporary databases and vector indexes, ensuring they run independently of live system captures or heavy machine learning models.

## API Reference

The REST API exposes the following core endpoints under `/api`:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/search` | Execute a hybrid (keyword + semantic) search query. |
| `GET` | `/api/events` | Retrieve paginated events, optionally filtered by session. |
| `GET` | `/api/events/{id}` | Retrieve metadata for a specific event. |
| `GET` | `/api/events/{id}/screenshot` | Retrieve the WebP screenshot associated with an event. |
| `DELETE` | `/api/events/{id}` | Permanently delete an event, its screenshot, and associated metadata. |
| `GET` | `/api/sessions` | Retrieve paginated user sessions. |
| `GET` | `/api/status` | Retrieve system health, capture state, and pipeline queue status. |
| `POST` | `/api/control/pause` | Suspend the activity capture monitor. |
| `POST` | `/api/control/resume` | Resume the activity capture monitor. |
| `GET` | `/api/settings` | Retrieve current application settings. |
| `PATCH` | `/api/settings` | Update persistent application settings. |

## Configuration Management

Settings are managed via the web interface and persisted locally to `settings.json`. Core architectural paths and static defaults are defined within `config.py`.

The following parameters can be configured dynamically at runtime:

| Parameter | Default | Description |
|---|---:|---|
| `capture_interval_seconds` | `90` | Interval between periodic screenshots during active usage. |
| `idle_threshold_seconds` | `120` | Duration of inactivity required to suspend periodic captures. |
| `screenshot_quality` | `75` | Compression quality for WebP screenshots (1-100). |
| `excluded_apps` | `[...]` | Process names to strictly ignore during capture. |
| `excluded_titles` | `[...]` | Window titles to strictly ignore during capture. |
| `ollama_base_url` | `http://localhost:11434` | Endpoint for the local Ollama instance. |
| `ollama_vision_model` | `llava` | Vision model used for multimodal context extraction. |
| `ollama_text_model` | `mistral` | Fallback text model used for summarization. |
| `clipboard_capture_enabled` | `False` | Determines whether clipboard contents are stored. |
| `capture_paused_on_startup` | `True` | Initializes the monitor in a suspended state. |

## Storage Architecture

By default, all application data is stored securely within the user's Local App Data directory to ensure isolation from the source repository.

**Path:** `%LOCALAPPDATA%\OmniContext\`

```text
%LOCALAPPDATA%\OmniContext\
├── omnicontext.db      # SQLite database containing events, sessions, and the FTS index
├── faiss.index         # FAISS vector index for semantic search
├── faiss_meta.json     # Metadata mapping FAISS row indices to event IDs
├── settings.json       # Persistent user configuration state
└── screenshots/        # Directory containing compressed WebP captures
```

## System Architecture

The application pipeline is designed for asynchronous, non-blocking execution:

```text
Activity Monitor (Producer)
 └─> Raw event captured -> Stored in SQLite
 └─> Enqueued in processing queue
       │
       v
AI Pipeline Worker (Consumer)
 └─> OCR Extraction (EasyOCR)
 └─> Multimodal Summarization (Ollama)
 └─> Vector Embedding Generation (SentenceTransformers)
 └─> Update SQLite & Append to FAISS Index
       │
       v
Retrieval Layer
 └─> Hybrid Search (Keyword + Semantic)
 └─> Served via FastAPI & NiceGUI UI (Port 7071)
```

## Repository Structure

```text
OmniContext/
├── pyproject.toml          # Project configuration and dependency specifications
├── main.py                 # Application entry point and service orchestrator
├── config.py               # Static constants and default configuration values
├── scripts/                # Utility scripts for execution, linting, and testing
├── api/
│   └── routes.py           # FastAPI controller definitions
├── capture/
│   ├── monitor.py          # Activity monitor for window and clipboard changes
│   ├── screenshot.py       # WebP screen capture utilities
│   └── session.py          # Temporal session grouping logic
├── pipeline/
│   ├── ocr.py              # Optical Character Recognition module
│   ├── summarizer.py       # LLM summarization integration
│   ├── embedder.py         # Embedding generation module
│   └── processor.py        # Background worker for the AI pipeline
├── search/
│   └── retrieval.py        # Implementation of Hybrid Search and RRF
├── storage/
│   ├── database.py         # SQLite connection and FTS operations
│   ├── models.py           # Pydantic data schemas
│   ├── settings.py         # Persistent configuration manager
│   └── vector_store.py     # FAISS index wrapper
├── ui/
│   ├── app.py              # NiceGUI frontend components
│   └── styles.css          # Core stylesheet
└── tests/
    └── test_core.py        # Automated test suite
```
