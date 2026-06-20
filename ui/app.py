"""
OmniContext — NiceGUI app (search overlay + timeline + settings).
"""

import asyncio
import base64
import logging
import threading
from datetime import datetime
from html import escape
from pathlib import Path
from typing import List, Optional

import httpx
from nicegui import app as nicegui_app, ui

from config import APP_NAME, HOTKEY, UI_PORT

logger = logging.getLogger(__name__)
API_BASE = f"http://127.0.0.1:{UI_PORT}/api"


# ── Helpers ───────────────────────────────────────────────────────────────

async def _api(method: str, path: str, **kwargs):
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await getattr(client, method)(f"{API_BASE}{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()


def _fmt_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %H:%M")
    except Exception:
        return iso[:16]


def _screenshot_src(event_id: str) -> str:
    return f"{API_BASE}/events/{event_id}/screenshot"


# ── CSS ───────────────────────────────────────────────────────────────────

GLOBAL_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

:root {
    --bg: #0d0f14;
    --surface: #161a23;
    --surface2: #1e2330;
    --border: #2a3045;
    --accent: #6366f1;
    --accent-glow: rgba(99,102,241,0.25);
    --text: #e8eaf0;
    --text-muted: #7a829a;
    --success: #22c55e;
    --warning: #f59e0b;
    --danger: #ef4444;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: 'Inter', sans-serif;
    background: var(--bg);
    color: var(--text);
}

.oc-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    transition: border-color .2s, box-shadow .2s;
    cursor: pointer;
}
.oc-card:hover {
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent-glow), 0 4px 20px rgba(0,0,0,.4);
}

.oc-pill {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 3px 10px;
    font-size: 11px;
    color: var(--text-muted);
    display: inline-block;
}

.oc-pill-accent {
    background: var(--accent-glow);
    border-color: var(--accent);
    color: var(--accent);
}

.search-input {
    background: var(--surface2) !important;
    border: 1.5px solid var(--border) !important;
    border-radius: 10px !important;
    color: var(--text) !important;
    font-size: 16px !important;
}
.search-input:focus-within {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-glow) !important;
}

.oc-tab {
    color: var(--text-muted);
    font-size: 13px;
    font-weight: 500;
    padding: 8px 16px;
    border-radius: 8px;
    cursor: pointer;
    transition: all .15s;
    border: none;
    background: transparent;
}
.oc-tab:hover { color: var(--text); background: var(--surface2); }
.oc-tab.active { color: var(--accent); background: var(--accent-glow); }

.status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    display: inline-block;
}
.status-dot.active { background: var(--success); box-shadow: 0 0 6px var(--success); }
.status-dot.paused { background: var(--warning); }

.sidebar {
    background: var(--surface);
    border-right: 1px solid var(--border);
    min-height: 100vh;
    width: 220px;
    padding: 24px 16px;
    position: fixed;
    left: 0; top: 0;
}

.main-content {
    margin-left: 220px;
    padding: 32px;
    min-height: 100vh;
}

.thumb {
    width: 120px;
    height: 75px;
    object-fit: cover;
    border-radius: 6px;
    border: 1px solid var(--border);
    flex-shrink: 0;
}

.score-bar {
    height: 3px;
    border-radius: 2px;
    background: linear-gradient(90deg, var(--accent), #818cf8);
}

.empty-state {
    text-align: center;
    padding: 80px 40px;
    color: var(--text-muted);
}

.section-title {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: var(--text-muted);
    margin-bottom: 12px;
}

.modal-overlay {
    position: fixed; inset: 0;
    background: rgba(0,0,0,.7);
    backdrop-filter: blur(4px);
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
}

.modal-box {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 24px;
    max-width: 900px;
    width: 90vw;
    max-height: 80vh;
    overflow-y: auto;
}
"""


# ── State ─────────────────────────────────────────────────────────────────

class AppState:
    def __init__(self):
        self.results: List[dict] = []
        self.status: dict = {}
        self.active_tab = "search"
        self.modal_event: Optional[dict] = None


# ── Page builder ──────────────────────────────────────────────────────────

def build_ui():
    state = AppState()

    ui.add_head_html(f"<style>{GLOBAL_CSS}</style>")

    # ── Sidebar ───────────────────────────────────────────────────────────
    with ui.element("div").classes("sidebar"):
        ui.label("OmniContext").style(
            "font-size:18px;font-weight:700;color:#e8eaf0;margin-bottom:8px"
        )
        ui.label("ambient memory").style(
            "font-size:11px;color:#6366f1;margin-bottom:32px"
        )

        status_html = ui.html("", sanitize=False).style("margin-bottom:24px")

        nav_items = [
            ("brain", "🧠  Brain"),
            ("search", "🔍  Search"),
            ("timeline", "📋  Timeline"),
            ("sessions", "📂  Sessions"),
            ("settings", "⚙️  Settings"),
        ]

        nav_labels: dict = {}
        for tab_id, label in nav_items:
            btn = ui.button(label).props("flat").style(
                "width:100%;text-align:left;justify-content:flex-start;"
                "padding:10px 12px;border-radius:8px;font-size:13px;"
                "color:#7a829a;font-weight:500;transition:all .15s;"
            )
            nav_labels[tab_id] = btn

        main_area = ui.element("div").classes("main-content")

    # ── Status refresh ────────────────────────────────────────────────────
    async def refresh_status():
        try:
            s = await _api("get", "/status")
            state.status = s
            capturing = s.get("capturing", False)
            dot_color = "#22c55e" if capturing else "#f59e0b"
            status_label = "Capturing" if capturing else "Paused"
            events = s.get("event_count", 0)
            ollama = "✓ Ollama" if s.get("ollama_available") else "✗ Ollama"
            status_html.set_content(f"""
                <div style="font-size:12px;color:#7a829a;line-height:2">
                    <span style="color:{dot_color}">●</span> {status_label}<br>
                    {events:,} memories<br>
                    {s.get('session_count',0)} sessions<br>
                    <span style="color:{'#22c55e' if s.get('ollama_available') else '#ef4444'}">{ollama}</span>
                </div>
            """)
        except Exception:
            status_html.set_content('<div style="font-size:12px;color:#ef4444">● API offline</div>')

    # ── Tab switching ─────────────────────────────────────────────────────
    def switch_tab(tab_id: str):
        state.active_tab = tab_id
        for tid, btn in nav_labels.items():
            color = "#6366f1" if tid == tab_id else "#7a829a"
            bg = "rgba(99,102,241,.15)" if tid == tab_id else "transparent"
            btn.style(
                f"width:100%;text-align:left;justify-content:flex-start;"
                f"padding:10px 12px;border-radius:8px;font-size:13px;"
                f"color:{color};font-weight:500;background:{bg};transition:all .15s;"
            )
        main_area.clear()
        with main_area:
            if tab_id == "brain":
                build_brain_tab(state)
            elif tab_id == "search":
                build_search_tab(state)
            elif tab_id == "timeline":
                build_timeline_tab(state)
            elif tab_id == "sessions":
                build_sessions_tab(state)
            elif tab_id == "settings":
                build_settings_tab(state)

    for tab_id, _ in nav_items:
        nav_labels[tab_id].on("click", lambda t=tab_id: switch_tab(t))

    # Initial render
    with main_area:
        build_brain_tab(state)
    switch_tab("brain")

    # Status timer
    ui.timer(5.0, refresh_status)
    ui.timer(0.1, refresh_status, once=True)


# ── Search tab ────────────────────────────────────────────────────────────

def build_search_tab(state: AppState):
    query_val = {"v": ""}
    results_container = None

    ui.label("Search your memory").style(
        "font-size:28px;font-weight:700;margin-bottom:8px"
    )
    ui.label("Ask anything about what you were doing").style(
        "font-size:14px;color:#7a829a;margin-bottom:32px"
    )

    search_input = ui.input(placeholder="What were you working on yesterday?").style(
        "width:100%;max-width:720px;font-size:16px"
    ).props("outlined rounded")

    results_area = ui.element("div").style("margin-top:32px;max-width:900px")

    async def do_search():
        q = search_input.value.strip()
        if not q:
            return
        results_area.clear()
        with results_area:
            ui.label("Searching…").style("color:#7a829a")
        try:
            data = await _api("post", "/query", json={"query": q, "top_k": 10})
            results = data.get("results", [])
            results_area.clear()
            with results_area:
                if not results:
                    ui.html('<div class="empty-state"><div style="font-size:48px">🔍</div>'
                            '<div style="margin-top:16px;font-size:16px;font-weight:500">No memories found</div>'
                            '<div style="margin-top:8px;font-size:13px">Try different keywords</div></div>',
                            sanitize=False)
                    return
                ui.label(f"{len(results)} results").style(
                    "font-size:12px;color:#7a829a;margin-bottom:16px"
                )
                for r in results:
                    ev = r["event"]
                    score = r["score"]
                    _render_result_card(ev, score)
        except Exception as exc:
            results_area.clear()
            with results_area:
                ui.label(f"Search failed: {exc}").style("color:#ef4444")

    search_input.on("keydown.enter", do_search)

    with ui.row().style("gap:12px;margin-top:16px;flex-wrap:wrap"):
        for suggestion in ["What did I work on today?", "Show me browser sessions", "Find Python code"]:
            ui.button(suggestion).props("flat").style(
                "font-size:12px;color:#6366f1;border:1px solid rgba(99,102,241,.3);"
                "border-radius:20px;padding:4px 14px"
            ).on("click", lambda s=suggestion: (search_input.set_value(s), do_search()))


def _render_result_card(ev: dict, score: float):
    with ui.element("div").classes("oc-card").style("margin-bottom:12px;display:flex;gap:16px;align-items:flex-start"):
        # Thumbnail
        ev_id = ev.get("id", "")
        if ev.get("screenshot_path"):
            ui.html(
                f'<img src="{escape(_screenshot_src(ev_id), quote=True)}" class="thumb" '
                f'onerror="this.style.display=\'none\'">',
                sanitize=False,
            )

        with ui.element("div").style("flex:1;min-width:0"):
            # App + title
            app_name = ev.get("app_name", "")
            title = ev.get("window_title", "")
            with ui.row().style("align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap"):
                if app_name:
                    ui.html(
                        f'<span class="oc-pill oc-pill-accent">{escape(app_name[:30])}</span>',
                        sanitize=False,
                    )
                ui.label(title[:80]).style(
                    "font-size:14px;font-weight:600;color:#e8eaf0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                )

            # Summary
            summary = ev.get("summary", "")
            if summary:
                ui.label(summary[:200]).style("font-size:13px;color:#9ca3af;margin-bottom:8px;line-height:1.5")

            # Topics + time
            with ui.row().style("align-items:center;gap:8px;flex-wrap:wrap"):
                for topic in (ev.get("topics") or [])[:4]:
                    ui.html(f'<span class="oc-pill">{escape(str(topic))}</span>', sanitize=False)
                ts = _fmt_time(ev.get("timestamp", ""))
                ui.label(ts).style("font-size:11px;color:#4b5563;margin-left:auto")

            # Score bar
            bar_w = min(100, int(score * 500))
            ui.html(
                f'<div class="score-bar" style="width:{bar_w}%;margin-top:8px"></div>',
                sanitize=False,
            )


# ── Timeline tab ──────────────────────────────────────────────────────────

def build_timeline_tab(state: AppState):
    ui.label("Timeline").style("font-size:28px;font-weight:700;margin-bottom:8px")
    ui.label("Your recent captures in chronological order").style(
        "font-size:14px;color:#7a829a;margin-bottom:32px"
    )

    container = ui.element("div").style("max-width:900px")

    async def load_events():
        try:
            events = await _api("get", "/events", params={"limit": 50})
            container.clear()
            with container:
                if not events:
                    ui.html('<div class="empty-state"><div style="font-size:48px">📋</div>'
                            '<div style="margin-top:16px">No captures yet</div></div>',
                            sanitize=False)
                    return
                prev_day = None
                for ev in events:
                    ts = ev.get("timestamp", "")
                    try:
                        day = datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%A, %B %d")
                    except Exception:
                        day = ts[:10]
                    if day != prev_day:
                        ui.label(day).style(
                            "font-size:11px;font-weight:600;text-transform:uppercase;"
                            "letter-spacing:.08em;color:#6366f1;margin:24px 0 12px"
                        )
                        prev_day = day
                    _render_result_card(ev, 0)
        except Exception as exc:
            with container:
                ui.label(f"Failed to load: {exc}").style("color:#ef4444")

    ui.timer(0.1, load_events, once=True)


# ── Sessions tab ──────────────────────────────────────────────────────────

def build_sessions_tab(state: AppState):
    ui.label("Sessions").style("font-size:28px;font-weight:700;margin-bottom:8px")
    ui.label("Activity sessions grouped by context").style(
        "font-size:14px;color:#7a829a;margin-bottom:32px"
    )

    container = ui.element("div").style(
        "display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;max-width:1100px"
    )

    async def load_sessions():
        try:
            sessions = await _api("get", "/sessions", params={"limit": 50})
            container.clear()
            with container:
                if not sessions:
                    ui.html('<div class="empty-state" style="grid-column:1/-1">'
                            '<div style="font-size:48px">📂</div>'
                            '<div style="margin-top:16px">No sessions yet</div></div>',
                            sanitize=False)
                    return
                for s in sessions:
                    with ui.element("div").classes("oc-card"):
                        topic = s.get("topic") or "Unnamed Session"
                        ui.label(topic[:40]).style("font-size:15px;font-weight:600;margin-bottom:8px")
                        start = _fmt_time(s.get("start_time", ""))
                        ec = s.get("event_count", 0)
                        ui.label(f"{start}  ·  {ec} captures").style(
                            "font-size:12px;color:#7a829a"
                        )
                        if s.get("summary"):
                            ui.label(s["summary"][:120]).style(
                                "font-size:12px;color:#9ca3af;margin-top:8px;line-height:1.5"
                            )
        except Exception as exc:
            with container:
                ui.label(f"Failed: {exc}").style("color:#ef4444")

    ui.timer(0.1, load_sessions, once=True)


# ── Settings tab ──────────────────────────────────────────────────────────

def build_settings_tab(state: AppState):
    ui.label("Settings").style("font-size:28px;font-weight:700;margin-bottom:8px")
    ui.label("Configure OmniContext behaviour").style(
        "font-size:14px;color:#7a829a;margin-bottom:32px"
    )

    settings_data = {}

    async def load_settings():
        nonlocal settings_data
        try:
            settings_data = await _api("get", "/settings")
            render_settings(settings_data)
        except Exception as exc:
            ui.label(f"Failed to load settings: {exc}").style("color:#ef4444")

    container = ui.element("div").style("max-width:700px")

    def render_settings(s: dict):
        container.clear()
        with container:
            # Capture
            ui.label("Capture").classes("section-title").style("margin-top:0")
            with ui.element("div").classes("oc-card").style("margin-bottom:20px"):
                interval = ui.number(
                    label="Screenshot interval (seconds)",
                    value=s.get("capture_interval_seconds", 90),
                    min=10, max=600, step=10,
                ).style("width:100%;margin-bottom:12px")

                async def save_interval():
                    await _api("patch", "/settings",
                               json={"capture_interval_seconds": int(interval.value)})
                    ui.notify("Saved", type="positive", position="bottom-right")

                ui.button("Save", on_click=save_interval).props("flat").style(
                    "color:#6366f1;font-size:12px"
                )

            # Excluded apps
            ui.label("Excluded Apps").classes("section-title")
            with ui.element("div").classes("oc-card").style("margin-bottom:20px"):
                excluded_input = ui.input(
                    label="Process names (comma-separated)",
                    value=", ".join(s.get("excluded_apps", [])),
                ).style("width:100%;margin-bottom:12px")

                async def save_excluded():
                    apps = [a.strip() for a in excluded_input.value.split(",") if a.strip()]
                    await _api("patch", "/settings", json={"excluded_apps": apps})
                    ui.notify("Saved", type="positive", position="bottom-right")

                ui.button("Save", on_click=save_excluded).props("flat").style("color:#6366f1;font-size:12px")

            # AI
            ui.label("AI Models").classes("section-title")
            with ui.element("div").classes("oc-card").style("margin-bottom:20px"):
                vis_model = ui.input(
                    label="Ollama vision model",
                    value=s.get("ollama_vision_model", "llava"),
                ).style("width:100%;margin-bottom:12px")
                txt_model = ui.input(
                    label="Ollama text model",
                    value=s.get("ollama_text_model", "mistral"),
                ).style("width:100%;margin-bottom:12px")

                async def save_models():
                    await _api("patch", "/settings", json={
                        "ollama_vision_model": vis_model.value,
                        "ollama_text_model": txt_model.value,
                    })
                    ui.notify("Saved", type="positive", position="bottom-right")

                ui.button("Save", on_click=save_models).props("flat").style("color:#6366f1;font-size:12px")

            # Capture control
            ui.label("Capture Control").classes("section-title")
            with ui.row().style("gap:12px"):
                async def pause_cap():
                    await _api("post", "/capture/pause")
                    ui.notify("Capture paused", type="warning", position="bottom-right")

                async def resume_cap():
                    await _api("post", "/capture/resume")
                    ui.notify("Capture resumed", type="positive", position="bottom-right")

                ui.button("⏸ Pause Capture", on_click=pause_cap).style(
                    "background:#f59e0b;color:#000;border-radius:8px;padding:8px 16px;font-size:13px"
                )
                ui.button("▶ Resume Capture", on_click=resume_cap).style(
                    "background:#22c55e;color:#000;border-radius:8px;padding:8px 16px;font-size:13px"
                )

    ui.timer(0.1, load_settings, once=True)


# ── Entry point ───────────────────────────────────────────────────────────


# ── Brain tab ─────────────────────────────────────────────────────────────────

_WINDOW_COLORS = {
    "today":      {"accent": "#6366f1", "glow": "rgba(99,102,241,.18)", "label": "Today"},
    "this_week":  {"accent": "#22c55e", "glow": "rgba(34,197,94,.15)",  "label": "This Week"},
    "this_month": {"accent": "#f59e0b", "glow": "rgba(245,158,11,.15)", "label": "This Month"},
}


def _render_cluster_card(cluster: dict, accent: str, glow: str, on_click):
    name        = cluster.get("name", "")
    count       = cluster.get("event_count", 0)
    app         = cluster.get("dominant_app", "")
    co_entities = cluster.get("co_entities", [])

    with ui.element("div").style(
        f"background:#161a23;border:1px solid {accent};border-radius:12px;"
        f"padding:16px;cursor:pointer;transition:all .2s;"
        f"box-shadow:0 0 0 0 {glow};"
    ).on("click", on_click).on(
        "mouseenter", lambda e: None
    ):
        # Top row: name + count badge
        with ui.row().style("align-items:center;justify-content:space-between;margin-bottom:10px"):
            ui.label(name[:32]).style(
                f"font-size:15px;font-weight:600;color:#e8eaf0;"
                f"overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:160px"
            )
            ui.html(
                f'<span style="background:{glow};border:1px solid {accent};color:{accent};'
                f'border-radius:20px;padding:2px 10px;font-size:11px;font-weight:600">'
                f'{count} captures</span>'
            )

        # Dominant app
        if app:
            ui.label(app[:30]).style("font-size:11px;color:#7a829a;margin-bottom:8px")

        # Co-entity pills
        if co_entities:
            with ui.row().style("gap:6px;flex-wrap:wrap"):
                for co in co_entities[:4]:
                    ui.html(
                        f'<span style="background:#1e2330;border:1px solid #2a3045;'
                        f'border-radius:16px;padding:2px 8px;font-size:10px;color:#9ca3af">'
                        f'{co[:20]}</span>'
                    )

        # Accent bar
        ui.html(f'<div style="height:2px;border-radius:2px;background:{accent};margin-top:10px;opacity:.6"></div>')


def build_brain_tab(state: AppState):
    detail_container = None

    # ── Header ────────────────────────────────────────────────────────────
    with ui.row().style("align-items:center;justify-content:space-between;margin-bottom:4px"):
        ui.label("Your Digital Brain").style("font-size:28px;font-weight:700")

    ui.label("Your activity, auto-clustered by topic").style(
        "font-size:14px;color:#7a829a;margin-bottom:28px"
    )

    clusters_area = ui.element("div")
    detail_area   = ui.element("div").style("margin-top:32px;max-width:1000px")

    async def show_cluster_detail(entity_name: str):
        detail_area.clear()
        with detail_area:
            ui.label(f"Loading '{entity_name}'…").style("color:#7a829a;font-size:13px")
        try:
            data = await _api("get", f"/brain/cluster/{entity_name}")
            detail_area.clear()
            with detail_area:
                events = data.get("events", [])
                co     = data.get("co_entities", [])

                with ui.row().style("align-items:center;gap:12px;margin-bottom:16px"):
                    ui.label(f"📌 {entity_name}").style("font-size:20px;font-weight:700")
                    ui.label(f"{len(events)} captures").style(
                        "font-size:12px;color:#7a829a;background:#1e2330;"
                        "border-radius:20px;padding:3px 12px;border:1px solid #2a3045"
                    )

                if co:
                    with ui.row().style("gap:8px;margin-bottom:20px;flex-wrap:wrap"):
                        ui.label("Related:").style("font-size:12px;color:#7a829a;align-self:center")
                        for c in co:
                            ui.button(c[:24]).props("flat").style(
                                "font-size:11px;color:#6366f1;border:1px solid rgba(99,102,241,.3);"
                                "border-radius:20px;padding:2px 12px;height:auto"
                            ).on("click", lambda n=c: show_cluster_detail(n))

                ui.separator().style("margin-bottom:16px;border-color:#2a3045")

                if not events:
                    ui.html('<div class="empty-state"><div style="font-size:32px">🔍</div>'
                            '<div style="margin-top:12px">No memories yet for this topic</div></div>')
                    return

                for ev in events[:20]:
                    _render_result_card(ev, 0)

        except Exception as exc:
            detail_area.clear()
            with detail_area:
                ui.label(f"Failed: {exc}").style("color:#ef4444;font-size:13px")

    async def load_brain():
        clusters_area.clear()
        with clusters_area:
            ui.label("Loading your brain…").style("color:#7a829a;font-size:13px")
        try:
            data = await _api("get", "/brain")
            clusters_area.clear()
            with clusters_area:
                windows = [
                    ("today",      data.get("today",      [])),
                    ("this_week",  data.get("this_week",  [])),
                    ("this_month", data.get("this_month", [])),
                ]

                any_data = any(clusters for _, clusters in windows)
                if not any_data:
                    ui.html(
                        '<div class="empty-state">'
                        '<div style="font-size:48px">🧠</div>'
                        '<div style="margin-top:16px;font-size:16px;font-weight:500">Brain is empty</div>'
                        '<div style="margin-top:8px;font-size:13px;color:#7a829a">'
                        'Memories will appear here as OmniContext captures your activity.'
                        '</div></div>'
                    )
                    return

                # Three-column layout for time windows
                with ui.row().style("gap:24px;align-items:flex-start;flex-wrap:wrap"):
                    for window_key, clusters in windows:
                        cfg = _WINDOW_COLORS[window_key]
                        with ui.element("div").style("flex:1;min-width:240px"):
                            # Window header
                            ui.html(
                                f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;'
                                f'letter-spacing:.08em;color:{cfg["accent"]};margin-bottom:14px;'
                                f'display:flex;align-items:center;gap:8px">'
                                f'<span style="width:8px;height:8px;border-radius:50%;'
                                f'background:{cfg["accent"]};display:inline-block"></span>'
                                f'{cfg["label"]}'
                                f'</div>'
                            )
                            if not clusters:
                                ui.label("No activity yet").style("font-size:12px;color:#4b5563")
                            else:
                                for cluster in clusters:
                                    _render_cluster_card(
                                        cluster,
                                        accent=cfg["accent"],
                                        glow=cfg["glow"],
                                        on_click=lambda n=cluster["name"]: show_cluster_detail(n),
                                    )
                                    ui.element("div").style("height:10px")

        except Exception as exc:
            clusters_area.clear()
            with clusters_area:
                ui.label(f"Failed to load brain: {exc}").style("color:#ef4444;font-size:13px")

    ui.timer(0.1, load_brain, once=True)


def run_ui():
    @ui.page("/")
    def index():
        build_ui()

    ui.run(
        host="127.0.0.1",
        port=UI_PORT,
        title="OmniContext",
        favicon="🧠",
        dark=True,
        reload=False,
        show=True,
        show_welcome_message=False,
    )
