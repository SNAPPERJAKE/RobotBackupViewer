"""Screen capture: the PNG encoder proven by decoding it back by hand, and
the GDI path smoke-tested against the real desktop (Windows only - which is
the only place the app runs)."""
import struct
import sys
import zlib

import pytest

from backupviewer import screengrab


def _decode_png(data: bytes):
    """Minimal PNG reader for our own encoder's output: returns (w, h, rgba)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, w = 8, None
    idat = b""
    while pos < len(data):
        (ln,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        (crc,) = struct.unpack(">I", data[pos + 8 + ln:pos + 12 + ln])
        assert crc == zlib.crc32(tag + body), f"bad crc on {tag}"
        if tag == b"IHDR":
            w, h, depth, ctype, comp, filt, inter = struct.unpack(">IIBBBBB", body)
            assert (depth, ctype, comp, filt, inter) == (8, 6, 0, 0, 0)
        elif tag == b"IDAT":
            idat += body
        pos += 12 + ln
    raw = zlib.decompress(idat)
    stride = w * 4
    rows = []
    for y in range(h):
        line = raw[y * (stride + 1):(y + 1) * (stride + 1)]
        assert line[0] == 0, "only filter 0 is emitted"
        rows.append(line[1:])
    return w, h, b"".join(rows)


def test_png_roundtrip():
    rgba = bytes(range(2 * 3 * 4))          # 2x3, every byte distinct
    png = screengrab.png_encode(2, 3, rgba)
    assert _decode_png(png) == (2, 3, rgba)


def test_png_rejects_wrong_length():
    with pytest.raises(ValueError):
        screengrab.png_encode(2, 2, b"\x00" * 15)


@pytest.mark.skipif(sys.platform != "win32", reason="GDI capture is Windows-only")
def test_grab_rect_png_speaks_png():
    png = screengrab.grab_rect_png(0, 0, 6, 4)
    w, h, rgba = _decode_png(png)
    assert (w, h) == (6, 4)
    assert all(rgba[i] == 255 for i in range(3, len(rgba), 4)), "alpha forced opaque"


@pytest.mark.skipif(sys.platform != "win32", reason="GDI capture is Windows-only")
def test_grab_rejects_empty_rect():
    with pytest.raises(OSError):
        screengrab.grab_rect_png(0, 0, 0, 10)


@pytest.mark.skipif(sys.platform != "win32", reason="monitor query is Windows-only")
def test_monitor_rect_falls_back_to_primary():
    x, y, w, h = screengrab.monitor_rect_for_window("no window has this title 8f2k")
    assert (x, y) == (0, 0)
    assert w > 0 and h > 0


@pytest.mark.skipif(sys.platform != "win32", reason="window move is Windows-only")
def test_cover_window_gives_up_honestly():
    assert screengrab.cover_window_on_monitor(
        "no window has this title 8f2k", (0, 0, 10, 10), tries=2, delay=0.01) is False
