r"""Seed a BackupViewer library with a building's robot list.

Hand a coworker this file + a robots.json (shaped {"LINE": {"ROBOT": "ip"}}).
It builds <library>\<plant>\<LINE>\<FULL NAME>\robot.json for every robot in
the list — names expanded to the plant convention (080R01 in line RBB01 ->
RB080R01B01) — and silently skips anything they already have: an existing
folder with that name, or any robot in that line whose robot.json already
claims the IP (their library may use different names; nothing is duplicated
and nothing of theirs is ever touched). Safe to re-run any time the list
grows. BackupViewer's scan then shows every robot, IP attached, ready to
back up — no backups required first.

Runs on plain Python 3 (standard library only; BackupViewer not needed).

Usage:
    python seed_library.py
        prompts for the list / library folder / plant (with sensible defaults)
    python seed_library.py --list robots.json --root D:\\RobotBackups --plant "My Plant" [--dry-run] [--yes]
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import uuid
from pathlib import Path

LINE_RE = re.compile(r"^([A-Z]{2})(B\d{2,})$", re.IGNORECASE)      # RBB01 -> RB + B01
ROBOT_RE = re.compile(r"^\d{3}R\d{2}$", re.IGNORECASE)             # 080R01
FULL_RE = re.compile(r"^[A-Z]{2}\d{2,4}R\d{2}B\d{2}$", re.IGNORECASE)


def full_name(line: str, robot: str) -> str:
    """Expand a short robot key to the plant convention: line RBB01 + 080R01
    -> RB080R01B01. Already-full names and one-offs (labs etc.) pass through."""
    if FULL_RE.match(robot):
        return robot
    m = LINE_RE.match(line or "")
    if m and ROBOT_RE.match(robot or ""):
        return m.group(1).upper() + robot.upper() + m.group(2).upper()
    return robot


def read_json(p: Path) -> dict:
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def app_library_root() -> str:
    """The coworker's configured BackupViewer library folder, if the app is
    installed — the natural default for where to seed."""
    import os
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        root = read_json(Path(appdata) / "BackupViewer" / "settings.json").get("library_root", "")
        if root:
            return root
    home = os.environ.get("USERPROFILE", "") or str(Path.home())
    return str(Path(home) / "RobotBackups")


def ask(prompt: str, default: str) -> str:
    val = input(f"{prompt} [{default}]: ").strip()
    return val or default


def line_ip_claims(line_dir: Path) -> set:
    """Every IP any robot.json in this line folder already claims."""
    ips: set = set()
    if not line_dir.is_dir():
        return ips
    try:
        for rdir in line_dir.iterdir():
            if rdir.is_dir():
                for ip in read_json(rdir / "robot.json").get("ips") or []:
                    if ip:
                        ips.add(ip)
    except OSError:
        pass
    return ips


def sidecar(ip: str) -> dict:
    """id + config only (schema 2): the folder's location/name IS the robot's
    plant/line/name — the app derives identity from the tree, never from here."""
    return {
        "schema": 2, "id": uuid.uuid4().hex,
        "model": "", "f_number": "", "ips": [ip],
        "ftp": {"user": "", "passive": True},
        "notes": "", "aliases": [],
        "updated": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", default="", help="robot list json: {line: {robot: ip}}")
    ap.add_argument("--root", default="", help="library folder to seed into")
    ap.add_argument("--plant", default="", help="plant folder name (created if missing)")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    list_path = Path(args.list or ask("robot list", str(here / "robots.json")))
    ip_list = read_json(list_path)
    if not ip_list:
        print(f"could not read a robot list from {list_path}")
        return 2

    root = Path(args.root or ask("library folder", app_library_root()))
    plant = args.plant
    if not plant:
        existing = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
        hint = existing[0] if len(existing) == 1 else ""
        if existing:
            print("existing plant folders here:", ", ".join(existing))
        plant = ask("plant folder to add the lines to", hint or "My Plant")

    plant_dir = root / plant
    create, skip_exists, skip_ip, claims = [], 0, 0, {}
    for line, robots in sorted(ip_list.items()):
        if not isinstance(robots, dict):
            continue
        line_dir = plant_dir / line
        if line not in claims:
            claims[line] = line_ip_claims(line_dir)
        for robot, ip in sorted(robots.items()):
            ip = (ip or "").strip()
            if not ip:
                continue
            name = full_name(line, robot)
            folder = line_dir / name
            if folder.exists():
                skip_exists += 1
            elif ip in claims[line]:
                skip_ip += 1                      # they already have this robot, named their way
            else:
                create.append((folder, line, name, ip))
                claims[line].add(ip)              # in-list duplicates don't double up either

    print(f"\nlibrary: {plant_dir}")
    print(f"robots to create:                    {len(create)}")
    print(f"already there (folder exists):       {skip_exists}")
    print(f"already there (IP known in line):    {skip_ip}")
    if create[:3]:
        print("examples:", ", ".join(f"{ln}\\{nm}" for _, ln, nm, _ in create[:3]))
    if args.dry_run or not create:
        print("dry run — nothing written." if args.dry_run else "nothing to do.")
        return 0
    if not args.yes and input("create these robot folders? [y/N]: ").strip().lower() != "y":
        print("cancelled — nothing written.")
        return 1

    made = 0
    for folder, line, name, ip in create:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            tmp = folder / "robot.json.tmp"
            tmp.write_text(json.dumps(sidecar(ip), indent=2), encoding="utf-8")
            tmp.replace(folder / "robot.json")
            made += 1
        except OSError as ex:
            print(f"  could not create {folder}: {ex}")
    print(f"created {made} robots. Open BackupViewer (or press rescan) to see them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
