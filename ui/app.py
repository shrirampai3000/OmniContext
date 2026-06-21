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

def _safe_html(content="", **kwargs):
    return ui.html(content, sanitize=False, **kwargs)

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


# -- State -----------------------------------------------------------------

class AppState:
    def __init__(self):
        self.results: List[dict] = []
        self.status: dict = {}
        self.active_tab = "search"
        self.modal_event: Optional[dict] = None


# -- Page builder ----------------------------------------------------------

def build_ui():
    state = AppState()

    css_path = Path(__file__).parent / "styles.css"
    if css_path.exists():
        ui.add_head_html(f"<style>{css_path.read_text(encoding='utf-8')}</style>")

    # -- Sidebar -----------------------------------------------------------
    with ui.element("div").classes("sidebar"):
        with ui.row().style("align-items:center;gap:12px;margin-bottom:8px"):
            ui.icon("psychology").classes("text-gradient").style("font-size:28px;")
            ui.label("OmniContext").classes("text-gradient").style("font-size:22px;font-weight:800;letter-spacing:-0.02em;")
        
        ui.label("ambient memory").style(
            "font-size:12px;color:var(--text-muted);margin-bottom:32px;letter-spacing:0.1em;text-transform:uppercase;font-weight:600"
        )

        status_html = _safe_html("").style("margin-bottom:32px")

        nav_items = [
            ("brain", "psychology", "Brain"),
            ("search", "search", "Search"),
            ("timeline", "view_timeline", "Timeline"),
            ("sessions", "folder", "Sessions"),
            ("settings", "settings", "Settings"),
        ]

        nav_labels: dict = {}
        for tab_id, icon, label in nav_items:
            with ui.element("div").classes("oc-tab") as btn:
                ui.icon(icon).style("font-size:20px")
                ui.label(label).style("font-size:15px;font-weight:600")
            nav_labels[tab_id] = btn

    main_area = ui.element("div").classes("main-content")

    # ── Status refresh ────────────────────────────────────────────────────
    async def refresh_status():
        try:
            s = await _api("get", "/status")
            state.status = s
            capturing = s.get("capturing", False)
            dot_color = "var(--success)" if capturing else "var(--warning)"
            status_label = "Capturing" if capturing else "Paused"
            events = s.get("event_count", 0)
            ollama = "✓ Ollama" if s.get("ollama_available") else "✗ Ollama"
            status_html.set_content(f"""
                <div style="font-size:13px;color:var(--text-muted);line-height:2.2;font-weight:500">
                    <span class="status-dot {'active' if capturing else 'paused'}"></span> &nbsp;{status_label}<br>
                    <span style="color:var(--text-main)">{events:,}</span> memories<br>
                    <span style="color:var(--text-main)">{s.get('session_count',0)}</span> sessions<br>
                    <span style="color:{'var(--success)' if s.get('ollama_available') else 'var(--danger)'}">{ollama}</span>
                </div>
            """)
        except Exception:
            status_html.set_content('<div style="font-size:12px;color:#ef4444">● API offline</div>')

    # -- Tab switching -----------------------------------------------------
    def switch_tab(tab_id: str):
        state.active_tab = tab_id
        for tid, btn in nav_labels.items():
            if tid == tab_id:
                btn.classes(add="active")
            else:
                btn.classes(remove="active")
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

    for tab_id, _, _ in nav_items:
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

    ui.label("Search your memory").classes("text-gradient").style(
        "font-size:32px;font-weight:800;margin-bottom:8px"
    )
    ui.label("Ask anything about what you were doing").style(
        "font-size:14px;color:var(--text-muted);margin-bottom:40px"
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
                    _safe_html('<div class="empty-state"><div style="font-size:48px">🔍</div>'
                            '<div style="margin-top:16px;font-size:16px;font-weight:500">No memories found</div>'
                            '<div style="margin-top:8px;font-size:13px">Try different keywords</div></div>')
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


import subprocess
import os

def _open_event_modal(ev: dict):
    with ui.dialog() as dialog, ui.element("div").classes("modal-box"):
        ui.label("Memory Details").style("font-size:24px;font-weight:800;margin-bottom:20px")
        
        # Image
        ev_id = ev.get("id", "")
        if ev.get("screenshot_path"):
            src_escaped = escape(_screenshot_src(ev_id), quote=True)
            _safe_html(f'<a href="{src_escaped}" target="_blank"><img src="{src_escaped}" style="width:100%;border-radius:12px;margin-bottom:24px;border:1px solid var(--border);cursor:zoom-in"></a>')

        # Action Bar (Deep Links)
        file_path = ev.get("file_path", "")
        cwd = ev.get("cwd", "")
        url = ev.get("url", "")
        app_name = ev.get("app_name", "")
        repo = ev.get("repo", "")
        page_title = ev.get("page_title", "")
        
        # Context Overview
        with ui.column().style("gap:8px;margin-bottom:16px;background:var(--bg-base);padding:16px;border-radius:12px;border:1px solid var(--border)"):
            ui.label("Context Overview").style("font-size:14px;font-weight:700;color:var(--accent);margin-bottom:8px;text-transform:uppercase")
            if repo: _safe_html(f'<span style="color:var(--text-muted);font-weight:600;min-width:80px;display:inline-block">Repo:</span> {escape(repo)}')
            if file_path: _safe_html(f'<span style="color:var(--text-muted);font-weight:600;min-width:80px;display:inline-block">File:</span> {escape(file_path)}')
            if cwd: _safe_html(f'<span style="color:var(--text-muted);font-weight:600;min-width:80px;display:inline-block">Folder:</span> {escape(cwd)}')
            if page_title: _safe_html(f'<span style="color:var(--text-muted);font-weight:600;min-width:80px;display:inline-block">Page:</span> {escape(page_title)}')
            _safe_html(f'<span style="color:var(--text-muted);font-weight:600;min-width:80px;display:inline-block">App:</span> {escape(app_name)}')

        with ui.row().style("gap:12px;margin-bottom:24px;align-items:center"):
            if file_path:
                ui.link("Open File", f"vscode://file/{file_path}").style(
                    "background:var(--accent);color:#fff;padding:6px 16px;border-radius:8px;font-size:13px;text-decoration:none;font-weight:600"
                )
            if cwd:
                def _open_folder():
                    try: os.startfile(cwd)
                    except: pass
                ui.button("Open Folder", on_click=_open_folder).style(
                    "background:var(--bg-surface);color:var(--text-main);padding:6px 16px;border-radius:8px;font-size:13px;font-weight:600;border:1px solid var(--border)"
                ).props('flat')
            if url:
                ui.link("Open URL", url, new_tab=True).style(
                    "background:var(--bg-surface);color:var(--text-main);padding:6px 16px;border-radius:8px;font-size:13px;text-decoration:none;font-weight:600;border:1px solid var(--border)"
                )
            if file_path or cwd:
                def _copy_path():
                    ui.clipboard.write(file_path or cwd)
                    ui.notify("Path copied!")
                ui.button("Copy Path", on_click=_copy_path).style(
                    "background:var(--bg-surface);color:var(--text-main);padding:6px 16px;border-radius:8px;font-size:13px;font-weight:600;border:1px solid var(--border)"
                ).props('flat')
            
            if not file_path and not cwd and not url:
                ui.label("No actionable links for this event.").style("font-size:13px;color:var(--text-muted)")

        # Details
        with ui.column().style("gap:8px"):
            if ev.get("summary"): _safe_html(f'<b>Summary:</b> {escape(ev.get("summary", ""))}')
            if ev.get("ocr_text"): 
                with ui.expansion("OCR Text").style("width:100%"):
                    ui.label(ev.get("ocr_text", "")).style("white-space:pre-wrap;font-size:12px;color:var(--text-muted);font-family:monospace")
            if ev.get("clipboard_text"):
                with ui.expansion("Clipboard").style("width:100%"):
                    ui.label(ev.get("clipboard_text", "")).style("white-space:pre-wrap;font-size:12px;color:var(--text-muted);font-family:monospace")

    dialog.open()

def _render_result_card(ev: dict, score: float):
    with ui.element("div").classes("oc-card").style("margin-bottom:12px;display:flex;gap:16px;align-items:flex-start").on("click", lambda: _open_event_modal(ev)):
        # Thumbnail
        ev_id = ev.get("id", "")
        if ev.get("screenshot_path"):
            _safe_html(
                f'<img src="{escape(_screenshot_src(ev_id), quote=True)}" class="thumb" '
                f'onerror="this.style.display=\'none\'">'
            )

        with ui.element("div").style("flex:1;min-width:0"):
            # App + title + repo
            app_name = ev.get("app_name", "")
            title = ev.get("window_title", "")
            repo = ev.get("repo", "")
            with ui.row().style("align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap"):
                if app_name:
                    _safe_html(f'<span class="oc-pill oc-pill-accent">{escape(app_name[:30])}</span>')
                if repo:
                    _safe_html(f'<span class="oc-pill" style="background:var(--success);color:#fff">{escape(repo[:30])}</span>')
                ui.label(title[:80]).style(
                    "font-size:15px;font-weight:600;color:var(--text-main);overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                )

            # Summary
            summary = ev.get("summary", "")
            if summary:
                ui.label(summary[:200]).style("font-size:13px;color:var(--text-muted);margin-bottom:8px;line-height:1.6")

            # Topics + time
            with ui.row().style("align-items:center;gap:8px;flex-wrap:wrap"):
                for topic in (ev.get("topics") or [])[:4]:
                    _safe_html(f'<span class="oc-pill">{escape(str(topic))}</span>')
                ts = _fmt_time(ev.get("timestamp", ""))
                ui.label(ts).style("font-size:12px;color:var(--text-muted);margin-left:auto;font-weight:500")

            # Score bar
            bar_w = min(100, int(score * 500))
            if score > 0:
                _safe_html(f'<div class="score-bar" style="width:{bar_w}%;margin-top:8px"></div>')


# ── Timeline tab ──────────────────────────────────────────────────────────

def build_timeline_tab(state: AppState):
    ui.label("Timeline").classes("text-gradient").style("font-size:32px;font-weight:800;margin-bottom:8px")
    ui.label("Your recent captures in chronological order").style(
        "font-size:14px;color:var(--text-muted);margin-bottom:40px"
    )

    container = ui.element("div").style("max-width:900px")

    async def load_events():
        try:
            events = await _api("get", "/events", params={"limit": 50})
            container.clear()
            with container:
                if not events:
                    _safe_html('<div class="empty-state"><div style="font-size:48px">📋</div>'
                            '<div style="margin-top:16px">No captures yet</div></div>')
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
                            "font-size:14px;font-weight:700;color:var(--accent);margin:32px 0 16px 0;"
                            "text-transform:uppercase;letter-spacing:0.1em;border-bottom:1px solid var(--border);padding-bottom:8px;"
                        )
                        prev_day = day
                    _render_result_card(ev, 0)
        except Exception as exc:
            with container:
                ui.label(f"Failed to load: {exc}").style("color:#ef4444")

    ui.timer(0.1, load_events, once=True)


# ── Sessions tab ──────────────────────────────────────────────────────────

def build_sessions_tab(state: AppState):
    ui.label("Sessions").classes("text-gradient").style("font-size:32px;font-weight:800;margin-bottom:8px")
    ui.label("Activity sessions grouped by context").style(
        "font-size:14px;color:var(--text-muted);margin-bottom:40px"
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
                    _safe_html('<div class="empty-state" style="grid-column:1/-1">'
                            '<div style="font-size:48px">📂</div>'
                            '<div style="margin-top:16px">No sessions yet</div></div>')
                    return
                for s in sessions:
                    with ui.element("div").classes("oc-card"):
                        topic = s.get("topic") or "Unnamed Session"
                        ui.label(topic[:40]).style("font-size:16px;font-weight:700;margin-bottom:8px;color:var(--text-main)")
                        start = _fmt_time(s.get("start_time", ""))
                        ec = s.get("event_count", 0)
                        ui.label(f"{start}  -  {ec} captures").style(
                            "font-size:12px;color:var(--text-muted)"
                        )
                        if s.get("summary"):
                            ui.label(s["summary"][:120]).style(
                                "font-size:13px;color:rgba(255,255,255,0.6);margin-top:12px;line-height:1.6"
                            )
        except Exception as exc:
            with container:
                ui.label(f"Failed: {exc}").style("color:#ef4444")

    ui.timer(0.1, load_sessions, once=True)


# -- Settings tab ----------------------------------------------------------

def build_settings_tab(state: AppState):
    ui.label("Settings").classes("text-gradient").style("font-size:32px;font-weight:800;margin-bottom:8px")
    ui.label("Configure OmniContext behaviour").style(
        "font-size:14px;color:var(--text-muted);margin-bottom:40px"
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
            # Privacy & Capture Controls
            ui.label("Privacy & Capture").classes("section-title").style("margin-top:0")
            with ui.element("div").classes("oc-card").style("margin-bottom:20px"):
                interval = ui.number(
                    label="Screenshot interval (seconds)",
                    value=s.get("capture_interval_seconds", 90),
                    min=10, max=600, step=10,
                ).style("width:100%;margin-bottom:12px")
                
                clipboard_toggle = ui.checkbox(
                    "Enable Clipboard Capture",
                    value=s.get("clipboard_capture_enabled", False),
                ).style("margin-bottom:12px")
                
                paused_toggle = ui.checkbox(
                    "Start Paused (Do not capture until manually resumed)",
                    value=s.get("capture_paused_on_startup", True),
                ).style("margin-bottom:12px")
                
                retention = ui.number(
                    label="Retention period (days)",
                    value=s.get("retention_days", 30),
                    min=1, max=3650, step=1,
                ).style("width:100%;margin-bottom:12px")

                async def save_privacy():
                    await _api("patch", "/settings", json={
                        "capture_interval_seconds": int(interval.value),
                        "clipboard_capture_enabled": bool(clipboard_toggle.value),
                        "capture_paused_on_startup": bool(paused_toggle.value),
                        "retention_days": int(retention.value),
                    })
                    ui.notify("Saved", type="positive", position="bottom-right")

                ui.button("Save", on_click=save_privacy).props("flat").style(
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


# -- Brain tab -----------------------------------------------------------------

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

    with ui.element("div").classes("oc-card").style(
        f"border-color:{accent};"
    ).on("click", on_click):
        # Top row: name + count badge
        with ui.row().style("align-items:center;justify-content:space-between;margin-bottom:10px"):
            ui.label(name[:32]).style(
                f"font-size:15px;font-weight:700;color:var(--text-main);"
                f"overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:160px"
            )
            _safe_html(
                f'<span style="background:{glow};border:1px solid {accent};color:{accent};'
                f'border-radius:20px;padding:2px 10px;font-size:11px;font-weight:600">'
                f'{count} captures</span>'
            )

        # Dominant app
        if app:
            ui.label(app[:30]).style("font-size:12px;color:var(--text-muted);margin-bottom:8px")

        # Co-entity pills
        if co_entities:
            with ui.row().style("gap:6px;flex-wrap:wrap"):
                for co in co_entities[:4]:
                    _safe_html(
                        f'<span class="oc-pill">'
                        f'{co[:20]}</span>'
                    )

        # Accent bar
        _safe_html(f'<div style="height:2px;border-radius:2px;background:{accent};margin-top:10px;opacity:.6"></div>')


def build_brain_tab(state: AppState):
    detail_container = None

    # ── Header ────────────────────────────────────────────────────────────
    with ui.row().style("align-items:center;justify-content:space-between;margin-bottom:8px"):
        ui.label("Your Digital Brain").classes("text-gradient").style("font-size:32px;font-weight:800")

    ui.label("Your activity, auto-clustered by topic").style(
        "font-size:14px;color:var(--text-muted);margin-bottom:40px"
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
                    _safe_html('<div class="empty-state"><div style="font-size:32px">🔍</div>'
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
                    _safe_html(
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
                            _safe_html(
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
        dark=False,
        reload=False,
        show=False,
        show_welcome_message=False,
    )
