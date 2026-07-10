"""Stamp a building IP list onto the library folder tree.

Reads an IP list shaped {"LINE": {"ROBOT": "ip", ...}, ...} and, for each
robot, makes sure <root>/<plant>/<LINE>/<ROBOT> exists and carries a
robot.json sidecar with that IP. The app's scan then shows every robot in
the building - with its IP - even before its first backup, so a whole-plant
bulk backup can be driven straight from the library screen.

Files are law: this writes ONLY inside <root>/<plant>, only robot.json
sidecars (atomic tmp+replace) and missing robot folders. Existing sidecar
fields are preserved; the IP is added to its ips list if absent. Backup data
is never touched. Undo = delete the files listed in the run manifest.

Usage:
    python tools/apply_ip_list.py --list robots.json --plant "My Plant" [--root PATH] [--apply]

Dry-run by default: prints what WOULD change. Pass --apply to write.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from backupviewer import library, settings  # noqa: E402  (sidecar + root conventions)


def _read_json(p: Path) -> dict:
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_sidecar(folder: Path, data: dict) -> None:
    tmp = folder / (library.SIDECAR + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(folder / library.SIDECAR)


def _fresh_sidecar(ip: str) -> dict:
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
    ap.add_argument("--list", required=True, help="IP list json: {line: {robot: ip}}")
    ap.add_argument("--plant", required=True, help="plant folder name under the library root")
    ap.add_argument("--root", default="", help="library root (default: the app's configured root)")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run report)")
    args = ap.parse_args()

    ip_list = _read_json(Path(args.list))
    if not ip_list:
        print(f"could not read an IP list from {args.list}")
        return 2
    root = Path(args.root) if args.root else Path(settings.library_root())
    plant_dir = root / args.plant
    if not plant_dir.is_dir():
        print(f"plant folder does not exist: {plant_dir}")
        return 2

    created, sidecarred, updated, ok, mismatched = [], [], [], [], []
    for line, robots in sorted(ip_list.items()):
        if not isinstance(robots, dict):
            continue
        for robot, ip in sorted(robots.items()):
            ip = (ip or "").strip()
            if not ip:
                continue
            folder = plant_dir / line / robot
            sidecar = folder / library.SIDECAR
            if sidecar.is_file():
                data = _read_json(sidecar)
                ips = [x for x in (data.get("ips") or []) if x]
                if ip in ips:
                    ok.append(folder)
                    continue
                if ips:
                    # the sidecar (usually from a live backup) says something
                    # else - keep its word first, append the list's IP after
                    mismatched.append((folder, ips[0], ip))
                data["ips"] = ips + [ip]
                data["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
                if args.apply:
                    _write_sidecar(folder, data)
                updated.append(sidecar)
            else:
                existed = folder.is_dir()
                if args.apply:
                    folder.mkdir(parents=True, exist_ok=True)
                    _write_sidecar(folder, _fresh_sidecar(ip))
                (sidecarred if existed else created).append(sidecar)

    # same-line duplicate-IP report: an ERBU short-name folder (010R01) and an
    # app full-name folder (RB010R01B01) for the SAME physical robot both end
    # up claiming its IP - a bulk backup would hit that robot twice. These are
    # merge/tidy candidates, listed so nothing is silently doubled.
    twins = []
    for line_dir in sorted(p for p in plant_dir.iterdir() if p.is_dir()):
        claims: dict = {}
        for rdir in sorted(p for p in line_dir.iterdir() if p.is_dir()):
            sc = rdir / library.SIDECAR
            data = _read_json(sc) if sc.is_file() else {}
            for ip in data.get("ips") or []:
                claims.setdefault(ip, []).append(rdir.name)
        # pending dry-run writes count as claims too
        if not args.apply:
            robots = ip_list.get(line_dir.name) or {}
            for robot, ip in robots.items():
                names = claims.setdefault((ip or "").strip(), [])
                if robot not in names:
                    names.append(robot)
        for ip, names in sorted(claims.items()):
            if ip and len(names) > 1:
                twins.append((line_dir.name, ip, names))

    mode = "APPLIED" if args.apply else "DRY RUN (nothing written; pass --apply)"
    print(f"== {mode} ==")
    print(f"already had the IP:            {len(ok)}")
    print(f"sidecars updated (IP added):   {len(updated)}")
    print(f"sidecars added to existing robot folders: {len(sidecarred)}")
    print(f"NEW folders+sidecars created:  {len(created)}")
    if mismatched:
        print(f"IP mismatches (sidecar kept first, list appended): {len(mismatched)}")
        for folder, have, want in mismatched[:20]:
            print(f"   {folder.parent.name}/{folder.name}: sidecar says {have}, list says {want}")
    if twins:
        print(f"same-line duplicate IP claims (merge/tidy candidates): {len(twins)}")
        for line, ip, names in twins[:30]:
            print(f"   {line}: {ip} -> {', '.join(names)}")
        if len(twins) > 30:
            print(f"   ... and {len(twins) - 30} more")
    if args.apply:
        manifest = Path(args.list).with_suffix(".applied.txt")
        manifest.write_text(
            "\n".join(["# files written by apply_ip_list.py (delete these to undo)"]
                      + [str(p) for p in updated + sidecarred + created]) + "\n",
            encoding="utf-8")
        print(f"undo manifest: {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
