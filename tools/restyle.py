r"""Clone one style's TP programs to a new style number - USB-ready.

Point it at a FANUC backup folder. Every S<FROM>* / STYLE<FROM>* program
(.ls only - the ASCII, load-ready form) is copied and renamed to the <TO>
number, and every reference inside the copies is rewritten to match:
/PROG headers, CALL / RUN targets, comments. The new style comes out
internally consistent:

    STYLE14.LS  (CALL S14PICK)   ->   STYLE04.LS  (CALL S04PICK)

Originals are never touched. The kit lands in a new folder NEXT TO the
backup, named after the robot (read from the backup's own report headers,
same as BackupViewer), holding only the new programs - drop it on a USB
stick and load.

BULK: point --backup at a folder OF backups instead (a line folder, a
whole plant, a folder of fresh ERBUs - any depth) and it finds every
backup underneath, groups them by robot (newest backup wins when a robot
has several), and writes one kit folder per robot inside a single wrapper:

    E:\LINEB01_STYLE04_from_STYLE14\
        RB080R01B01\  STYLE04.LS  S04PICK.LS ...
        RB080R02B01\  ...

Before writing anything it reports: what will be cloned, how many
references get rewritten, any TO-name that already exists on the robot
(it would be OVERWRITTEN at load time), any CALL whose target program
exists nowhere, and any FROM program that only exists in binary (.tp -
can't be cloned from ASCII).

Plain Python 3, standard library only.

Usage:
    python restyle.py                  prompts FROM/TO, backup = current folder
    python restyle.py 14 4            no prompts ('4' pads to '04' to match)
    python restyle.py 14 4 --backup "D:\Backups\PlantX\LINEB01" --out E:\
    python restyle.py 14 4 --backup "D:\Backups\RB080R01B01 070826" --dry-run
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

PREFIXES = ("STYLE", "S")            # style-program name prefixes; edit to taste
BINARY_PROGRAM_EXTS = {".TP", ".PC", ".MR"}
MAX_SCAN_FILES = 20_000              # same guard BackupViewer uses: don't walk C:\ by accident
MAX_BACKUPS = 500                    # bulk-discovery sanity cap
DEFAULT_HOSTNAMES = {"ROBOT"}        # factory default - identifies nothing (same rule as the app)

_ALT = "|".join(PREFIXES)
_CALL = re.compile(r"\b(?:CALL|RUN)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_COMMENTED = re.compile(r"^\s*\d+:\s*!")                      # '  7:  !...' commented-out body line
_REPORT_HEADER = re.compile(r"^(\S+)\s+Robot Name\s+(\S+)")   # LOGBOOK.LS etc. open with this
_PROG_HEADER = re.compile(r"^\s*/PROG\s+([A-Za-z0-9_]+)")


def name_pattern(num: str) -> re.Pattern:
    """<PREFIX><num> at an identifier start, never swallowing longer numbers:
    FROM=1 must not touch S14PICK, FROM=14 must not touch S140DD."""
    return re.compile(rf"(?<![A-Za-z0-9_])({_ALT}){num}(?![0-9])", re.IGNORECASE)


def spaced_pattern(num: str) -> re.Pattern:
    """'STYLE 14' the way pendant comments write it."""
    return re.compile(rf"(?<![A-Za-z0-9_])(STYLE) {num}(?![0-9])", re.IGNORECASE)


def read_text(p: Path) -> str:
    raw = p.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("latin-1")     # byte-faithful: round-trips odd bytes, keeps CRLF


def first_line(p: Path) -> str:
    try:
        with open(p, "rb") as f:
            raw = f.read(400)
    except OSError:
        return ""
    text = raw.decode("latin-1", "replace")
    return text.splitlines()[0] if text else ""


def collect_files(backup: Path) -> dict[str, Path]:
    """Every file under the backup keyed by UPPER basename, deduped the way
    BackupViewer does it - the shallowest copy wins (mdb/ dumps duplicate)."""
    best: dict[str, Path] = {}
    count = 0
    for p in sorted(backup.rglob("*")):
        if not p.is_file():
            continue
        count += 1
        if count > MAX_SCAN_FILES:
            raise RuntimeError(f"more than {MAX_SCAN_FILES} files under {backup} - "
                               f"is this really a backup folder?")
        key = p.name.upper()
        cur = best.get(key)
        if cur is None or len(p.relative_to(backup).parts) < len(cur.relative_to(backup).parts):
            best[key] = p
    return best


def discover_backups(container: Path) -> list[Path]:
    """Backup roots under container: the shallowest folders that directly hold
    .ls files. A backup's own subfolders (mdb/ dumps) stay inside it."""
    roots: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(container):
        if any(f.upper().endswith(".LS") for f in filenames):
            roots.append(Path(dirpath))
            dirnames[:] = []          # this is one backup - don't mine its insides
            if len(roots) > MAX_BACKUPS:
                sys.exit(f"more than {MAX_BACKUPS} backup folders under {container} - wrong folder?")
        else:
            dirnames.sort()
    return roots


def robot_name(backup: Path, files: dict[str, Path]) -> str:
    """The app's order: report-header name, then SUMMARY.DG $HOSTNAME, then
    the backup folder's own name."""
    preferred = [k for k in ("LOGBOOK.LS", "ERRALL.LS", "ERRHIST.LS") if k in files]
    rest = sorted(k for k in files if k.endswith(".LS") and k not in preferred)
    for key in preferred + rest:
        line = first_line(files[key])
        if line.startswith("/PROG"):
            continue
        m = _REPORT_HEADER.match(line)
        if m:
            return m.group(2)
    if "SUMMARY.DG" in files:
        try:
            for line in read_text(files["SUMMARY.DG"]).splitlines():
                m = re.match(r"\s*\$HOSTNAME\s*:?\s*(\S+)", line)
                if m:
                    return m.group(1).strip("'\"")
        except OSError:
            pass
    return backup.name


def safe_name(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._ -]+", "_", s).strip(" ._")
    return s or "ROBOT"


def next_free(parent: Path, name: str) -> Path:
    """parent/name, or parent/name_2 ... if a previous run already sits there."""
    kit = parent / name
    n = 2
    while kit.exists():
        if n > 99:
            sys.exit(f"gave up finding a free folder name for {name} in {parent}")
        kit = parent / f"{name}_{n}"
        n += 1
    return kit


def ask_num(label: str, given: str | None) -> str:
    """A style number as a digit string. Accepts '14', '04', '4', 'S14', 'STYLE14'."""
    if given is not None:
        num = re.sub(r"^[A-Za-z]+", "", given.strip())
        if num.isdigit() and 1 <= len(num) <= 3:
            return num
        sys.exit(f"bad style number: {given!r} (want 1-3 digits, e.g. 14)")
    while True:
        try:
            raw = input(f"{label} style number (e.g. 14): ").strip()
        except EOFError:
            sys.exit(1)
        num = re.sub(r"^[A-Za-z]+", "", raw)
        if num.isdigit() and 1 <= len(num) <= 3:
            return num
        print("  just the number, 1-3 digits ('14', '4', 'S14' and 'STYLE14' all work)")


def plan_backup(backup: Path, from_num: str, to_num: str,
                pat: re.Pattern, spaced: re.Pattern) -> dict:
    """Everything needed to clone one backup - nothing is written here."""
    files = collect_files(backup)

    def renum(m: re.Match) -> str:
        return m.group(1) + to_num

    # -- pick the programs to clone (by name AND content: report dumps are .LS too) --
    clones: list[Path] = []
    skipped_reports: list[str] = []
    ls_count = 0
    for key in sorted(files):
        if not key.endswith(".LS"):
            continue
        ls_count += 1
        p = files[key]
        if not pat.match(p.stem):
            continue
        if not first_line(p).startswith("/PROG"):
            skipped_reports.append(p.name)
            continue
        clones.append(p)

    # -- build every output in memory: kits are written all-or-nothing later --
    kit_files: list[tuple[str, str, int]] = []   # (new name, new text, refs rewritten)
    for p in clones:
        text = read_text(p)
        out, n1 = pat.subn(renum, text)
        out, n2 = spaced.subn(lambda m: m.group(1) + " " + to_num, out)
        kit_files.append((pat.sub(renum, p.stem) + p.suffix, out, n1 + n2))

    # -- safety checks -----------------------------------------------------------
    stem_exts: dict[str, set[str]] = {}
    for key in files:
        stem, dot, ext = key.rpartition(".")
        if dot:
            stem_exts.setdefault(stem, set()).add("." + ext)

    out_stems = {Path(n).stem.upper() for n, _, _ in kit_files}
    to_name = re.compile(rf"^({_ALT}){to_num}(?![0-9])", re.IGNORECASE)
    known = out_stems | set(stem_exts)
    missing: dict[str, set[str]] = {}
    warn: list[str] = []

    for new_name, text, _ in kit_files:
        m = _PROG_HEADER.match(text)
        if not m or m.group(1).upper() != Path(new_name).stem.upper():
            warn.append(f"{new_name}: /PROG header says '{m.group(1) if m else '?'}', which "
                        f"doesn't match the file name - check the source file")
        for line in text.splitlines():
            if _COMMENTED.match(line):
                continue
            for c in _CALL.finditer(line):
                callee = c.group(1).upper()
                if to_name.match(callee) and callee not in known:
                    missing.setdefault(callee, set()).add(Path(new_name).stem.upper())

    for st in sorted(out_stems):
        if st in stem_exts:
            warn.append(f"{st} already exists in this backup ({', '.join(sorted(stem_exts[st]))}) - "
                        f"loading the kit will OVERWRITE it on the robot")
    for callee, callers in sorted(missing.items()):
        warn.append(f"{callee} is called by {', '.join(sorted(callers))} but exists nowhere "
                    f"(kit or backup) - will fault at run time")
    for st, exts in sorted(stem_exts.items()):
        if pat.match(st) and ".LS" not in exts and exts & BINARY_PROGRAM_EXTS:
            warn.append(f"{st} exists only as binary ({', '.join(sorted(exts & BINARY_PROGRAM_EXTS))}) - "
                        f"NOT cloned; take an ASCII (.ls) backup to include it")
    for nm in skipped_reports:
        warn.append(f"{nm} matches the name but is a report dump, not a TP program - skipped")

    raw = robot_name(backup, files)
    identity = raw if raw and raw.upper() not in DEFAULT_HOSTNAMES else backup.name
    return {
        "backup": backup,
        "identity": identity,
        "clones": clones,
        "kit_files": kit_files,
        "warnings": warn,
        "ls_count": ls_count,
        "refs": sum(n for _, _, n in kit_files),
        "mtime": max((p.stat().st_mtime for p in files.values()), default=0.0),
    }


def write_kit(kit: Path, kit_files: list[tuple[str, str, int]]) -> None:
    kit.mkdir(parents=True)
    for new_name, text, _ in kit_files:
        (kit / new_name).write_bytes(text.encode("latin-1"))


def print_clone_lines(plan: dict, indent: str = "  ") -> None:
    w = max(len(p.name) for p in plan["clones"])
    for p, (new_name, _, nref) in zip(plan["clones"], plan["kit_files"]):
        print(f"{indent}{p.name:<{w}}  ->  {new_name:<{w}}   {nref:>3} refs rewritten")


def run_single(backup: Path, from_num: str, to_num: str, args) -> int:
    try:
        plan = plan_backup(backup, from_num, to_num,
                           name_pattern(from_num), spaced_pattern(from_num))
    except (OSError, RuntimeError) as e:
        print(f"cannot read the backup: {e}")
        return 1

    if not plan["clones"]:
        print(f"no S{from_num}/STYLE{from_num} programs found "
              f"({plan['ls_count']} .ls files scanned in {backup})")
        return 1

    robot = safe_name(plan["identity"])
    parent = Path(args.out).resolve() if args.out else backup.parent
    kit = next_free(parent, args.name or f"{robot}_STYLE{to_num}_from_STYLE{from_num}")

    print()
    print(f"Restyle: STYLE{from_num} -> STYLE{to_num}   (prefixes: {', '.join(PREFIXES)})")
    print(f"Backup : {backup}")
    print(f"Robot  : {robot}")
    print(f"Clone  : {len(plan['clones'])} programs (of {plan['ls_count']} .ls files in the backup)")
    print()
    print_clone_lines(plan)
    if plan["warnings"]:
        print()
        print("Warnings:")
        for line in plan["warnings"]:
            print(f"  !! {line}")

    print()
    if args.dry_run:
        print(f"DRY RUN - nothing written. Kit would be: {kit}")
        return 0
    try:
        write_kit(kit, plan["kit_files"])
    except OSError as e:
        shutil.rmtree(kit, ignore_errors=True)
        print(f"could not write the kit: {e}")
        return 1
    print(f"Kit    : {kit}  ({len(plan['kit_files'])} files)")
    print("Ready for USB. Originals untouched.")
    return 0


def run_bulk(container: Path, roots: list[Path], from_num: str, to_num: str, args) -> int:
    pat, spaced = name_pattern(from_num), spaced_pattern(from_num)

    plans: list[dict] = []
    broken: list[str] = []
    for r in sorted(roots):
        try:
            plans.append(plan_backup(r, from_num, to_num, pat, spaced))
        except (OSError, RuntimeError) as e:
            broken.append(f"{r.relative_to(container)}: {e} - skipped")

    # one kit per robot: group the backups, newest one WITH the style wins
    groups: dict[str, list[dict]] = {}
    for pl in plans:
        groups.setdefault(pl["identity"].upper(), []).append(pl)

    chosen: list[dict] = []
    skipped: list[dict] = []
    for key in sorted(groups):
        group = groups[key]
        with_clones = [p for p in group if p["clones"]]
        if not with_clones:
            skipped.append(group[0])
            continue
        pick = max(with_clones, key=lambda p: p["mtime"])
        newer_empty = [p for p in group if not p["clones"] and p["mtime"] > pick["mtime"]]
        if newer_empty:
            newest = max(newer_empty, key=lambda p: p["mtime"])
            pick["warnings"].append(f"newest backup '{newest['backup'].name}' has no "
                                    f"STYLE{from_num} programs - cloned from older "
                                    f"'{pick['backup'].name}'")
        pick["group_n"] = len(group)
        chosen.append(pick)

    # -- destination: <out or prompt or next-to-source>\<SOURCE>_STYLE.. wrapper --
    default_parent = container.parent
    if args.out:
        parent = Path(args.out).resolve()
    elif not args.dry_run and sys.stdin.isatty():
        raw = input(f"Destination folder for the kits [{default_parent}]: ").strip().strip('"')
        parent = Path(raw).resolve() if raw else default_parent
    else:
        parent = default_parent
    src_label = safe_name(container.name or container.anchor.strip("\\/:") or "BACKUPS")
    wrapper = next_free(parent, args.name or f"{src_label}_STYLE{to_num}_from_STYLE{from_num}")

    # -- report ------------------------------------------------------------------
    print()
    print(f"Restyle (bulk): STYLE{from_num} -> STYLE{to_num}   (prefixes: {', '.join(PREFIXES)})")
    print(f"Source : {container}   ({len(roots)} backup folders, {len(groups)} robots)")
    print(f"Kits to: {wrapper}")
    print()
    if not chosen:
        print(f"no S{from_num}/STYLE{from_num} programs found in any backup here")
        return 1
    w = max(len(safe_name(p["identity"])) for p in chosen + skipped)
    for pick in chosen:
        extra = f"   from '{pick['backup'].name}' ({pick['group_n']} backups)" \
                if pick.get("group_n", 1) > 1 else ""
        flag = f"   [{len(pick['warnings'])} warnings]" if pick["warnings"] else ""
        print(f"  {safe_name(pick['identity']):<{w}}  {len(pick['clones']):>2} programs  "
              f"{pick['refs']:>4} refs{extra}{flag}")
        if args.verbose:
            print_clone_lines(pick, indent="      ")
    for pl in skipped:
        print(f"  {safe_name(pl['identity']):<{w}}  no STYLE{from_num} programs - skipped")

    warn_lines = [f"{safe_name(p['identity'])}: {msg}" for p in chosen for msg in p["warnings"]]
    warn_lines += broken
    if warn_lines:
        print()
        print("Warnings:")
        for line in warn_lines:
            print(f"  !! {line}")

    print()
    if args.dry_run:
        print(f"DRY RUN - nothing written. {len(chosen)} kits would go to: {wrapper}")
        return 0

    try:
        for pick in chosen:
            write_kit(wrapper / safe_name(pick["identity"]), pick["kit_files"])
    except OSError as e:
        shutil.rmtree(wrapper, ignore_errors=True)
        print(f"could not write the kits ({e}) - {wrapper} removed, nothing kept")
        return 1
    total = sum(len(p["kit_files"]) for p in chosen)
    print(f"{len(chosen)} kits written to {wrapper}  ({total} files)."
          + (f" {len(skipped)} robots had no STYLE{from_num}." if skipped else ""))
    print("Ready for USB. Originals untouched.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Clone one style's .ls programs to a new style number (USB-ready kit folders). "
                    "Point --backup at one backup, or at a whole line/folder of backups for "
                    "one kit per robot.",
        epilog=r'examples:  restyle.py 14 4     restyle.py 14 4 --backup "D:\Backups\PlantX\LINEB01" --out E:\kits',
    )
    ap.add_argument("from_num", nargs="?", metavar="FROM", help="style number to clone from, e.g. 14")
    ap.add_argument("to_num", nargs="?", metavar="TO", help="style number to create, e.g. 4 or 04")
    ap.add_argument("--backup", default=".", help="a backup folder OR a folder of backups "
                                                  "(default: the current folder)")
    ap.add_argument("--out", help="create the kit folder(s) HERE (default: next to the source)")
    ap.add_argument("--name", help="kit/wrapper folder name (default: <ROBOT or SOURCE>_STYLE<TO>_from_STYLE<FROM>)")
    ap.add_argument("--dry-run", action="store_true", help="report everything, write nothing")
    ap.add_argument("-v", "--verbose", action="store_true", help="bulk mode: list every file per robot")
    args = ap.parse_args(argv)

    source = Path(args.backup).resolve()
    if not source.is_dir():
        print(f"not a folder: {source}")
        return 1

    from_num = ask_num("Clone FROM", args.from_num)
    to_num = ask_num("Clone TO  ", args.to_num)
    if len(to_num) < len(from_num):
        to_num = to_num.zfill(len(from_num))
        print(f"note: TO padded to '{to_num}' to match the width of '{from_num}'")
    if to_num == from_num:
        print("FROM and TO are the same number - nothing to do.")
        return 1

    roots = discover_backups(source)
    if not roots:
        print(f"no .ls files anywhere under {source}")
        return 1
    if len(roots) == 1:
        return run_single(source, from_num, to_num, args)
    return run_bulk(source, roots, from_num, to_num, args)


if __name__ == "__main__":
    sys.exit(main())
