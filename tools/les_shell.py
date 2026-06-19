"""LES desktop shell — a thin native window + tray around the Sovushka web UI.

L1 of the GUI-shell plan: this does NOT reimplement the interface — Sovushka
(NiceGUI, served on :8051) stays the single source of truth. The shell only adds
the two things a browser tab can't give: a native window with a start-up splash,
and a tray menu for lifecycle (open / restart / stop / logs / quit) so the
operator never needs a terminal to control the stack.

Launched by the installer bootstrap after the environment is prepared. The GUI
deps (pywebview + pystray + Pillow) live in the optional ``desktop`` extra; if
they are missing the shell degrades gracefully — start the stack headless and
open the default browser.

Run:
    uv run python -m tools.les_shell          # native shell (with desktop extra)
    uv run python -m tools.les_shell --no-gui # force headless start + browser
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

UI_URL = "http://127.0.0.1:8051/les"
HEALTH_URL = "http://127.0.0.1:8051/healthz"
WINDOW_TITLE = "ЛЕС · Совушка"


def _log_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "LES"
    if sys.platform.startswith("win"):
        import os

        base = os.environ.get("LOCALAPPDATA", str(Path.home()))
        return Path(base) / "LES" / "logs"
    return Path.home() / ".local" / "state" / "les" / "logs"


# ── health / lifecycle (deterministic, unit-tested) ─────────────────────────
def healthy(url: str = HEALTH_URL, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def wait_healthy(url: str = HEALTH_URL, attempts: int = 90, delay: float = 1.0) -> bool:
    for _ in range(attempts):
        if healthy(url):
            return True
        time.sleep(delay)
    return False


def start_stack() -> bool:
    from tools import les_runtime_control as rc

    try:
        result = rc.start_core(include_ui=True)
    except Exception:
        return False
    return all(getattr(item, "ok", False) for item in result)


def stop_stack() -> None:
    from tools import les_runtime_control as rc

    try:
        rc.stop_core(include_ui=True)
    except Exception:
        pass


def restart_stack() -> None:
    from tools import les_runtime_control as rc

    try:
        rc.restart_core(include_ui=True)
    except Exception:
        pass


def ensure_started() -> bool:
    """Bring the stack up if it is not already serving the UI."""
    if healthy():
        return True
    start_stack()
    return wait_healthy()


def open_logs() -> None:
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    opener = {"darwin": "open", "win32": "explorer"}.get(sys.platform, "xdg-open")
    subprocess.run([opener, str(log_dir)], check=False)


def gui_available() -> bool:
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False


# ── headless fallback ───────────────────────────────────────────────────────
def run_headless() -> int:
    if not ensure_started():
        print("LES: не удалось поднять службы — см. логи", file=sys.stderr)
        return 1
    webbrowser.open(UI_URL)
    return 0


# ── native shell (pywebview + pystray) ──────────────────────────────────────
SPLASH_HTML = """<!doctype html><html><head><meta charset="utf-8">
<style>
  html,body{height:100%;margin:0;background:#0f1115;color:#e6e6e6;
    font-family:-apple-system,Segoe UI,Roboto,sans-serif;display:flex;
    align-items:center;justify-content:center}
  .wrap{text-align:center}
  .tree{font-size:54px}
  .t{font-size:20px;margin-top:14px;opacity:.92}
  .s{font-size:13px;margin-top:8px;opacity:.55}
  .bar{margin:22px auto 0;width:220px;height:3px;border-radius:3px;
    background:#23262d;overflow:hidden}
  .bar i{display:block;height:100%;width:40%;border-radius:3px;
    background:#4c8bf5;animation:slide 1.1s ease-in-out infinite}
  @keyframes slide{0%{margin-left:-40%}100%{margin-left:100%}}
</style></head><body><div class="wrap">
  <div class="tree">🌲</div>
  <div class="t">Поднимаю ЛЕС…</div>
  <div class="s">Qdrant · модель · proxy · Совушка</div>
  <div class="bar"><i></i></div>
</div></body></html>"""


def _build_tray(on_open, on_restart, on_stop, on_logs, on_quit):
    """Construct a pystray Icon, or return None if pystray/Pillow are absent."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        return None

    image = Image.new("RGB", (64, 64), "#0f1115")
    draw = ImageDraw.Draw(image)
    draw.ellipse((16, 16, 48, 48), fill="#4c8bf5")  # simple placeholder mark

    menu = pystray.Menu(
        pystray.MenuItem("Открыть Совушку", lambda *_: on_open()),
        pystray.MenuItem("Перезапустить", lambda *_: on_restart()),
        pystray.MenuItem("Остановить службы", lambda *_: on_stop()),
        pystray.MenuItem("Логи…", lambda *_: on_logs()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", lambda *_: on_quit()),
    )
    return pystray.Icon("les", image, WINDOW_TITLE, menu)


def run_gui() -> int:
    import webview

    window = webview.create_window(WINDOW_TITLE, html=SPLASH_HTML, width=1200, height=820)
    state = {"tray": None}

    def boot() -> None:
        if ensure_started():
            window.load_url(UI_URL)
        else:
            window.load_html(
                "<body style='background:#0f1115;color:#e66;font-family:sans-serif;"
                "padding:40px'>Не удалось поднять службы. Откройте логи из трея.</body>"
            )

    def on_open() -> None:
        try:
            window.show()
            window.load_url(UI_URL)
        except Exception:
            pass

    def on_quit() -> None:
        stop_stack()
        if state["tray"] is not None:
            try:
                state["tray"].stop()
            except Exception:
                pass
        try:
            window.destroy()
        except Exception:
            pass

    tray = _build_tray(
        on_open=on_open,
        on_restart=restart_stack,
        on_stop=stop_stack,
        on_logs=open_logs,
        on_quit=on_quit,
    )
    state["tray"] = tray
    if tray is not None:
        threading.Thread(target=tray.run, daemon=True).start()

    webview.start(boot)  # blocks until the window is closed
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LES desktop shell")
    parser.add_argument("--no-gui", action="store_true", help="force headless start + browser")
    args = parser.parse_args(argv)

    if args.no_gui or not gui_available():
        return run_headless()
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
