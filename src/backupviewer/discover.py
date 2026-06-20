"""Scan jobs that populate the library in bulk.

Two background jobs, both mirroring ftpbackup.BackupJob's shape (a uuid `id`, a
lock-guarded progress dict, snapshot()/cancel(), a run() driven on a daemon
thread), so the api layer can poll them through one pair of endpoints:

- FolderScanJob: walk a parent folder, turn every backup root beneath it into a
  library draft (newest snapshot wins per robot).
- NetworkScanJob: sweep a subnet for FANUC controllers over FTP and return the
  reachable ones, best-effort named from the controller (IP as the fallback).

Network code lives only here. Both jobs accept injectable factories so they run
fully offline under test (see tests/test_discover.py), the same way
ftpbackup.probe_controller takes an ftp_factory.
"""
from __future__ import annotations

import ftplib
import ipaddress
import logging
import socket
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import ftpbackup, session

log = logging.getLogger(__name__)

PORT = 21
PORT_TIMEOUT = 0.7        # fast TCP pre-check before the heavier FTP probe
SCAN_WORKERS = 48
_NAME_LS_TRIES = 8        # report .LS files to sniff for a robot name


# -- subnet helpers --------------------------------------------------------------

def local_ipv4() -> str:
    """The primary egress IPv4 (sends nothing - just inspects the routing pick)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


def default_cidr() -> str:
    """The local /24 to prefill the discover dialog, or "" if undeterminable."""
    ip = local_ipv4()
    if not ip:
        return ""
    try:
        return str(ipaddress.ip_network(ip + "/24", strict=False))
    except ValueError:
        return ""


def enumerate_hosts(cidr: str) -> list[str]:
    """Usable host addresses in a CIDR. A /32 (or /31) yields its literal address(es)."""
    net = ipaddress.ip_network(cidr, strict=False)
    hosts = [str(h) for h in net.hosts()]
    if not hosts:
        hosts = [str(net.network_address)]
    return hosts


def _mtime(path: str) -> float:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


def _tcp_open(host: str, port: int, timeout: float) -> bool:
    """Fast TCP pre-check so a /24 sweep doesn't wait on the FTP timeout per host."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# -- base job --------------------------------------------------------------------

class _ScanJob:
    kind = "scan"

    def __init__(self):
        self.id = uuid.uuid4().hex
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._p = {
            "id": self.id, "kind": self.kind, "status": "pending",
            "total": 0, "scanned": 0, "found": 0, "current": "",
            "results": [], "error": "",
        }

    def _set(self, **kw):
        with self._lock:
            self._p.update(kw)

    def _bump(self, current: str = ""):
        with self._lock:
            self._p["scanned"] += 1
            if current:
                self._p["current"] = current

    def _set_results(self, results: list):
        with self._lock:
            self._p["results"] = list(results)
            self._p["found"] = len(results)

    def _add_result(self, r: dict):
        with self._lock:
            self._p["results"].append(r)
            self._p["found"] = len(self._p["results"])

    def snapshot(self) -> dict:
        with self._lock:
            s = dict(self._p)
            s["results"] = list(self._p["results"])
        return s

    def cancel(self):
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()


# -- folder bulk scan ------------------------------------------------------------

class FolderScanJob(_ScanJob):
    """Turn a parent folder of several backups into a list of library drafts.

    draft_fn(root: Path) -> dict builds one draft from a backup root (api wires
    this to _draft_from_session so the heavy parsing stays there)."""
    kind = "folder"

    def __init__(self, parent, draft_fn, *, find_fn=session.find_backup_roots):
        super().__init__()
        self.parent = Path(parent)
        self._draft_fn = draft_fn
        self._find_fn = find_fn

    def run(self):
        try:
            self._set(status="scanning")
            roots = self._find_fn(self.parent)
            self._set(total=len(roots))
            drafts: list[dict] = []
            for root in roots:
                if self.cancelled:
                    self._set(status="cancelled")
                    return
                self._bump(current=str(root))
                try:
                    d = self._draft_fn(root)
                    if d:
                        drafts.append(d)
                except Exception as e:  # noqa: BLE001 - one bad folder shouldn't sink the scan
                    log.warning("bulk draft failed for %s: %s", root, e)
            self._set_results(_dedupe_newest(drafts))
            self._set(status="done")
        except Exception as e:  # noqa: BLE001
            log.exception("folder scan failed")
            self._set(status="error", error=f"{type(e).__name__}: {e}")


def _dedupe_newest(drafts: list[dict]) -> list[dict]:
    """One draft per robot name - keep the newest backup folder when a robot has
    several dated snapshots under the scanned tree."""
    best: dict[str, dict] = {}
    for d in drafts:
        key = (d.get("robot") or "").upper()
        cur = best.get(key)
        if cur is None or _mtime(d.get("latest_path", "")) > _mtime(cur.get("latest_path", "")):
            best[key] = d
    return sorted(best.values(), key=lambda d: (d.get("robot") or "").upper())


# -- network discovery -----------------------------------------------------------

class _StopRead(Exception):
    """Raised inside a retrlines callback to stop after the header line."""


class NetworkScanJob(_ScanJob):
    """Sweep a subnet for FANUC controllers reachable over FTP."""
    kind = "network"

    def __init__(self, cidr, *, port=PORT, port_timeout=PORT_TIMEOUT,
                 ftp_factory=ftplib.FTP, host_provider=enumerate_hosts,
                 port_check=_tcp_open, workers=SCAN_WORKERS):
        super().__init__()
        self.cidr = cidr
        self.port = int(port or PORT)
        self.port_timeout = port_timeout
        self._ftp_factory = ftp_factory
        self._host_provider = host_provider
        self._port_check = port_check
        self._workers = workers

    def run(self):
        try:
            self._set(status="scanning")
            hosts = self._host_provider(self.cidr)
            self._set(total=len(hosts))
            with ThreadPoolExecutor(max_workers=self._workers) as ex:
                futs = {ex.submit(self._scan_host, h): h for h in hosts}
                for fut in as_completed(futs):
                    self._bump(current=futs[fut])
                    if self.cancelled:
                        continue
                    try:
                        r = fut.result()
                    except Exception:  # noqa: BLE001
                        r = None
                    if r:
                        self._add_result(r)
            self._set(status="cancelled" if self.cancelled else "done")
        except Exception as e:  # noqa: BLE001
            log.exception("network scan failed")
            self._set(status="error", error=f"{type(e).__name__}: {e}")

    def _scan_host(self, host: str):
        if self.cancelled:
            return None
        if not self._port_check(host, self.port, self.port_timeout):
            return None
        info = ftpbackup.probe_controller(host, port=self.port, ftp_factory=self._ftp_factory)
        if not info.get("reachable"):
            return None
        banner = info.get("banner", "") or ""
        if "FANUC" not in banner.upper() and not info.get("has_md"):
            return None  # an FTP server, but not a FANUC controller
        return {
            "host": host,
            "name": self._resolve_name(host),
            "banner": banner,
            "has_md": bool(info.get("has_md")),
            "has_fr": bool(info.get("has_fr")),
        }

    def _resolve_name(self, host: str) -> str:
        """Best-effort robot name from the controller's host comms / report
        headers over FTP. Returns "" on any failure - the caller falls back to
        the IP. Reads only the first line of a few report .LS files, so it stays
        gentle on a live robot."""
        ftp = None
        try:
            ftp = self._ftp_factory(timeout=ftpbackup.CONNECT_TIMEOUT)
            ftp.connect(host, self.port)
            ftp.login("", "")
            try:
                ftp.cwd("MD:")
            except ftplib.all_errors:
                return ""
            ls = [n for n in ftp.nlst() if n.upper().endswith(".LS")][:_NAME_LS_TRIES]
            for n in ls:
                first = {"line": ""}

                def grab(line, _f=first):
                    _f["line"] = line
                    raise _StopRead

                try:
                    ftp.retrlines("RETR " + n, grab)
                except _StopRead:
                    pass
                except ftplib.all_errors:
                    continue
                m = session._REPORT_HEADER.match(first["line"])
                if m:
                    return m.group(2)
            return ""
        except Exception:  # noqa: BLE001 - name is a nicety; never let it sink discovery
            return ""
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except Exception:  # noqa: BLE001
                    try:
                        ftp.close()
                    except Exception:  # noqa: BLE001
                        pass
