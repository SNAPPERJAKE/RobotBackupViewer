"""The js_api bridge. Python owns the state (the parsed source model and the
chosen destination); every endpoint hands back the ONE canonical UI state via
_state(), so the page never merges - it just re-renders. Same never-throw
{ok, data|error} envelope as BackupViewer's api.py."""
from __future__ import annotations

import functools
import json
import logging
import os
import time
from pathlib import Path

from . import APP_NAME, __version__, core

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _endpoint(fn):
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        t0 = time.perf_counter()
        try:
            data = fn(self, *args, **kwargs)
            return {"ok": True, "data": data, "ms": round((time.perf_counter() - t0) * 1000)}
        except ApiError as e:
            return {"ok": False, "error": {"code": e.code, "message": str(e)}}
        except Exception as e:  # noqa: BLE001 - bridge boundary
            log.exception("api %s failed", fn.__name__)
            return {"ok": False, "error": {"code": "INTERNAL", "message": f"{type(e).__name__}: {e}"}}
    return wrapper


class Api:
    def __init__(self):
        self._window = None
        self._model: dict | None = None   # last GOOD core.parse_source output
        self._dest: str = ""              # the plant folder

    def bind(self, window) -> None:
        self._window = window

    # ---- state ------------------------------------------------------------

    def _state(self) -> dict:
        """The whole truth, every time: source summary, destination, the
        planned line/robot rows (present flags included), and warnings."""
        out: dict = {"source": None, "dest": self._dest or None, "lines": [],
                     "selectable": 0, "present": 0, "warnings": []}
        if self._model:
            out["source"] = {"name": self._model["name"], "path": self._model["path"],
                             "robots": self._model["robots"],
                             "lines": len(self._model["lines"]),
                             "warnings": self._model["warnings"]}
            p = core.plan(self._model, self._dest or None)
            out["lines"], out["selectable"], out["present"] = \
                p["lines"], p["selectable"], p["present"]
        if self._dest:
            out["warnings"] = core.dest_warnings(self._dest)
        return out

    def _load(self, path: str) -> dict:
        model = core.parse_source(path)
        if not model["ok"]:
            raise ApiError("BAD_SOURCE", f"{model['name']}: {model['error']}")
        self._model = model
        log.info("loaded %s: %d robots / %d lines",
                 model["name"], model["robots"], len(model["lines"]))
        return self._state()

    # ---- endpoints ----------------------------------------------------------

    @_endpoint
    def get_boot(self):
        log.info("ui booted")
        return {"name": APP_NAME, "version": __version__}

    @_endpoint
    def pick_source(self):
        import webview
        start = str(Path(self._model["path"]).parent) if self._model else ""
        res = self._window.create_file_dialog(
            webview.FileDialog.OPEN, directory=start,
            file_types=("Robot list (*.json)", "All files (*.*)"))
        if not res:
            return None                    # cancelled - the page keeps what it has
        return self._load(res[0])

    @_endpoint
    def load_source(self, path: str):
        """Shared by drag-drop and anything that already knows the path."""
        return self._load(path)

    @_endpoint
    def pick_dest(self):
        import webview
        res = self._window.create_file_dialog(
            webview.FileDialog.FOLDER,
            directory=self._dest or core.default_dest_start())
        if not res:
            return None
        self._dest = res[0]
        log.info("destination: %s", self._dest)
        return self._state()

    @_endpoint
    def seed(self, selection: dict):
        if not self._model or not self._dest:
            raise ApiError("NOT_READY", "load a robot list and pick a destination first")
        result = core.seed(self._model, self._dest, selection or {},
                           progress=self._push_progress)
        log.info("seeded %s: %d created / %d skipped / %d errors", self._dest,
                 result["created"], result["skipped"], len(result["errors"]))
        # the refreshed state re-grays everything just created ("import more")
        return {"result": result, "state": self._state()}

    @_endpoint
    def open_dest(self):
        if not self._dest:
            raise ApiError("NOT_READY", "no destination chosen")
        os.startfile(self._dest)  # noqa: S606 - the folder the user just picked
        return True

    # ---- pushes (Python -> page; not endpoints) --------------------------------

    def handle_drop(self, event) -> None:
        """pywebview DOM drop handler (real OS paths only surface Python-side,
        as file['pywebviewFullPath'] - see app._wire_drop)."""
        try:
            files = ((event or {}).get("dataTransfer") or {}).get("files") or []
            paths = [f.get("pywebviewFullPath") for f in files
                     if isinstance(f, dict) and f.get("pywebviewFullPath")]
            path = next((p for p in paths if p.lower().endswith(".json")), None)
            if not path:
                self._push_drop({"ok": False, "error": "drop a .json robot list"})
                return
            state = self._load(path)
            state["ok"] = True
            self._push_drop(state)
        except ApiError as e:
            self._push_drop({"ok": False, "error": str(e)})
        except Exception:  # noqa: BLE001 - event thread must never blow up
            log.exception("drop handling failed")
            self._push_drop({"ok": False, "error": "could not read the dropped file"})

    def _push_drop(self, payload: dict) -> None:
        self._push("LI.onDrop(%s)" % json.dumps(payload))

    def _push_progress(self, done: int, total: int, line: str) -> None:
        self._push("LI.onProgress(%d,%d,%s)" % (done, total, json.dumps(line)))

    def _push(self, js: str) -> None:
        # json.dumps keeps ensure_ascii, so U+2028/29 can't break the JS literal
        try:
            if self._window:
                self._window.evaluate_js("window.LI && " + js)
        except Exception:  # noqa: BLE001 - window may be tearing down
            pass
