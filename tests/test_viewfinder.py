"""The screen viewfinder: a phone share whose frames are a user-picked
rectangle of the PC screen. Server behavior over real loopback HTTP with the
capture faked; the api endpoints with webview and the GDI layer stubbed; the
picker's coordinate math straight."""
import sys
import types
import urllib.error
import urllib.request

import pytest

from backupviewer import phoneview, screengrab
from backupviewer.phoneview import PhoneShare, css_rect_to_physical, picker_page

PNG1 = screengrab.png_encode(1, 1, b"\x10\x20\x30\xff")
PNG2 = screengrab.png_encode(1, 1, b"\x40\x50\x60\xff")


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.status, dict(r.headers), r.read()


def _get_err(port, path):
    try:
        _get(port, path)
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    raise AssertionError("expected an HTTP error")


@pytest.fixture
def share():
    s = PhoneShare(bind="127.0.0.1")
    yield s
    s.stop_session(None)


# -- the screen session on the share server ----------------------------------------

def test_screen_session_is_a_singleton(share):
    a = share.start_screen_session("screen area")
    b = share.start_screen_session("again")
    assert a["token"] == b["token"]
    s = share.status()["sessions"][0]
    assert s["kind"] == "screen" and s["ip"] == ""


def test_no_area_picked_is_an_honest_503(share):
    r = share.start_screen_session("screen area")
    code, body = _get_err(share.port, f"/v/{r['token']}/frame")
    assert code == 503
    assert b"no screen area picked yet" in body


def test_picked_area_streams_png(share):
    r = share.start_screen_session("screen area")
    share.set_screen_source(r["token"], lambda: PNG1, (10, 20, 300, 400))
    status, headers, body = _get(share.port, f"/v/{r['token']}/frame")
    assert status == 200
    assert headers["Content-Type"] == "image/png"
    assert body == PNG1
    s = share.status()["sessions"][0]
    assert s["area"] == [10, 20, 300, 400] and s["picking"] is False


def test_picking_freezes_the_stream_on_the_last_frame(share, monkeypatch):
    calls = []
    r = share.start_screen_session("screen area")
    share.set_screen_source(r["token"], lambda: (calls.append(1), PNG1)[1], (0, 0, 9, 9))
    _get(share.port, f"/v/{r['token']}/frame")
    assert calls == [1]
    monkeypatch.setattr(phoneview, "MIN_FETCH_GAP", 0.0)     # freshness gate off
    share.set_picking(r["token"], b"SNAPSHOT")
    _, _, body = _get(share.port, f"/v/{r['token']}/frame")  # stale, no new call
    assert body == PNG1
    assert calls == [1]
    assert share.status()["sessions"][0]["picking"] is True
    share.set_screen_source(r["token"], lambda: (calls.append(2), PNG2)[1], (0, 0, 9, 9))
    _, _, body = _get(share.port, f"/v/{r['token']}/frame")
    assert body == PNG2 and calls == [1, 2]


def test_pick_snapshot_route(share):
    r = share.start_screen_session("screen area")
    assert _get_err(share.port, f"/v/{r['token']}/pick.png")[0] == 404
    share.set_picking(r["token"], b"\x89PNGfake")
    status, headers, body = _get(share.port, f"/v/{r['token']}/pick.png")
    assert status == 200 and headers["Content-Type"] == "image/png"
    assert body == b"\x89PNGfake"
    share.cancel_picking(r["token"])
    assert _get_err(share.port, f"/v/{r['token']}/pick.png")[0] == 404
    assert share.status()["sessions"][0]["picking"] is False


def test_screen_capture_failure_is_reported(share):
    r = share.start_screen_session("screen area")

    def dead():
        raise OSError("BitBlt failed")
    share.set_screen_source(r["token"], dead, (0, 0, 9, 9))
    code, body = _get_err(share.port, f"/v/{r['token']}/frame")
    assert code == 503 and b"screen" in body
    assert share.status()["sessions"][0]["fetch_err"] == "BitBlt failed"


def test_camera_and_screen_sessions_coexist(share):
    cam = share.start_session("192.0.2.10", "cam")
    scr = share.start_screen_session("screen area")
    assert cam["token"] != scr["token"]
    kinds = {s["kind"] for s in share.status()["sessions"]}
    assert kinds == {"camera", "screen"}


# -- picker math + template --------------------------------------------------------

def test_css_rect_to_physical_scales_and_offsets():
    phys = css_rect_to_physical({"x": 100, "y": 50, "w": 400, "h": 300},
                                1.5, (2560, -80))
    assert phys == (2560 + 150, -80 + 75, 600, 450)
    assert css_rect_to_physical({"x": 0, "y": 0, "w": 0.1, "h": 0.1}, 1.0, (0, 0)) \
        == (0, 0, 1, 1)                                     # never a zero rect


def test_picker_page_fills_placeholders():
    page = picker_page("http://127.0.0.1:8756/v/tok/pick.png", (5, 6, 7, 8), (5, 0))
    assert 'src="http://127.0.0.1:8756/v/tok/pick.png"' in page
    assert "var AREA = [5, 6, 7, 8], ORIGIN = [5, 0];" in page
    page2 = picker_page("http://127.0.0.1:1/v/t/pick.png", None, (0, 0))
    assert "var AREA = null" in page2


def test_lan_urls_accepts_no_camera():
    urls = phoneview.lan_urls(None, 8756, "tok")
    for u in urls:
        assert u["kind"] in ("hotspot", "lan")              # nothing camera-facing


# -- the api endpoints (webview + GDI stubbed) -------------------------------------

@pytest.fixture
def api(monkeypatch):
    from backupviewer.api import Api
    monkeypatch.setattr(phoneview, "BIND", "127.0.0.1")
    monkeypatch.setattr(screengrab, "monitor_rect_for_window", lambda title: (0, 0, 800, 600))
    monkeypatch.setattr(screengrab, "grab_rect_png", lambda x, y, w, h: PNG1)
    monkeypatch.setattr(screengrab, "cover_window_on_monitor", lambda *a, **k: True)
    made = []
    stub = types.SimpleNamespace(create_window=lambda title, **kw: (
        made.append((title, kw)),
        types.SimpleNamespace(destroy=lambda: made.append(("destroyed", title))))[1])
    monkeypatch.setitem(sys.modules, "webview", stub)
    a = Api()
    a._made_windows = made
    yield a
    if a._phone_share is not None:
        a._phone_share.stop_session(None)


def test_viewfinder_start_opens_picker_and_shares(api):
    r = api.viewfinder_start()
    assert r["ok"] is True
    d = r["data"]
    assert d["token"] and d["urls"]
    title, kw = api._made_windows[0]
    assert title == "BV area picker"
    assert kw["frameless"] and kw["on_top"]
    assert f"/v/{d['token']}/pick.png" in kw["html"]
    assert "var AREA = null" in kw["html"]
    st = api.phone_view_status()["data"]["sessions"][0]
    assert st["kind"] == "screen" and st["picking"] is True


def test_picker_done_goes_live_and_pick_again_prefills(api):
    d = api.viewfinder_start()["data"]
    bridge = api._made_windows[0][1]["js_api"]
    bridge.done({"x": 10, "y": 20, "w": 100, "h": 80, "dpr": 1.5})
    st = api.phone_view_status()["data"]["sessions"][0]
    assert st["picking"] is False
    assert st["area"] == [15, 30, 150, 120]
    assert ("destroyed", "BV area picker") in api._made_windows
    status, headers, body = _get(d["port"], f"/v/{d['token']}/frame")
    assert status == 200 and headers["Content-Type"] == "image/png" and body == PNG1
    api.viewfinder_pick({"token": d["token"]})
    assert "var AREA = [15, 30, 150, 120]" in api._made_windows[-1][1]["html"]


def test_picker_cancel_restores(api):
    d = api.viewfinder_start()["data"]
    api._made_windows[0][1]["js_api"].cancel()
    st = api.phone_view_status()["data"]["sessions"][0]
    assert st["picking"] is False and st["area"] is None


def test_viewfinder_rejoin_and_stop_closes_picker(api):
    d = api.viewfinder_start()["data"]
    d2 = api.viewfinder_start()["data"]
    assert d["token"] == d2["token"]
    api.phone_view_stop({"token": d["token"]})
    assert api._picker is None
    assert ("destroyed", "BV area picker") in api._made_windows
    assert api.phone_view_status()["data"]["running"] is False


def test_viewfinder_pick_rejects_unknown_token(api):
    assert api.viewfinder_pick({"token": "nope"})["error"]["code"] == "BAD_SPEC"
    api.viewfinder_start()
    cam_r = api.phone_view_start({"ip": "192.0.2.9", "label": "cam"})["data"]
    assert api.viewfinder_pick({"token": cam_r["token"]})["error"]["code"] == "BAD_SPEC"
