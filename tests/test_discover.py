"""Discover + bulk-scan unit tests - fully offline (synthetic folders + a fake
FTP), so they touch neither the network nor a user's %APPDATA% and are safe in
the public repo. Mirrors the ftp_factory injection style of test_ftpbackup.py."""
import ftplib
import os

from backupviewer import discover, session


# -- folder backup detection ----------------------------------------------------

def _touch(d, name):
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("x", encoding="utf-8")


def test_looks_like_backup(tmp_path):
    md = tmp_path / "MD"
    _touch(md, "SUMMARY.DG")
    assert session.looks_like_backup(md) is True

    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "notes.txt").write_text("hi", encoding="utf-8")
    assert session.looks_like_backup(plain) is False

    maint = tmp_path / "maint"
    (maint / "mnt_data").mkdir(parents=True)
    assert session.looks_like_backup(maint) is True


def test_find_backup_roots_latest_style(tmp_path):
    # a per-line Latest/ mirror: one backup per robot folder
    parent = tmp_path / "Latest"
    _touch(parent / "R1", "SUMMARY.DG")
    _touch(parent / "R2", "SYSTEM.VA")
    roots = session.find_backup_roots(parent)
    assert sorted(r.name for r in roots) == ["R1", "R2"]


def test_find_backup_roots_nested_and_empty(tmp_path):
    # a LINE/ROBOT/<date>/<time> tree: the time folder is the root, descended to
    deep = tmp_path / "LINE" / "ROBOT" / "2026_01_01" / "12_00_00"
    _touch(deep, "SUMMARY.DG")
    roots = session.find_backup_roots(tmp_path / "LINE")
    assert [r.name for r in roots] == ["12_00_00"]

    empty = tmp_path / "empty"
    (empty / "sub").mkdir(parents=True)
    assert session.find_backup_roots(empty) == []


def test_folder_scan_job_dedupes_newest(tmp_path):
    # same robot, two dated snapshots -> only the newest folder is kept
    old = tmp_path / "R1" / "2026_01_01"
    new = tmp_path / "R1" / "2026_02_02"
    _touch(old, "SUMMARY.DG")
    _touch(new, "SUMMARY.DG")
    os.utime(old, (1_600_000_000, 1_600_000_000))
    os.utime(new, (1_700_000_000, 1_700_000_000))

    def draft_fn(root):
        return {"robot": "R1", "latest_path": str(root), "backup_type": "MD"}

    job = discover.FolderScanJob(tmp_path, draft_fn)
    job.run()
    snap = job.snapshot()
    assert snap["status"] == "done"
    assert len(snap["results"]) == 1
    assert snap["results"][0]["latest_path"] == str(new)


# -- network discovery -----------------------------------------------------------

class FakeFTP:
    """A FANUC controller at 10.0.0.5; any other host answers like a plain ftpd.
    Implements only the surface probe_controller + _resolve_name actually use."""

    def __init__(self, timeout=None):
        self._cwd = "/"
        self.host = None

    def connect(self, host, port=21):
        self.host = host

    def login(self, user="", passwd=""):
        pass

    def set_pasv(self, flag):
        pass

    def getwelcome(self):
        return "220 FANUC Robot FTP server ready" if self.host == "10.0.0.5" else "220 generic ftpd"

    def cwd(self, path):
        if path in ("/", ""):
            self._cwd = "/"
            return "250 ok"
        if path.rstrip("/").upper() == "MD:" and self.host == "10.0.0.5":
            self._cwd = "MD:"
            return "250 ok"
        raise ftplib.error_perm("550 no such device: " + path)

    def nlst(self, *args):
        return ["MAIN.LS", "ERRALL.LS"] if self._cwd == "MD:" else []

    def retrlines(self, cmd, callback):
        name = cmd.split(" ", 1)[1]
        line = {"MAIN.LS": "/PROG MAIN",
                "ERRALL.LS": "ERRALL.LS   Robot Name COOLBOT 2026/01/01"}.get(name, "")
        callback(line)  # discover stops after the first line via an internal exception
        return "226 transfer complete"

    def quit(self):
        pass

    def close(self):
        pass


def test_network_scan_finds_only_fanuc():
    hosts = ["10.0.0.1", "10.0.0.5", "10.0.0.9"]
    job = discover.NetworkScanJob(
        "10.0.0.0/24",
        ftp_factory=lambda timeout=None: FakeFTP(timeout),
        host_provider=lambda cidr: hosts,
        port_check=lambda h, p, t: h in ("10.0.0.1", "10.0.0.5"),  # .9 is down
    )
    job.run()
    snap = job.snapshot()
    assert snap["status"] == "done"
    assert snap["total"] == 3
    got = {r["host"]: r for r in snap["results"]}
    assert set(got) == {"10.0.0.5"}                # only the FANUC host (.1 is a plain ftpd)
    assert got["10.0.0.5"]["name"] == "COOLBOT"    # name read from the report header
    assert got["10.0.0.5"]["has_md"] is True


def test_network_scan_name_falls_back_to_ip():
    class NoName(FakeFTP):
        def nlst(self, *args):
            return ["MAIN.LS"] if self._cwd == "MD:" else []  # no report header anywhere

    job = discover.NetworkScanJob(
        "10.0.0.0/24",
        ftp_factory=lambda timeout=None: NoName(timeout),
        host_provider=lambda cidr: ["10.0.0.5"],
        port_check=lambda h, p, t: True,
    )
    job.run()
    r = job.snapshot()["results"][0]
    assert r["host"] == "10.0.0.5"
    assert r["name"] == ""   # the UI falls back to the IP


def test_enumerate_hosts_single_and_range():
    assert discover.enumerate_hosts("127.0.0.1/32") == ["127.0.0.1"]
    assert len(discover.enumerate_hosts("10.0.0.0/24")) == 254
