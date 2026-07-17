"""LibraryImporter boot resilience (the slimmed WebView2 rescue) and the api
bridge's pure logic - no GUI, no webview import. Mirrors test_webview_boot."""
import json
import logging
import sys

from libraryimporter import app, core
from libraryimporter.api import Api


class _FakeWindow:
    def __init__(self):
        self.destroyed = 0
        self.evaluated = []

    def destroy(self):
        self.destroyed += 1

    def evaluate_js(self, js):
        self.evaluated.append(js)


def _record(msg, level=logging.ERROR):
    return logging.LogRecord("pywebview", level, __file__, 1, msg, None, None)


# ---- rescue-lite ----------------------------------------------------------------

def test_failure_watch_fires_only_on_the_init_failure():
    w = _FakeWindow()
    watch = app._WebView2FailureWatch(w)
    watch.emit(_record("some other pywebview error"))
    assert watch.failed is False and w.destroyed == 0
    watch.emit(_record("WebView2 initialization failed with exception:\n boom"))
    assert watch.failed is True and w.destroyed == 1


def test_next_boot_action_two_step_ladder():
    assert app._next_boot_action(False, False) == "ok"
    assert app._next_boot_action(False, True) == "ok"
    assert app._next_boot_action(True, False) == "relaunch"
    assert app._next_boot_action(True, True) == "give-up"


def test_relaunch_cmd_dev_and_frozen(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_libraryimporter.py", "--debug"])
    monkeypatch.setattr(sys, "executable", r"C:\Python\python.exe")
    assert app._relaunch_cmd() == [r"C:\Python\python.exe", "run_libraryimporter.py", "--debug"]

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\LibraryImporter.exe")
    monkeypatch.setattr(sys, "argv", [r"C:\Apps\LibraryImporter.exe", "--debug"])
    assert app._relaunch_cmd() == [r"C:\Apps\LibraryImporter.exe", "--debug"]


def test_apply_fallback_env_arms_software_rendering(monkeypatch, tmp_path):
    import os
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", raising=False)
    stale = tmp_path / "LibraryImporter" / "webview2" / "stale"
    stale.mkdir(parents=True)
    kwargs = app._apply_fallback_env()
    assert "--disable-gpu" in os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"]
    d = tmp_path / "LibraryImporter" / "webview2"
    assert kwargs == {"storage_path": str(d), "private_mode": False}
    assert d.is_dir() and not stale.exists()


# ---- api bridge -------------------------------------------------------------------

def _api_with_model(tmp_path):
    src = tmp_path / "robots.json"
    src.write_text(json.dumps({"RBB01": {"010R01": "192.0.2.10"}}), encoding="utf-8")
    api = Api()
    w = _FakeWindow()
    api.bind(w)
    return api, w, src


def test_endpoint_envelope_never_throws(tmp_path):
    api, _, _ = _api_with_model(tmp_path)
    res = api.load_source(str(tmp_path / "missing.json"))
    assert res["ok"] is False and res["error"]["code"] == "BAD_SOURCE"
    res = api.seed({})
    assert res["ok"] is False and res["error"]["code"] == "NOT_READY"


def test_load_then_state_carries_the_plan(tmp_path):
    api, _, src = _api_with_model(tmp_path)
    res = api.load_source(str(src))
    assert res["ok"] is True
    state = res["data"]
    assert state["source"]["robots"] == 1 and state["dest"] is None
    assert state["lines"][0]["robots"][0]["full"] == "RB010R01B01"
    assert state["selectable"] == 1


def test_seed_endpoint_creates_and_returns_refreshed_state(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "configured_library_root", lambda: "")
    api, w, src = _api_with_model(tmp_path)
    api.load_source(str(src))
    dest = tmp_path / "FakePlant"
    dest.mkdir()
    api._dest = str(dest)                      # the probe seam - no dialog in tests
    res = api.seed({"RBB01": ["010R01"]})
    assert res["ok"] is True
    assert res["data"]["result"]["created"] == 1
    # refreshed state re-grays what was just created
    assert res["data"]["state"]["present"] == 1 and res["data"]["state"]["selectable"] == 0
    # progress was pushed to the page, guarded behind window.LI
    assert any("LI.onProgress" in js for js in w.evaluated)
    assert all(js.startswith("window.LI && ") for js in w.evaluated)


def test_handle_drop_loads_json_and_pushes_state(tmp_path):
    api, w, src = _api_with_model(tmp_path)
    api.handle_drop({"dataTransfer": {"files": [
        {"name": "robots.json", "pywebviewFullPath": str(src)},
    ]}})
    assert len(w.evaluated) == 1 and "LI.onDrop" in w.evaluated[0]
    payload = json.loads(w.evaluated[0].split("LI.onDrop(", 1)[1][:-1])
    assert payload["ok"] is True and payload["source"]["robots"] == 1


def test_handle_drop_rejects_non_json_and_bad_lists(tmp_path):
    api, w, _ = _api_with_model(tmp_path)
    api.handle_drop({"dataTransfer": {"files": [{"name": "x.tp", "pywebviewFullPath": "x.tp"}]}})
    api.handle_drop({"dataTransfer": {"files": []}})
    api.handle_drop(None)
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    api.handle_drop({"dataTransfer": {"files": [{"pywebviewFullPath": str(bad)}]}})
    payloads = [json.loads(js.split("LI.onDrop(", 1)[1][:-1]) for js in w.evaluated]
    assert len(payloads) == 4 and all(p["ok"] is False for p in payloads)
    assert api._model is None                  # nothing bad ever sticks
