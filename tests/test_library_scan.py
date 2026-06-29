"""scan_library_root: the backup folder tree is the source of truth; library.json
is a local overlay. Fully synthetic (a SUMMARY.DG marks each snapshot a backup),
so nothing here needs SampleBackup or a network."""
import json
import os
import shutil

from backupviewer import library, settings


def _iso(monkeypatch, tmp_path):
    appdir = tmp_path / "appdata"
    appdir.mkdir()
    monkeypatch.setattr(settings, "app_dir", lambda: appdir)


def _make_robot(root, plant, line, robot, snaps, *, rid="", notes="", ips=None, mirror=False):
    """snaps = [(date, time, mtime)]. Writes SUMMARY.DG + backup.json + notes.txt
    per snapshot, a robot.json at the robot folder, and optionally a Latest/
    mirror whose backup.json claims to be the newest (to prove it's excluded)."""
    base = root / plant / line / robot
    for i, (date, time, ts) in enumerate(snaps):
        d = base / date / time
        d.mkdir(parents=True, exist_ok=True)
        (d / "SUMMARY.DG").write_text("x", encoding="utf-8")
        (d / "backup.json").write_text(json.dumps({
            "robot": robot, "line": line, "plant": plant,
            "taken": date.replace("_", "-") + "T" + time.replace("_", ":"),
            "type": "all of above", "files": 3 + i, "bytes": 100, "source": "ftp",
        }), encoding="utf-8")
        (d / "notes.txt").write_text("snap note " + time + "\n", encoding="utf-8")
        os.utime(d, (ts, ts))
    (base / "robot.json").write_text(json.dumps({
        "schema": 1, "id": rid, "plant": plant, "line": line, "robot": robot,
        "model": "", "f_number": "", "ips": ips or [],
        "ftp": {"user": "", "passive": True}, "notes": notes,
    }), encoding="utf-8")
    if mirror:
        md = root / plant / line / "Latest" / robot
        md.mkdir(parents=True, exist_ok=True)
        (md / "SUMMARY.DG").write_text("x", encoding="utf-8")
        (md / "backup.json").write_text(json.dumps(
            {"robot": robot, "line": line, "plant": plant, "taken": "2099-01-01T00:00:00"}),
            encoding="utf-8")
    return base


def test_scan_builds_history_newest_first_excluding_mirror(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    root = tmp_path / "lib"
    _make_robot(root, "PlantA", "Line1", "ROBO1", [
        ("2026_01_01", "12_00_00", 1_600_000_000),
        ("2026_02_02", "09_30_00", 1_700_000_000),
    ], rid="id-robo1", notes="binpicker notes", ips=["1.2.3.4"], mirror=True)

    robots = library.scan_library_root(root)["robots"]
    assert len(robots) == 1
    e = robots[0]
    assert (e["robot"], e["line"], e["plant"]) == ("ROBO1", "Line1", "PlantA")
    assert e["id"] == "id-robo1"               # id carried from robot.json
    assert e["notes"] == "binpicker notes"
    assert e["ips"] == ["1.2.3.4"]
    assert len(e["backups"]) == 2              # two dated snaps; Latest/ mirror excluded
    assert e["backups"][0]["taken"] == "2026-02-02T09:30:00"   # newest first
    assert e["backups"][0]["note"] == "snap note 09_30_00"     # per-snap notes.txt
    assert e["latest_path"].endswith(os.path.join("2026_02_02", "09_30_00"))
    assert "Latest" not in e["latest_path"]    # never the mirror


def test_rescan_preserves_overlay_edits(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    root = tmp_path / "lib"
    _make_robot(root, "P", "L", "R1", [("2026_01_01", "12_00_00", 1_600_000_000)], rid="rid-1")
    library.scan_library_root(root)

    e = library.list_robots()["robots"][0]
    library.update_robot(e["id"], {"robot": "R1-RENAMED", "notes": "field note", "hidden": True})

    data = library.scan_library_root(root)     # a second scan must not clobber edits
    assert len(data["robots"]) == 1
    e2 = data["robots"][0]
    assert e2["robot"] == "R1-RENAMED"         # overlay/user wins for identity
    assert e2["notes"] == "field note"
    assert e2["hidden"] is True
    assert len(e2["backups"]) == 1             # disk still authoritative for history


def test_vanished_folder_kept_and_marked_stale(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    root = tmp_path / "lib"
    _make_robot(root, "P", "L", "R1", [("2026_01_01", "12_00_00", 1_600_000_000)], rid="rid-1")
    _make_robot(root, "P", "L", "R2", [("2026_01_01", "12_00_00", 1_600_000_000)], rid="rid-2")
    library.scan_library_root(root)

    shutil.rmtree(root / "P" / "L" / "R2")     # someone deleted R2 in Explorer
    by = {e["robot"]: e for e in library.scan_library_root(root)["robots"]}
    assert set(by) == {"R1", "R2"}             # R2 kept (never auto-deleted)
    assert by["R2"]["stale"] is True
    assert by["R1"]["stale"] is False


def test_sidecar_round_trip_carries_identity_to_a_fresh_library(monkeypatch, tmp_path):
    """The portability promise: add a robot -> robot.json is written (no password);
    wipe the index (a coworker's machine) and a scan rebuilds the same robot."""
    _iso(monkeypatch, tmp_path)
    root = tmp_path / "lib"
    snap = root / "P" / "L" / "R7" / "2026_03_03" / "08_00_00"
    snap.mkdir(parents=True)
    (snap / "SUMMARY.DG").write_text("x", encoding="utf-8")
    (snap / "backup.json").write_text(json.dumps(
        {"robot": "R7", "line": "L", "plant": "P", "taken": "2026-03-03T08:00:00"}),
        encoding="utf-8")
    robot_dir = root / "P" / "L" / "R7"

    e = library.add_robot({"robot": "R7", "line": "L", "plant": "P",
                           "notes": "travels with the folder", "ips": ["10.0.0.7"],
                           "ftp": {"user": "fanuc", "passive": True},
                           "history_root": str(robot_dir)})
    rj = json.loads((robot_dir / "robot.json").read_text(encoding="utf-8"))
    assert rj["id"] == e["id"] and rj["notes"] == "travels with the folder"
    assert "passwd" not in rj and "password" not in json.dumps(rj)   # never a password
    assert rj["ftp"]["user"] == "fanuc"

    (settings.app_dir() / "library.json").unlink()      # a fresh machine
    data = library.scan_library_root(root)
    assert len(data["robots"]) == 1
    e2 = data["robots"][0]
    assert e2["id"] == e["id"]                  # id travelled via robot.json
    assert e2["robot"] == "R7"
    assert e2["notes"] == "travels with the folder"
    assert e2["ftp"]["user"] == "fanuc"
    assert len(e2["backups"]) == 1


def test_scan_missing_root_is_a_noop(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    data = library.scan_library_root(tmp_path / "does_not_exist")
    assert data["robots"] == []


def test_set_hidden_survives_rescan(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    root = tmp_path / "lib"
    _make_robot(root, "P", "L", "R1", [("2026_01_01", "12_00_00", 1_600_000_000)], rid="rid-1")
    library.scan_library_root(root)
    e = library.list_robots()["robots"][0]

    library.set_hidden(e["id"], True)
    assert library.get_robot(e["id"])["hidden"] is True
    data = library.scan_library_root(root)          # rescan keeps the overlay flag
    assert data["robots"][0]["hidden"] is True


def test_delete_robot_files_guarded_to_root(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    root = tmp_path / "lib"
    settings.set_value("library_root", str(root))
    _make_robot(root, "P", "L", "R1", [
        ("2026_01_01", "12_00_00", 1_600_000_000),
        ("2026_02_02", "09_30_00", 1_700_000_000),
    ], rid="rid-1", mirror=True)
    library.scan_library_root(root)
    e = library.list_robots()["robots"][0]
    robot_dir = root / "P" / "L" / "R1"
    mirror = root / "P" / "L" / "Latest" / "R1"
    assert robot_dir.is_dir() and mirror.is_dir()

    res = library.delete_robot_files(e["id"])
    assert res["robot"] == "R1" and res["refused"] == []
    assert not robot_dir.exists()                   # robot folder gone
    assert not mirror.exists()                      # mirror gone too
    assert library.get_robot(e["id"]) is None       # and removed from the index


def test_lib_scan_folder_groups_multi_date(monkeypatch, tmp_path):
    """Pointing 'add from backup' at a folder of several dated snapshots of ONE
    robot yields a single draft carrying the full history (not a muddled scan)."""
    from backupviewer.api import Api
    _iso(monkeypatch, tmp_path)
    summary = '<H2><A NAME="1">Ethernet</A></H2><PRE>\n$HOSTNAME : TIMELINE1\n</PRE>\n'
    base = tmp_path / "lib" / "P" / "L" / "TIMELINE1"
    for i, (date, time) in enumerate([("2026_01_01", "08_00_00"),
                                      ("2026_02_02", "09_00_00"),
                                      ("2026_03_03", "10_00_00")]):
        d = base / date / time
        d.mkdir(parents=True)
        (d / "SUMMARY.DG").write_text(summary, encoding="cp1252")
        (d / "backup.json").write_text(json.dumps({
            "robot": "TIMELINE1", "line": "L", "plant": "P",
            "taken": date.replace("_", "-") + "T" + time.replace("_", ":")}), encoding="utf-8")
        os.utime(d, (1_600_000_000 + i, 1_600_000_000 + i))

    res = Api().lib_scan_folder(str(base))["data"]
    assert isinstance(res, dict) and not res.get("multi")
    assert res["robot"] == "TIMELINE1"
    assert len(res["backups"]) == 3                      # full dated history
    assert res["backups"][0]["taken"] == "2026-03-03T10:00:00"   # newest first
    assert res["latest_path"].endswith(os.path.join("2026_03_03", "10_00_00"))


def test_lib_open_augments_with_history(monkeypatch, tmp_path):
    from backupviewer.api import Api
    _iso(monkeypatch, tmp_path)
    snap = tmp_path / "lib" / "P" / "L" / "R1" / "2026_01_01" / "12_00_00"
    snap.mkdir(parents=True)
    (snap / "SUMMARY.DG").write_text("x", encoding="utf-8")
    e = library.add_robot({"robot": "R1", "latest_path": str(snap),
                           "backups": [{"path": str(snap), "taken": "2026-01-01T12:00:00"}]})
    m = Api().lib_open(e["id"], "latest")["data"]
    assert m["robot_id"] == e["id"]
    assert m["current_path"] == str(snap)
    assert len(m["backups"]) == 1


def test_delete_refuses_outside_root(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    inside = tmp_path / "lib"
    inside.mkdir()
    settings.set_value("library_root", str(inside))
    outside = tmp_path / "elsewhere" / "R9"          # a folder OUTSIDE the library root
    outside.mkdir(parents=True)
    (outside / "keep.txt").write_text("important", encoding="utf-8")
    e = library.add_robot({"robot": "R9", "history_root": str(outside)})

    res = library.delete_robot_files(e["id"])
    assert outside.is_dir() and (outside / "keep.txt").is_file()   # NOT deleted
    assert res["removed"] == [] and res["refused"]                 # explicitly refused
    assert library.get_robot(e["id"]) is None                      # still dropped from index
