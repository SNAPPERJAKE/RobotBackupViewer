"""Window boot. resource_path() is the single dev/frozen asset resolver:
PyInstaller re-roots this module's __file__ under sys._MEIPASS and the spec
bundles web/ alongside it, so Path(__file__).parent works in both modes.

Carries a slimmed copy of BackupViewer's WebView2 rescue (the field
0x8007139F failure: CreateCoreWebView2ControllerAsync dies, pywebview swallows
it and leaves a dead window). Slim = no remembered mode: every boot tries
normal rendering first and relaunches ONCE into software rendering + a stable
profile if that dies. Hand-out exes land on exactly the machines this exists
for."""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import APP_NAME, __version__
from .api import Api

log = logging.getLogger(__name__)

BG_FALLBACK = "#323437"  # pre-CSS window color; avoids the white flash

_WV2_RESCUE_ENV = "LI_WV2_RESCUE"               # set on the relaunched process
_WV2_FAIL_MARK = "WebView2 initialization failed"


def resource_path(rel: str) -> Path:
    return Path(__file__).resolve().parent / rel


def app_dir() -> Path:
    """Per-user scratch home (log + fallback WebView2 profile). Nothing else
    is ever persisted - the tool is deliberately setting-less."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / "LibraryImporter"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        d = Path.home()
    return d


class _WebView2FailureWatch(logging.Handler):
    """Fires when pywebview logs its (otherwise-swallowed) WebView2 init
    failure; closes the dead window so webview.start() returns to main()."""

    def __init__(self, window):
        super().__init__(level=logging.ERROR)
        self.window = window
        self.failed = False

    def emit(self, record):
        try:
            if _WV2_FAIL_MARK not in record.getMessage():
                return
        except Exception:  # noqa: BLE001 - a logging handler must never raise
            return
        self.failed = True
        try:
            self.window.destroy()
        except Exception:  # noqa: BLE001 - window may already be gone
            pass


def _apply_fallback_env() -> dict:
    """Arm the rescue boot: software rendering via the WebView2 loader's env
    hook (broken GPU drivers are the top suspect) and a fresh stable profile
    (corrupt profiles are the runner-up). Returns extra webview.start kwargs."""
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
        "--disable-gpu --disable-gpu-compositing"
    )
    d = app_dir() / "webview2"
    shutil.rmtree(d, ignore_errors=True)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.warning("could not create %s - letting WebView2 create it", d)
    return {"storage_path": str(d), "private_mode": False}


def _relaunch_cmd() -> list[str]:
    """This process's own launch command (frozen exe vs `python run_...py`)."""
    if getattr(sys, "frozen", False):
        return [sys.executable] + sys.argv[1:]
    return [sys.executable] + sys.argv


def _next_boot_action(failed: bool, rescued: bool) -> str:
    """After webview.start() returns: 'ok', 'relaunch' (first failure -> one
    rescue attempt), or 'give-up' (the rescue itself failed - never chain)."""
    if not failed:
        return "ok"
    return "give-up" if rescued else "relaunch"


def _webview2_help(err: Exception, runtime_missing: bool = False) -> None:
    if runtime_missing:
        msg = (
            f"{APP_NAME} could not start its web view.\n\n"
            "This usually means the Microsoft Edge WebView2 Runtime is missing.\n"
            "Install it from:\n"
            "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
            f"Details: {err}"
        )
    else:
        msg = (
            f"{APP_NAME}'s web view failed to start, even with software rendering.\n\n"
            "Things that fix this, in order of likelihood:\n"
            "1. Update the graphics driver (old integrated-GPU drivers are the\n"
            "    most common cause)\n"
            "2. Repair 'Microsoft Edge WebView2 Runtime'\n"
            "    (Settings > Apps > Installed apps > ... > Modify)\n"
            "3. Have IT check antivirus exclusions for msedgewebview2.exe\n\n"
            f"Full log: {app_dir() / 'app.log'}\n\n"
            f"Details: {err}"
        )
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, msg, APP_NAME, 0x10)
    except Exception:  # noqa: BLE001 - console run / non-Windows
        print(msg)


def _setup_logging() -> None:
    try:
        logging.basicConfig(
            filename=str(app_dir() / "app.log"), level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    except OSError:
        logging.basicConfig(level=logging.INFO)


def _wire_drop(window, api: Api) -> None:
    """Native file drops only surface real OS paths through a PYTHON-side DOM
    subscription (the JS drop event's File objects carry no path); subscribing
    also arms the backend to capture them. Wired after page load; failure is
    non-fatal - the click-to-pick path covers everything."""
    def wire(*_a):
        try:
            from webview.dom import DOMEventHandler
            window.dom.document.events.drop += DOMEventHandler(
                api.handle_drop, prevent_default=True)
            log.info("drag-drop armed")
        except Exception:  # noqa: BLE001 - surface varies across pywebview versions
            log.exception("drag-drop unavailable - click-to-pick still works")
    window.events.loaded += wire


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="libraryimporter",
                                     description="seed a BackupViewer library from a robot list")
    parser.add_argument("--debug", action="store_true", help="enable devtools")
    args = parser.parse_args(argv)

    _setup_logging()
    log.info("%s %s starting", APP_NAME, __version__)

    try:
        import webview
    except ImportError:
        print("pywebview is not installed. Run: pip install pywebview")
        return 1

    rescued = bool(os.environ.pop(_WV2_RESCUE_ENV, ""))
    start_kwargs = {"gui": "edgechromium", "debug": args.debug}
    if rescued:
        log.info("rescue boot: software rendering + stable profile")
        start_kwargs.update(_apply_fallback_env())

    api = Api()
    window = webview.create_window(
        f"{APP_NAME} {__version__}",
        url=str(resource_path("web/index.html")),
        js_api=api,
        width=780,
        height=720,
        min_size=(580, 480),
        background_color=BG_FALLBACK,
    )
    api.bind(window)
    _wire_drop(window, api)

    watch = _WebView2FailureWatch(window)
    logging.getLogger("pywebview").addHandler(watch)
    try:
        webview.start(**start_kwargs)
    except Exception as e:
        log.exception("webview failed to start")
        _webview2_help(e, runtime_missing=True)
        return 1
    finally:
        logging.getLogger("pywebview").removeHandler(watch)

    action = _next_boot_action(watch.failed, rescued)
    if action == "ok":
        return 0
    if action == "give-up":
        log.error("WebView2 failed in both normal and rescue modes")
        _webview2_help(RuntimeError("WebView2 could not start in any mode (see app.log)"))
        return 1
    log.warning("WebView2 init failed - relaunching once in rescue mode")
    env = dict(os.environ)
    env[_WV2_RESCUE_ENV] = "1"
    try:
        subprocess.Popen(_relaunch_cmd(), env=env, close_fds=True)
    except OSError:
        log.exception("could not relaunch for the WebView2 rescue")
        _webview2_help(RuntimeError("WebView2 failed and the automatic rescue "
                                    "could not start (see app.log)"))
    return 1
