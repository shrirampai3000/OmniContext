import os
import psutil

def find_git_root(start_path: str) -> str:
    """Walks upward until a .git folder is found, or returns empty string."""
    if not start_path or not os.path.isdir(start_path):
        return ""
    
    current = os.path.abspath(start_path)
    while True:
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return ""
        current = parent

class ContextExtractor:
    def extract(self, title: str, app: str, pid: int) -> dict:
        """Returns a dict with context fields."""
        return {}

class VSCodeExtractor(ContextExtractor):
    def extract(self, title: str, app: str, pid: int) -> dict:
        ctx = {"context_type": "vscode", "context_confidence": 0.95}
        try:
            cwd = psutil.Process(pid).cwd()
            if cwd:
                ctx["cwd"] = cwd
                git_root = find_git_root(cwd)
                if git_root:
                    ctx["repo"] = os.path.basename(git_root)
                else:
                    ctx["repo"] = os.path.basename(cwd)
                
                parts = title.split(" - ")
                if len(parts) >= 2:
                    filename = parts[0].strip()
                    ctx["file"] = os.path.join(cwd, filename)
        except Exception:
            pass
        return ctx

class BrowserExtractor(ContextExtractor):
    def extract(self, title: str, app: str, pid: int) -> dict:
        ctx = {"context_type": "browser", "context_confidence": 0.8}
        parts = title.split(" - ")
        if len(parts) >= 2:
            ctx["page_title"] = " - ".join(parts[:-1]).strip()
        else:
            ctx["page_title"] = title
        return ctx

class TerminalExtractor(ContextExtractor):
    def extract(self, title: str, app: str, pid: int) -> dict:
        ctx = {"context_type": "terminal", "context_confidence": 0.9}
        try:
            cwd = psutil.Process(pid).cwd()
            if cwd:
                ctx["cwd"] = cwd
                git_root = find_git_root(cwd)
                if git_root:
                    ctx["repo"] = os.path.basename(git_root)
        except Exception:
            pass
        return ctx

class ExplorerExtractor(ContextExtractor):
    def extract(self, title: str, app: str, pid: int) -> dict:
        ctx = {"context_type": "explorer", "context_confidence": 0.8}
        try:
            # For Windows Explorer, cwd is usually useless (System32), but we might parse title
            # This is a stub for future UIAutomation or more complex logic
            pass
        except Exception:
            pass
        return ctx

def get_extractor(app_name: str) -> ContextExtractor:
    app_lower = app_name.lower()
    if "code.exe" in app_lower:
        return VSCodeExtractor()
    elif "chrome" in app_lower or "edge" in app_lower or "firefox" in app_lower:
        return BrowserExtractor()
    elif "powershell" in app_lower or "cmd.exe" in app_lower or "terminal" in app_lower:
        return TerminalExtractor()
    elif "explorer" in app_lower:
        return ExplorerExtractor()
    return ContextExtractor()
