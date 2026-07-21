"""Keyence CV-X camera backup taker: pull a CV-X vision controller's settings off
the camera over plain FTP.

Discovered live (2026-07-13, CV-X482D on the shop floor — see
CVX_FTP_LAYOUT.md): a CV-X exposes an **anonymous** FTP server
(`220 CV-X482D FTP server ready`), the login lands on the SD card at `/SD1/`, and
the settings live under `cv-x/setting/` (config `.dat`/`.tbd` + master `.bmp`
images, a `recovery/` dir, and numbered program dirs). `cv-x/box/` holds large
saved-set blobs. This means Keyence backup is plain FTP after all — the
proprietary `Vapi.Net.dll` C# helper the old plan assumed is NOT required.

Backup scope (matches the shop's existing Terminal-Software backup and the parked
helper's default): the whole `cv-x/setting/` tree; `cv-x/box/` is optional (big).

Mirrors mtxbackup.CameraBackupJob's shape (uuid id, lock-guarded progress dict,
snapshot()/cancel()/run() on a worker thread) so the api layer polls it through
the same endpoints, and reuses ftpbackup's gentle transfer primitives.

CV-X FTP quirk handled here: `LIST <path>` / `RETR <path-with-dirs>` are refused
("550 Bad path"); you must CWD into a directory and then act with bare names. So
the downloader positions CWD per directory and RETRs basenames — unlike the Linux
Matrox server, which resolves full relpaths directly.

ftplib is injected via ftp_factory so the whole flow is testable offline against a
FakeFTP (see tests/test_keyencebackup.py) - live-camera testing is never the first
validation.
"""
from __future__ import annotations

import ftplib
import json
import logging
import time
from pathlib import Path

from . import ftpbackup
from .ftpbackup import _names, _walk   # shared read-only FTP listing helpers

log = logging.getLogger(__name__)

# CV-X FTP takes an anonymous login (empty user/pass); the SD card is the login dir.
KEYENCE_USER = ""
KEYENCE_PASS = ""

SETTING_DIR = "cv-x/setting"       # relative to the FTP login dir (/SD1)
BOX_DIR = "cv-x/box"
BACKUP_TYPE = "keyence cv-x setting"


def keyence_enumerate(ftp, home: str, *, include_box: bool = False, cancel=None) -> list[str]:
    """Relpaths (from `home`) to pull for one CV-X: the whole `cv-x/setting/` tree,
    plus `cv-x/box/` when include_box. Read-only; restores CWD to `home`."""
    out: list = []

    def _home():
        if home:
            try:
                ftp.cwd(home)
            except ftplib.all_errors:
                pass

    targets = [SETTING_DIR] + ([BOX_DIR] if include_box else [])
    for target in targets:
        _home()
        try:
            for part in target.split("/"):
                ftp.cwd(part)
            _walk(ftp, target, out, cancel)
        except ftplib.all_errors:
            log.info("no %s tree on this CV-X", target)
    _home()
    return out


class KeyenceBackupJob(ftpbackup.CameraJobBase):
    """One Keyence CV-X station backup run. Construct, then .run() on a worker
    thread; poll .snapshot(); .cancel() stops gracefully between files. The
    state machine, crash-safety and library record live in
    ftpbackup.CameraJobBase; this class is the CV-X FTP transport."""

    DEVICE_TYPE = "camera-keyence"
    TYPE_STR = BACKUP_TYPE
    SOURCE = "ftp"
    NOTE_PREFIX = "keyence backup of"
    LOG_LABEL = "keyence"
    PULL_ERRORS = ftplib.all_errors   # tuple incl. OSError (long-path/os ops)

    def __init__(self, host, dest_root, plant, line, station, *,
                 cameras=None, user=KEYENCE_USER, passwd=KEYENCE_PASS, passive=True,
                 port=21, include_box=False, note="", run_id="", ftp_factory=ftplib.FTP,
                 throttle=0.03, on_complete=None):
        super().__init__(host, dest_root, plant, line, station, cameras=cameras,
                         note=note, run_id=run_id, throttle=throttle,
                         on_complete=on_complete)
        self.port = int(port or 21)
        self.user = user or ""
        self.passwd = passwd or ""
        self.passive = passive
        self.include_box = include_box
        self._ftp_factory = ftp_factory

    def _pull_camera(self, host, label, dated: Path, done, nbytes):
        """Connect to one CV-X, enumerate cv-x/setting (+box), and download each
        file into <dated>/<label>/…. The CV-X FTP refuses pathful RETR, so we CWD
        into each remote directory and RETR bare basenames."""
        ftp = None
        try:
            self._set(status="listing", current=f"{label} @ {host}")
            ftp = self._connect(host)
            try:
                home = ftp.pwd()
            except ftplib.all_errors:
                home = ""
            rels = keyence_enumerate(ftp, home, include_box=self.include_box,
                                     cancel=lambda: self.cancelled)
            with self._lock:
                self._p["total"] += len(rels)
            self._set(status="downloading")

            cur_dir = None
            for rel in sorted(rels):
                if self.cancelled:
                    return done, nbytes
                self._set(current=f"{label}/{rel}")
                parts = rel.split("/")
                rdir, base = "/".join(parts[:-1]), parts[-1]
                if rdir != cur_dir:
                    self._cwd_into(ftp, home, rdir)   # reposition only on dir change
                    cur_dir = rdir
                dest = dated.joinpath(label, *parts)
                try:
                    nbytes += ftpbackup.retrieve(ftp, base, dest)   # bare-name RETR at CWD
                    done += 1
                except ftplib.all_errors as e:   # tuple incl. OSError (long-path/os ops)
                    # a single missing/locked file must not sink the whole pull
                    with self._lock:
                        self._p["skipped"].append(f"{label}/{rel}")
                    log.info("skipped %s (%s)", rel, e)
                self._set(done=done, bytes=nbytes)
                if self._throttle:
                    time.sleep(self._throttle)
            return done, nbytes
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except Exception:  # noqa: BLE001
                    try:
                        ftp.close()
                    except Exception:  # noqa: BLE001
                        pass

    def _cwd_into(self, ftp, home, rdir):
        """Position CWD at home/<rdir> segment by segment (the CV-X FTP rejects a
        pathful cwd/RETR, so walk the segments)."""
        if home:
            ftp.cwd(home)
        for seg in rdir.split("/"):
            if seg:
                ftp.cwd(seg)

    def _connect(self, host):
        ftp = self._ftp_factory(timeout=ftpbackup.CONNECT_TIMEOUT)
        ftp.connect(host, self.port)
        ftp.login(self.user, self.passwd)   # anonymous
        try:
            ftp.set_pasv(self.passive)
        except Exception:  # noqa: BLE001
            pass
        return ftp

# -- pre-flight probe + read-only diagnose ---------------------------------------

def probe_keyence(host, *, user=KEYENCE_USER, passwd=KEYENCE_PASS, passive=True,
                  port=21, ftp_factory=ftplib.FTP) -> dict:
    """Pre-flight: connect + anonymous login + confirm the cv-x/setting tree. NO
    writes. `has_setting` is what marks a real CV-X (a bare ftpd that accepts
    anonymous login but has no cv-x/ is not a camera)."""
    out = {"reachable": False, "banner": "", "home": "",
           "has_cvx": False, "has_setting": False, "error": ""}
    ftp = None
    try:
        ftp = ftp_factory(timeout=ftpbackup.CONNECT_TIMEOUT)
        ftp.connect(host, int(port or 21))
        ftp.login(user or "", passwd or "")
        try:
            ftp.set_pasv(passive)
        except Exception:  # noqa: BLE001
            pass
        out["reachable"] = True
        try:
            out["banner"] = (ftp.getwelcome() or "").strip()
        except Exception:  # noqa: BLE001
            pass
        try:
            out["home"] = ftp.pwd() or ""
        except Exception:  # noqa: BLE001
            pass
        names = {n.lower() for n in _names(ftp)}
        out["has_cvx"] = "cv-x" in names
        if out["has_cvx"]:
            try:
                for part in SETTING_DIR.split("/"):
                    ftp.cwd(part)
                out["has_setting"] = True
            except ftplib.all_errors:
                pass
    except ftplib.all_errors as e:
        out["error"] = f"{type(e).__name__}: {e}"
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except Exception:  # noqa: BLE001
                try:
                    ftp.close()
                except Exception:  # noqa: BLE001
                    pass
    return out


def diagnose_keyence(host, *, user=KEYENCE_USER, passwd=KEYENCE_PASS, passive=True,
                     port=21, ftp_factory=ftplib.FTP) -> dict:
    """Read-only probe of a live CV-X: banner, home dir, and the cv-x / setting /
    box listings. ZERO writes. Also log.info'd as JSON for app.log."""
    port = int(port or 21)
    out: dict = {"host": host, "port": port, "banner": "", "home": "",
                 "home_list": [], "cvx_list": [], "setting_list": [], "box_list": [],
                 "error": ""}
    ftp = None
    try:
        ftp = ftp_factory(timeout=ftpbackup.CONNECT_TIMEOUT)
        ftp.connect(host, port)
        ftp.login(user or "", passwd or "")
        try:
            ftp.set_pasv(passive)
        except Exception:  # noqa: BLE001
            pass
        try:
            out["banner"] = (ftp.getwelcome() or "").strip()
        except Exception as e:  # noqa: BLE001
            out["banner"] = f"<{type(e).__name__}: {e}>"
        try:
            out["home"] = ftp.pwd() or ""
        except Exception:  # noqa: BLE001
            pass
        out["home_list"] = _names(ftp)[:100]

        def _relist(path, key):
            if out["home"]:
                try:
                    ftp.cwd(out["home"])
                except ftplib.all_errors:
                    pass
            try:
                for part in path.split("/"):
                    ftp.cwd(part)
                out[key] = _names(ftp)[:100]
            except ftplib.all_errors:
                pass

        _relist("cv-x", "cvx_list")
        _relist(SETTING_DIR, "setting_list")
        _relist(BOX_DIR, "box_list")
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except Exception:  # noqa: BLE001
                try:
                    ftp.close()
                except Exception:  # noqa: BLE001
                    pass
    try:
        log.info("diagnose_keyence %s -> %s", host, json.dumps(out)[:4000])
    except Exception:  # noqa: BLE001
        pass
    return out
